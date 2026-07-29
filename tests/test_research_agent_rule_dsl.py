from __future__ import annotations

import unittest

import pandas as pd

from nero_core.research_agent.rule_dsl import (
    RuleAmbiguousError,
    compute_indicator_frame,
    count_triggers,
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
            parse_structured_rule({"conditions": [{"field": "rsi14", "op": "lt", "value": 30.0}]})

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
