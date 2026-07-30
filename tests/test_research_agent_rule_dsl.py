from __future__ import annotations

import unittest

import pandas as pd

from nero_core.research_agent.rule_dsl import (
    Condition,
    RuleAmbiguousError,
    compute_indicator_frame,
    count_triggers,
    evaluate_condition,
    find_trigger_timestamps,
    parse_structured_rule,
    rule_fires_at,
)

HOUR_MS = 3_600_000


def _candles(n: int, closes: list[float] | None = None) -> pd.DataFrame:
    """Synthetic hourly candles starting at an arbitrary epoch. `closes`
    overrides the default flat-then-noise series when the test needs specific
    values at specific indices."""
    if closes is None:
        closes = [100.0 + (i % 5) for i in range(n)]
    rows = []
    start = 1_700_000_000_000
    for i, close in enumerate(closes):
        rows.append(
            {
                "close_time": start + i * HOUR_MS,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


class ParseStructuredRuleTest(unittest.TestCase):
    def test_valid_single_condition_parses(self) -> None:
        rule = parse_structured_rule({"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]})
        self.assertEqual(len(rule.conditions), 1)
        self.assertEqual(rule.conditions[0].field, "zscore20")

    def test_multiple_conditions_and_together(self) -> None:
        rule = parse_structured_rule(
            {
                "conditions": [
                    {"field": "close", "op": "gt", "value": 100.0},
                    {"field": "ma50", "op": "gt", "value": 90.0},
                ]
            }
        )
        self.assertEqual(len(rule.conditions), 2)

    def test_non_dict_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule("z-score below -2")  # free text, not structured

    def test_missing_conditions_key_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({})

    def test_empty_conditions_list_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": []})

    def test_unsupported_field_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "macd", "op": "lt", "value": 30.0}]})

    def test_unsupported_op_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "close", "op": "between", "value": 5.0}]})

    def test_non_numeric_value_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "close", "op": "gt", "value": "high"}]})

    def test_boolean_value_raises_ambiguous(self) -> None:
        # bool is a subclass of int in Python -- must not silently pass as a numeric threshold
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "close", "op": "gt", "value": True}]})

    def test_rsi14_is_an_allowed_field(self) -> None:
        # RSI is MEAN_REVERSION's own core indicator -- added 2026-07-30 after its
        # absence meant a genuinely-supportable RSI hypothesis got rejected UNMEASURABLE,
        # indistinguishable from real ambiguity.
        rule = parse_structured_rule({"conditions": [{"field": "rsi14", "op": "lt", "value": 30.0}]})
        self.assertEqual(rule.conditions[0].field, "rsi14")

    def test_compare_to_field_parses(self) -> None:
        rule = parse_structured_rule({"conditions": [{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}]})
        self.assertEqual(rule.conditions[0].compare_to_field, "ma50")
        self.assertIsNone(rule.conditions[0].value)

    def test_both_value_and_compare_to_field_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "ma20", "op": "gt", "value": 1.0, "compare_to_field": "ma50"}]})

    def test_neither_value_nor_compare_to_field_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "ma20", "op": "gt"}]})

    def test_unsupported_compare_to_field_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "ma20", "op": "gt", "compare_to_field": "macd"}]})

    def test_compare_to_field_equal_to_field_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_structured_rule({"conditions": [{"field": "ma20", "op": "gt", "compare_to_field": "ma20"}]})


class IndicatorFrameTest(unittest.TestCase):
    def test_missing_required_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_indicator_frame(pd.DataFrame({"close": [1.0, 2.0]}))

    def test_ma20_only_populated_after_warmup(self) -> None:
        frame = compute_indicator_frame(_candles(25))
        self.assertTrue(frame["ma20"].iloc[:19].isna().all())
        self.assertFalse(pd.isna(frame["ma20"].iloc[19]))

    def test_ma20_never_uses_future_candles(self) -> None:
        # Change a FUTURE close and confirm every prior ma20 value is untouched -- the
        # defining no-lookahead property.
        base = _candles(30)
        mutated = base.copy()
        mutated.loc[29, "close"] = 99999.0

        frame_base = compute_indicator_frame(base)
        frame_mutated = compute_indicator_frame(mutated)

        pd.testing.assert_series_equal(
            frame_base["ma20"].iloc[:29], frame_mutated["ma20"].iloc[:29], check_names=False
        )

    def test_rsi14_warmup_rows_are_nan_not_fabricated(self) -> None:
        # nero_core.strategies.mean_reversion.rsi fillna(100.0)s its OWN warmup rows too
        # (correct for its caller -- "no losses yet" legitimately reads as RSI 100 once
        # warmed up); this module must re-mask those same rows back to NaN, or a warmup
        # row would look identical to a genuine, extreme overbought reading.
        frame = compute_indicator_frame(_candles(30, closes=[100.0 + i * 0.1 for i in range(30)]))
        self.assertTrue(frame["rsi14"].iloc[:14].isna().all())
        self.assertFalse(pd.isna(frame["rsi14"].iloc[14]))

    def test_rsi14_matches_the_reused_mean_reversion_function_after_warmup(self) -> None:
        from nero_core.strategies.mean_reversion import rsi as mean_reversion_rsi

        closes = [100.0, 98.0, 99.5, 97.0, 101.0, 102.0, 99.0, 98.5, 103.0, 104.0,
                  101.5, 100.5, 99.0, 98.0, 97.5, 99.0, 100.0, 101.0, 102.5, 103.0]
        frame = compute_indicator_frame(_candles(len(closes), closes=closes))
        expected = mean_reversion_rsi(pd.Series(closes), 14)
        # only compare from the point both consider warmed up (index 14 onward)
        pd.testing.assert_series_equal(
            frame["rsi14"].iloc[14:].reset_index(drop=True), expected.iloc[14:].reset_index(drop=True), check_names=False
        )


class FieldVsFieldEvaluationTest(unittest.TestCase):
    """evaluate_condition in isolation, on hand-built rows -- exact numbers,
    no dependency on compute_indicator_frame's own warmup behavior."""

    def test_gt_field_vs_field(self) -> None:
        condition = Condition(field="ma20", op="gt", compare_to_field="ma50")
        row = pd.Series({"ma20": 105.0, "ma50": 100.0})
        self.assertTrue(evaluate_condition(row, condition, None))
        row2 = pd.Series({"ma20": 95.0, "ma50": 100.0})
        self.assertFalse(evaluate_condition(row2, condition, None))

    def test_field_vs_field_none_when_either_side_is_nan(self) -> None:
        condition = Condition(field="ma20", op="gt", compare_to_field="ma50")
        self.assertIsNone(evaluate_condition(pd.Series({"ma20": float("nan"), "ma50": 100.0}), condition, None))
        self.assertIsNone(evaluate_condition(pd.Series({"ma20": 105.0, "ma50": float("nan")}), condition, None))

    def test_cross_above_field_vs_field(self) -> None:
        # A golden cross: ma20 was <= ma50, now ma20 > ma50.
        condition = Condition(field="ma20", op="cross_above", compare_to_field="ma50")
        prev_row = pd.Series({"ma20": 99.0, "ma50": 100.0})
        row = pd.Series({"ma20": 101.0, "ma50": 100.0})
        self.assertTrue(evaluate_condition(row, condition, prev_row))

    def test_cross_above_field_vs_field_does_not_fire_without_a_real_crossing(self) -> None:
        condition = Condition(field="ma20", op="cross_above", compare_to_field="ma50")
        # ma20 already above ma50 on both rows -- no crossing occurred
        prev_row = pd.Series({"ma20": 101.0, "ma50": 100.0})
        row = pd.Series({"ma20": 102.0, "ma50": 100.0})
        self.assertFalse(evaluate_condition(row, condition, prev_row))

    def test_cross_below_field_vs_field(self) -> None:
        condition = Condition(field="ma20", op="cross_below", compare_to_field="ma50")
        prev_row = pd.Series({"ma20": 101.0, "ma50": 100.0})
        row = pd.Series({"ma20": 99.0, "ma50": 100.0})
        self.assertTrue(evaluate_condition(row, condition, prev_row))

    def test_end_to_end_ma20_crosses_above_ma50_on_a_real_indicator_frame(self) -> None:
        # 60 flat candles (ma20 == ma50 == 100) then a sustained uptrend -- the faster
        # ma20 must cross above the slower ma50 exactly once, at a known index (verified
        # empirically before writing this test: index 60).
        closes = [100.0] * 60
        for _ in range(40):
            closes.append(closes[-1] * 1.01)
        frame = compute_indicator_frame(_candles(len(closes), closes=closes))
        rule = parse_structured_rule({"conditions": [{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}]})

        timestamps = find_trigger_timestamps(frame, rule)

        self.assertEqual(len(timestamps), 1)
        self.assertEqual(timestamps[0], int(frame["close_time"].iloc[60]))


class RuleFiresAtTest(unittest.TestCase):
    def test_gt_condition_fires_correctly(self) -> None:
        frame = compute_indicator_frame(_candles(5, closes=[10.0, 20.0, 5.0, 30.0, 1.0]))
        rule = parse_structured_rule({"conditions": [{"field": "close", "op": "gt", "value": 15.0}]})
        fires = [rule_fires_at(frame, i, rule) for i in range(len(frame))]
        self.assertEqual(fires, [False, True, False, True, False])

    def test_cross_above_requires_prior_row_below_threshold(self) -> None:
        # close sequence crosses 10 upward exactly once (index 2: 9 -> 11)
        frame = compute_indicator_frame(_candles(4, closes=[8.0, 9.0, 11.0, 12.0]))
        rule = parse_structured_rule({"conditions": [{"field": "close", "op": "cross_above", "value": 10.0}]})
        timestamps = find_trigger_timestamps(frame, rule)
        self.assertEqual(len(timestamps), 1)
        self.assertEqual(timestamps[0], int(frame["close_time"].iloc[2]))

    def test_cross_above_at_first_row_never_fires(self) -> None:
        # no prior row to compare against -- must not fire, must not raise
        frame = compute_indicator_frame(_candles(3, closes=[20.0, 21.0, 22.0]))
        rule = parse_structured_rule({"conditions": [{"field": "close", "op": "cross_above", "value": 10.0}]})
        self.assertFalse(rule_fires_at(frame, 0, rule))

    def test_warmup_rows_never_fire_and_never_raise(self) -> None:
        frame = compute_indicator_frame(_candles(10))
        rule = parse_structured_rule({"conditions": [{"field": "ma200", "op": "gt", "value": 0.0}]})
        # ma200 needs 200 rows -- every row here is warmup (NaN) and must count as "no fire"
        self.assertEqual(count_triggers(frame, rule), 0)

    def test_and_semantics_require_every_condition(self) -> None:
        frame = compute_indicator_frame(_candles(5, closes=[10.0, 20.0, 20.0, 30.0, 5.0]))
        rule = parse_structured_rule(
            {
                "conditions": [
                    {"field": "close", "op": "gt", "value": 15.0},
                    {"field": "close", "op": "lt", "value": 25.0},
                ]
            }
        )
        # only indices 1 and 2 satisfy BOTH gt 15 and lt 25
        fires = [rule_fires_at(frame, i, rule) for i in range(len(frame))]
        self.assertEqual(fires, [False, True, True, False, False])


if __name__ == "__main__":
    unittest.main()
