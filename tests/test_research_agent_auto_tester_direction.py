"""feature/short-side-support Task 5: dedicated behavioral tests for the
direction-aware code auto_tester.py gained this branch -- _size_entry_for_
hypothesis and _evaluate_exit_for_hypothesis's SHORT branches, short-side P&L
sign correctness, run_backtest's long-checked-first mutual exclusivity,
_measure_frequency_for_hypothesis's bidirectional combining, and _half_stats'
bidirectional random-baseline wiring. Every one of these code paths is new to
this branch and had zero dedicated test coverage before this file."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.frequency_gate import UNMEASURABLE, VIABLE
from nero_core.research_agent.rule_dsl import Condition, ExitPlan, StructuredRule
from nero_core.strategies.mean_reversion import MeanReversionParameters, MeanReversionState

ZERO_COST_PARAMS = MeanReversionParameters(initial_equity=10_000.0, risk_per_trade=0.01, fee_bps=0.0, slippage_bps=0.0)


def _candle(close: float, high: float | None = None, low: float | None = None, close_time: int = 0, **extra) -> pd.Series:
    data = {
        "close": close, "high": high if high is not None else close, "low": low if low is not None else close,
        "close_time": close_time,
    }
    data.update(extra)
    return pd.Series(data)


class SizeEntryDirectionTest(unittest.TestCase):
    def test_long_entry_stop_below_and_target_above_r_multiple_shape(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = MeanReversionState(equity=10_000.0)
        trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), state, ZERO_COST_PARAMS, plan, direction="LONG")
        self.assertEqual(trade.direction, "LONG")
        self.assertEqual(trade.entry_price, 100.0)
        self.assertAlmostEqual(trade.stop_loss, 98.0)
        self.assertAlmostEqual(trade.target, 104.0)  # entry + 2 * risk_per_unit (2.0)

    def test_short_entry_stop_above_and_target_below_r_multiple_shape(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = MeanReversionState(equity=10_000.0)
        trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), state, ZERO_COST_PARAMS, plan, direction="SHORT")
        self.assertEqual(trade.direction, "SHORT")
        self.assertEqual(trade.entry_price, 100.0)
        self.assertAlmostEqual(trade.stop_loss, 102.0)  # mirrored: entry + risk
        self.assertAlmostEqual(trade.target, 96.0)  # mirrored: entry - 2 * risk_per_unit

    def test_short_entry_target_below_percentage_shape(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_pct_of_entry=0.05)
        state = MeanReversionState(equity=10_000.0)
        trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), state, ZERO_COST_PARAMS, plan, direction="SHORT")
        self.assertAlmostEqual(trade.target, 95.0)  # entry * (1 - 0.05)

    def test_default_direction_is_long_every_pre_existing_call_site_is_unaffected(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = MeanReversionState(equity=10_000.0)
        trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), state, ZERO_COST_PARAMS, plan)
        self.assertEqual(trade.direction, "LONG")

    def test_short_entry_uses_sell_slippage_lower_fill_than_long_buy_slippage(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        params = MeanReversionParameters(initial_equity=10_000.0, risk_per_trade=0.01, fee_bps=0.0, slippage_bps=100.0)
        long_trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), MeanReversionState(equity=10_000.0), params, plan, direction="LONG")
        short_trade = auto_tester._size_entry_for_hypothesis(_candle(100.0), MeanReversionState(equity=10_000.0), params, plan, direction="SHORT")
        self.assertGreater(long_trade.entry_price, 100.0)  # "buy" slippage: worse (higher) fill
        self.assertLess(short_trade.entry_price, 100.0)  # "sell" slippage: worse (lower) fill


class EvaluateExitDirectionTest(unittest.TestCase):
    def _open_short(self, entry_price: float, stop_loss: float, target: float) -> MeanReversionState:
        from nero_core.strategies.mean_reversion import OpenTrade

        state = MeanReversionState(equity=10_000.0)
        state.open_trade = OpenTrade(
            entry_price=entry_price, stop_loss=stop_loss, target=target, quantity=1.0, notional=entry_price,
            risk_dollars=abs(stop_loss - entry_price), entry_fee=0.0, open_close_time=0,
            entry_rsi=0.0, entry_ma20=0.0, entry_bb_lower=0.0, entry_ma200=0.0, entry_atr=1.0,
            direction="SHORT",
        )
        return state

    def test_short_stop_hit_on_high_not_low(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = self._open_short(entry_price=100.0, stop_loss=102.0, target=96.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=101.0, high=103.0, low=100.5, close_time=3_600_000), state, ZERO_COST_PARAMS, plan
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")
        self.assertEqual(event.exit_price, 102.0)

    def test_short_target_hit_on_low_not_high_fixed_shape(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = self._open_short(entry_price=100.0, stop_loss=102.0, target=96.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=96.5, high=98.0, low=95.5, close_time=3_600_000), state, ZERO_COST_PARAMS, plan
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TARGET")
        self.assertEqual(event.exit_price, 96.0)

    def test_short_profit_when_price_falls_gross_pnl_sign_is_entry_minus_exit(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = self._open_short(entry_price=100.0, stop_loss=102.0, target=96.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=96.5, high=98.0, low=95.5, close_time=3_600_000), state, ZERO_COST_PARAMS, plan
        )
        self.assertGreater(event.gross_pnl, 0.0)
        self.assertAlmostEqual(event.gross_pnl, (100.0 - 96.0) * 1.0)
        self.assertGreater(event.r_multiple, 0.0)

    def test_short_loss_when_price_rises_gross_pnl_is_negative(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        state = self._open_short(entry_price=100.0, stop_loss=102.0, target=96.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=101.5, high=103.0, low=100.5, close_time=3_600_000), state, ZERO_COST_PARAMS, plan
        )
        self.assertEqual(event.exit_reason, "SL")
        self.assertLess(event.gross_pnl, 0.0)
        self.assertAlmostEqual(event.gross_pnl, (100.0 - 102.0) * 1.0)
        self.assertLess(event.r_multiple, 0.0)

    def test_short_exit_uses_buy_slippage_worse_fill_is_higher_not_lower(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        params = MeanReversionParameters(initial_equity=10_000.0, risk_per_trade=0.01, fee_bps=0.0, slippage_bps=100.0)
        state = self._open_short(entry_price=100.0, stop_loss=102.0, target=96.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=101.0, high=103.0, low=100.5, close_time=3_600_000), state, params, plan
        )
        self.assertGreater(event.exit_price, 102.0)  # "buy" slippage on a SHORT's stop fill

    def test_dynamic_target_condition_is_mirrored_for_a_short_trade(self) -> None:
        # Authored LONG-shaped: "close >= ma20" (target reached moving up).
        # For a SHORT trade this must mirror to "close <= ma20" (target
        # reached moving down) via rule_dsl.mirror_condition, not fire on the
        # unmirrored (wrong-direction) condition.
        plan = ExitPlan(stop_pct_of_entry=0.05, dynamic_target_condition=Condition(field="close", op="gte", compare_to_field="ma20"))
        state = self._open_short(entry_price=100.0, stop_loss=105.0, target=float("nan"))
        # close (90) <= ma20 (95): mirrored condition fires for the SHORT.
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=90.0, high=91.0, low=89.0, close_time=3_600_000, ma20=95.0), state, ZERO_COST_PARAMS, plan
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TARGET")

    def test_dynamic_target_condition_does_not_fire_on_the_unmirrored_direction_for_a_short(self) -> None:
        plan = ExitPlan(stop_pct_of_entry=0.05, dynamic_target_condition=Condition(field="close", op="gte", compare_to_field="ma20"))
        state = self._open_short(entry_price=100.0, stop_loss=105.0, target=float("nan"))
        # close (99) > ma20 (95): the UNMIRRORED (LONG-shaped) condition would
        # fire here, but the mirrored (SHORT-shaped) "close <= ma20" does not.
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=99.0, high=99.5, low=98.5, close_time=3_600_000, ma20=95.0), state, ZERO_COST_PARAMS, plan
        )
        self.assertIsNone(event)

    def test_regime_break_condition_is_never_mirrored_fires_identically_for_short(self) -> None:
        plan = ExitPlan(
            stop_pct_of_entry=0.05, target_r_multiple=10.0,
            regime_break_condition=Condition(field="adx14", op="gte", value=28.0),
            regime_break_consecutive_bars=1,
        )
        state = self._open_short(entry_price=100.0, stop_loss=105.0, target=50.0)
        event = auto_tester._evaluate_exit_for_hypothesis(
            _candle(close=100.0, high=100.5, low=99.5, close_time=3_600_000, adx14=30.0), state, ZERO_COST_PARAMS, plan
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REGIME_BREAK")


class RunBacktestMutualExclusivityTest(unittest.TestCase):
    def test_long_rule_is_checked_before_short_rule_on_the_same_candle(self) -> None:
        # A rule pair deliberately overlapping (both would fire on candle 0)
        # to prove long-checked-first, not that they merely happen to be
        # mutually exclusive by construction (as EXT_ADX_RANGE's own rules are).
        long_rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        short_rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        exit_plan = ExitPlan(stop_pct_of_entry=0.5, target_r_multiple=10.0)
        frame = pd.DataFrame([
            {"close": 100.0, "high": 100.0, "low": 100.0, "close_time": 0},
            {"close": 100.0, "high": 100.0, "low": 100.0, "close_time": 3_600_000},
        ])
        _, state = auto_tester.run_backtest(frame, long_rule, exit_plan, ZERO_COST_PARAMS, short_rule=short_rule)
        self.assertIsNotNone(state.open_trade)
        self.assertEqual(state.open_trade.direction, "LONG")

    def test_short_rule_only_opens_when_long_rule_does_not_fire(self) -> None:
        long_rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=1_000_000.0),))  # never fires
        short_rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))  # always fires
        exit_plan = ExitPlan(stop_pct_of_entry=0.5, target_r_multiple=10.0)
        frame = pd.DataFrame([{"close": 100.0, "high": 100.0, "low": 100.0, "close_time": 0}])
        _, state = auto_tester.run_backtest(frame, long_rule, exit_plan, ZERO_COST_PARAMS, short_rule=short_rule)
        self.assertIsNotNone(state.open_trade)
        self.assertEqual(state.open_trade.direction, "SHORT")

    def test_long_only_call_site_omitting_short_rule_never_opens_a_short(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        exit_plan = ExitPlan(stop_pct_of_entry=0.5, target_r_multiple=10.0)
        frame = pd.DataFrame([{"close": 100.0, "high": 100.0, "low": 100.0, "close_time": 0}])
        _, state = auto_tester.run_backtest(frame, rule, exit_plan, ZERO_COST_PARAMS)
        self.assertEqual(state.open_trade.direction, "LONG")


def _indicator_frame(n: int = 50) -> pd.DataFrame:
    from nero_core.research_agent.rule_dsl import compute_indicator_frame

    raw = pd.DataFrame([{"close": 100.0, "high": 101.0, "low": 99.0, "close_time": i * 3_600_000} for i in range(n)])
    return compute_indicator_frame(raw)


class HalfStatsBidirectionalWiringTest(unittest.TestCase):
    def test_short_rule_none_calls_the_single_asset_baseline_not_bidirectional(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        exit_plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        frame = _indicator_frame()
        from nero_core.strategies.mean_reversion import ExitEvent

        trades = [ExitEvent(exit_reason="TARGET", exit_price=102.0, gross_pnl=2.0, fees=0.0, net_pnl=2.0, r_multiple=1.0, holding_hours=1.0, equity_after=10_002.0)]
        with patch.object(auto_tester, "random_entry_baseline_single_asset", wraps=auto_tester.random_entry_baseline_single_asset) as single_spy, \
             patch.object(auto_tester, "random_entry_baseline_bidirectional", wraps=auto_tester.random_entry_baseline_bidirectional) as bidi_spy:
            auto_tester._half_stats(trades, frame, rule, exit_plan, ZERO_COST_PARAMS)
            single_spy.assert_called_once()
            bidi_spy.assert_not_called()

    def test_short_rule_present_calls_bidirectional_baseline_not_single_asset(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        short_rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        exit_plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        frame = _indicator_frame()
        from nero_core.strategies.mean_reversion import ExitEvent

        trades = [ExitEvent(exit_reason="TARGET", exit_price=102.0, gross_pnl=2.0, fees=0.0, net_pnl=2.0, r_multiple=1.0, holding_hours=1.0, equity_after=10_002.0)]
        with patch.object(auto_tester, "random_entry_baseline_single_asset", wraps=auto_tester.random_entry_baseline_single_asset) as single_spy, \
             patch.object(auto_tester, "random_entry_baseline_bidirectional", wraps=auto_tester.random_entry_baseline_bidirectional) as bidi_spy:
            auto_tester._half_stats(trades, frame, rule, exit_plan, ZERO_COST_PARAMS, short_rule=short_rule)
            bidi_spy.assert_called_once()
            single_spy.assert_not_called()

    def test_zero_trades_calls_neither_baseline_unchanged_pre_existing_behavior(self) -> None:
        rule = StructuredRule(conditions=(Condition(field="close", op="gt", value=0.0),))
        exit_plan = ExitPlan(stop_pct_of_entry=0.02, target_r_multiple=2.0)
        frame = _indicator_frame(n=1)
        with patch.object(auto_tester, "random_entry_baseline_single_asset") as single_spy, \
             patch.object(auto_tester, "random_entry_baseline_bidirectional") as bidi_spy:
            result = auto_tester._half_stats([], frame, rule, exit_plan, ZERO_COST_PARAMS)
            single_spy.assert_not_called()
            bidi_spy.assert_not_called()
            self.assertIsNone(result.random_baseline)


class MeasureFrequencyForHypothesisTest(unittest.TestCase):
    def _candles(self, n: int = 400) -> pd.DataFrame:
        return pd.DataFrame([
            {"close": 100.0 + (i % 5), "high": 101.0, "low": 99.0, "close_time": i * 3_600_000, "adx14": 20.0}
            for i in range(n)
        ])

    def test_long_only_hypothesis_returns_the_unchanged_measure_entry_frequency_result(self) -> None:
        from nero_core.research_agent.frequency_gate import measure_entry_frequency

        rule = {"conditions": [{"field": "adx14", "op": "lt", "value": 25.0}]}
        hypothesis = {"structured_entry_rule": rule}
        candles = self._candles()
        now = pd.Timestamp("2026-08-01", tz="UTC").to_pydatetime()

        expected = measure_entry_frequency(candles, rule, now)
        actual = auto_tester._measure_frequency_for_hypothesis(candles, hypothesis, now)
        self.assertEqual(actual, expected)

    def test_bidirectional_hypothesis_combines_trigger_counts_from_both_sides(self) -> None:
        from nero_core.research_agent.frequency_gate import measure_entry_frequency

        long_rule = {"conditions": [{"field": "close", "op": "lt", "value": 101.0}]}
        short_rule = {"conditions": [{"field": "close", "op": "gt", "value": 103.0}]}
        hypothesis = {"structured_entry_rule": long_rule, "structured_entry_rule_short": short_rule}
        candles = self._candles()
        now = pd.Timestamp("2026-08-01", tz="UTC").to_pydatetime()

        long_alone = measure_entry_frequency(candles, long_rule, now)
        short_alone = measure_entry_frequency(candles, short_rule, now)
        combined = auto_tester._measure_frequency_for_hypothesis(candles, hypothesis, now)
        self.assertEqual(combined.triggers_counted, long_alone.triggers_counted + short_alone.triggers_counted)

    def test_bidirectional_hypothesis_is_unmeasurable_if_either_side_is(self) -> None:
        # A never-firing rule classifies as TOO_SLOW (a real, measured rate of
        # zero), not UNMEASURABLE -- an actually AMBIGUOUS short rule (an
        # unsupported field, caught by rule_dsl.RuleAmbiguousError) is what
        # forces UNMEASURABLE, both alone and combined.
        long_rule = {"conditions": [{"field": "close", "op": "lt", "value": 101.0}]}
        short_rule = {"conditions": [{"field": "not_a_real_field", "op": "gt", "value": 1.0}]}
        hypothesis = {"structured_entry_rule": long_rule, "structured_entry_rule_short": short_rule}
        candles = self._candles()
        now = pd.Timestamp("2026-08-01", tz="UTC").to_pydatetime()

        combined = auto_tester._measure_frequency_for_hypothesis(candles, hypothesis, now)
        self.assertEqual(combined.classification, UNMEASURABLE)


if __name__ == "__main__":
    unittest.main()
