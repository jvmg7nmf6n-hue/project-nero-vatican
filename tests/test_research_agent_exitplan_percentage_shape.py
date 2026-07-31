"""feature/philosophy-hypotheses-dsl-check: ExitPlan's percentage-based stop/
target shape (stop_pct_of_entry / target_pct_of_entry) -- WISE_MAN_ASYMMETRIC_
HOLD's own blocker (target +1%, stop -3%, no time cap). See rule_dsl.ExitPlan's
own docstring ("PERCENTAGE SHAPE") for why this is a genuine new field rather
than an ATR-multiple approximation.

BACKWARD COMPATIBILITY is the primary concern here, same as
test_research_agent_exitplan_dynamic_exit.py before it: this must not change
behavior for any plan that doesn't use the new fields, and _make_exit_
evaluator's routing decision must stay correct for a percentage-shape plan
too -- proven directly below (assertIs/assertIsNot), not just asserted by
construction.
"""
from __future__ import annotations

import unittest

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.rule_dsl import (
    ExitPlan,
    RuleAmbiguousError,
    compute_indicator_frame,
    parse_exit_plan,
    parse_structured_rule,
)
from nero_core.strategies.mean_reversion import MeanReversionParameters, MeanReversionState, evaluate_exit

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000


def _row(close_time: int, close: float, high: float, low: float, **extra) -> pd.Series:
    data = {"close_time": close_time, "close": close, "high": high, "low": low}
    data.update(extra)
    return pd.Series(data)


class ParseExitPlanPercentageShapeTest(unittest.TestCase):
    def test_both_stop_atr_multiple_and_stop_pct_of_entry_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({"stop_atr_multiple": 2.0, "stop_pct_of_entry": 0.03, "target_r_multiple": 2.0})

    def test_neither_stop_atr_multiple_nor_stop_pct_of_entry_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({"target_r_multiple": 2.0, "max_holding_hours": 48.0})

    def test_non_positive_stop_pct_of_entry_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({"stop_pct_of_entry": 0.0, "target_pct_of_entry": 0.01})

    def test_target_r_multiple_and_target_pct_of_entry_together_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({"stop_pct_of_entry": 0.03, "target_r_multiple": 2.0, "target_pct_of_entry": 0.01})

    def test_dynamic_target_condition_and_target_pct_of_entry_together_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({
                "stop_pct_of_entry": 0.03,
                "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
                "target_pct_of_entry": 0.01,
            })

    def test_all_three_target_shapes_together_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({
                "stop_pct_of_entry": 0.03, "target_r_multiple": 2.0,
                "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
                "target_pct_of_entry": 0.01,
            })

    def test_non_positive_target_pct_of_entry_raises_ambiguous(self) -> None:
        with self.assertRaises(RuleAmbiguousError):
            parse_exit_plan({"stop_pct_of_entry": 0.03, "target_pct_of_entry": -0.01})

    def test_wise_man_asymmetric_hold_shape_parses(self) -> None:
        # target +1%, stop -3%, no time cap -- WISE_MAN_ASYMMETRIC_HOLD's literal exit_rule.
        plan = parse_exit_plan({"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01})
        self.assertEqual(plan.stop_pct_of_entry, 0.03)
        self.assertEqual(plan.target_pct_of_entry, 0.01)
        self.assertIsNone(plan.stop_atr_multiple)
        self.assertIsNone(plan.target_r_multiple)
        self.assertIsNone(plan.dynamic_target_condition)
        self.assertIsNone(plan.max_holding_hours)  # omitted -- no time cap, same convention as the ATR shape

    def test_stop_pct_can_combine_with_target_r_multiple(self) -> None:
        # A plan MAY mix bases (percentage stop, R-multiple target) -- see ExitPlan's own
        # docstring: the two computations are independent, not coupled by definition.
        plan = parse_exit_plan({"stop_pct_of_entry": 0.02, "target_r_multiple": 3.0, "max_holding_hours": 24.0})
        self.assertEqual(plan.stop_pct_of_entry, 0.02)
        self.assertEqual(plan.target_r_multiple, 3.0)

    def test_original_atr_shape_still_parses_unchanged(self) -> None:
        # Regression: the pre-existing fixed-three-number shape must still parse
        # identically after this addition.
        plan = parse_exit_plan({"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 48.0})
        self.assertEqual(plan.stop_atr_multiple, 1.5)
        self.assertIsNone(plan.stop_pct_of_entry)
        self.assertEqual(plan.target_r_multiple, 2.0)
        self.assertIsNone(plan.target_pct_of_entry)


class MakeExitEvaluatorBackwardCompatibilityTest(unittest.TestCase):
    """Mirrors test_research_agent_exitplan_dynamic_exit.py's own identity-check
    convention for the dynamic-target shape -- proving the SAME thing here for
    the percentage shape: _make_exit_evaluator's routing decision depends only
    on dynamic_target_condition/regime_break_condition/max_holding_hours, never
    on which stop/target BASIS a plan uses."""

    def test_old_atr_shape_plan_returns_evaluate_exit_itself(self) -> None:
        # Regression -- must still hold after adding the percentage fields.
        plan = parse_exit_plan({"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0})
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIs(evaluator, evaluate_exit)

    def test_percentage_shape_plan_with_a_real_time_cap_also_returns_evaluate_exit_itself(self) -> None:
        # The new proof: a percentage-shape plan is exactly as eligible for evaluate_exit
        # ITSELF as the ATR shape is, as long as it doesn't use dynamic-target/regime-break
        # and does carry a real max_holding_hours -- evaluate_exit only reads the already-
        # computed stop_loss/target PRICE LEVELS, never how they were derived.
        plan = parse_exit_plan({"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01, "max_holding_hours": 48.0})
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIs(evaluator, evaluate_exit)

    def test_wise_man_shape_no_time_cap_does_not_use_evaluate_exit_directly(self) -> None:
        # WISE_MAN_ASYMMETRIC_HOLD's actual shape: no max_holding_hours -- evaluate_exit's
        # own TIME check would crash comparing hours_held against None (same reasoning as
        # test_no_time_cap_plan_does_not_use_evaluate_exit_directly in the dynamic-exit
        # suite), so this must route to the extended evaluator regardless of stop/target basis.
        plan = parse_exit_plan({"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01})
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIsNot(evaluator, evaluate_exit)

    def test_dynamic_target_shape_still_does_not_use_evaluate_exit_directly(self) -> None:
        # Regression -- must still hold after adding the percentage fields.
        plan = parse_exit_plan({
            "stop_atr_multiple": 2.0,
            "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
            "max_holding_hours": 24.0,
        })
        evaluator = auto_tester._make_exit_evaluator(plan)
        self.assertIsNot(evaluator, evaluate_exit)


class SizeEntryPercentageShapeTest(unittest.TestCase):
    """Hand-built rows, matching test_research_agent_exitplan_dynamic_exit.py's own
    RegimeBreakConsecutiveBarsTest convention for isolated, exact-value testing."""

    PARAMS = MeanReversionParameters(slippage_bps=0.0, fee_bps=0.0)

    def test_stop_and_target_are_fixed_fractions_of_entry_price(self) -> None:
        exit_plan = ExitPlan(stop_pct_of_entry=0.03, target_pct_of_entry=0.01)
        state = MeanReversionState(equity=10_000.0)
        candle = _row(START_MS, close=100.0, high=100.0, low=100.0, atr14=float("nan"))

        trade = auto_tester._size_entry_for_hypothesis(candle, state, self.PARAMS, exit_plan)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.entry_price, 100.0, places=6)
        self.assertAlmostEqual(trade.stop_loss, 97.0, places=6)  # 100 - 3%
        self.assertAlmostEqual(trade.target, 101.0, places=6)  # 100 + 1%

    def test_percentage_stop_opens_a_trade_even_when_atr14_is_nan(self) -> None:
        # The decoupling proof: unlike stop_atr_multiple, stop_pct_of_entry never reads
        # atr14 for sizing -- a missing/NaN ATR (e.g. still in warmup) must never block
        # a percentage-shape entry the way it correctly blocks an ATR-shape one.
        exit_plan = ExitPlan(stop_pct_of_entry=0.03, target_pct_of_entry=0.01)
        state = MeanReversionState(equity=10_000.0)
        candle = _row(START_MS, close=100.0, high=100.0, low=100.0)  # no atr14 key at all

        trade = auto_tester._size_entry_for_hypothesis(candle, state, self.PARAMS, exit_plan)

        self.assertIsNotNone(trade)
        self.assertTrue(pd.isna(trade.entry_atr))  # informational only, honestly NaN, never guessed

    def test_atr_shape_still_requires_atr14_present_and_positive(self) -> None:
        # Regression: the ORIGINAL gate (missing/non-positive ATR blocks an ATR-shape
        # entry) must be unchanged -- this gate is now conditional on which stop field
        # the plan uses, not removed.
        exit_plan = ExitPlan(stop_atr_multiple=1.5, target_r_multiple=2.0)
        state = MeanReversionState(equity=10_000.0)
        candle = _row(START_MS, close=100.0, high=100.0, low=100.0, atr14=float("nan"))

        trade = auto_tester._size_entry_for_hypothesis(candle, state, self.PARAMS, exit_plan)

        self.assertIsNone(trade)


class RunBacktestPercentageShapeTest(unittest.TestCase):
    """Real candle data, real compute_indicator_frame, real run_backtest -- matches
    WISE_MAN_ASYMMETRIC_HOLD's own entry (close < bb_lower AND adx14 < 25) and exit
    (target +1%, stop -3%, no time cap) end to end, isolating each exit path."""

    def _candles_with_a_dip_then_a_small_bounce(self) -> pd.DataFrame:
        rows = []
        close = 100.0
        # Warmup: 30 flat-ish, low-ADX candles so bb_lower/adx14 are populated (period 20/14)
        # and adx14 stays comfortably below the 25 entry threshold.
        for i in range(30):
            close = 100.0 + 0.05 * ((i % 3) - 1)
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.2, "low": close - 0.2, "volume": 1.0})
        # A dip below bb_lower (entry trigger), then a bounce comfortably clearing +1% (TARGET).
        dip_index = 30
        close = 96.0
        rows.append({"close_time": START_MS + dip_index * HOUR_MS, "close": close, "high": close + 0.2, "low": close - 0.2, "volume": 1.0})
        for j in range(1, 4):
            close += 0.6
            i = dip_index + j
            rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.2, "low": close - 0.2, "volume": 1.0})
        return pd.DataFrame(rows)

    def test_target_exit_fires_at_entry_plus_one_percent(self) -> None:
        candles = self._candles_with_a_dip_then_a_small_bounce()
        frame = compute_indicator_frame(candles)
        rule = parse_structured_rule({"conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 25.0},
        ]})
        exit_plan = parse_exit_plan({"stop_pct_of_entry": 0.03, "target_pct_of_entry": 0.01})
        params = MeanReversionParameters()

        trades, _state = auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(len(trades), 1, "expected exactly one resolved trade (one dip, one bounce)")
        trade = trades[0]
        self.assertEqual(trade.exit_reason, "TARGET")

    def test_stop_exit_fires_at_entry_minus_three_percent(self) -> None:
        # Isolate the STOP path directly (no ambiguity about which candle triggers entry).
        exit_plan = ExitPlan(stop_pct_of_entry=0.03, target_pct_of_entry=0.01)
        params = MeanReversionParameters(slippage_bps=0.0, fee_bps=0.0)
        state = MeanReversionState(equity=10_000.0)
        entry_candle = _row(START_MS, close=100.0, high=100.0, low=100.0, atr14=float("nan"))
        trade = auto_tester._size_entry_for_hypothesis(entry_candle, state, params, exit_plan)
        state.open_trade = trade

        # low breaches stop_loss=97.0; close hasn't reached target=101.0.
        exit_row = _row(START_MS + HOUR_MS, close=98.0, high=98.5, low=96.5)
        exit_evaluator = auto_tester._make_exit_evaluator(exit_plan)
        event = exit_evaluator(exit_row, state, params)

        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")
        self.assertAlmostEqual(event.exit_price, 97.0, places=6)


if __name__ == "__main__":
    unittest.main()
