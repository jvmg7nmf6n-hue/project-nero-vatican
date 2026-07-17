from __future__ import annotations

import math
import unittest

import pandas as pd

from nero_core.strategies.breakout_momentum import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    add_indicators,
    evaluate_entry,
    register_default_variant,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.mean_reversion import register_default_variant as register_mean_reversion_v1
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T01:00:00Z"),
        "open_time": close_time - 3600000,
        "close_time": close_time,
        "open": 109.0,
        "high": 111.0,
        "low": 108.0,
        "close": 110.0,
        "volume": 1000.0,
        "rsi": 55.0,
        "ma200": 95.0,
        "atr": 2.0,
        "breakout_high": 105.0,
    }
    data.update(overrides)
    return pd.Series(data)


class BreakoutMomentumEntryExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_conditions_pass_and_size_is_capped_by_notional(self) -> None:
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state)
        trade = size_entry(candle, self.state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())
        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, 10000.0)
        self.assertGreater(trade.risk_dollars, 0.0)

    def test_target_is_fixed_125r_not_ma_based(self) -> None:
        candle = make_candle()

        trade = size_entry(candle, self.state)

        risk_per_unit = trade.entry_price - trade.stop_loss
        expected_target = trade.entry_price + DEFAULT_PARAMETERS.reward_multiple * risk_per_unit
        self.assertAlmostEqual(trade.target, expected_target, places=8)
        self.assertAlmostEqual(risk_per_unit, DEFAULT_PARAMETERS.atr_stop_multiple * candle["atr"], places=8)

    def test_rejects_when_open_trade_already_exists(self) -> None:
        self.state.open_trade = size_entry(make_candle(), MeanReversionState(equity=10000.0))

        evaluation = evaluate_entry(make_candle(), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_rejects_when_daily_loss_guard_is_hit(self) -> None:
        self.state.daily_r = -3.0

        evaluation = evaluate_entry(make_candle(), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)

    def test_rejects_when_close_not_above_breakout_high(self) -> None:
        evaluation = evaluate_entry(make_candle(close=105.0, breakout_high=105.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_BREAKOUT_HIGH", evaluation.reasons)

    def test_rejects_when_breakout_high_is_nan(self) -> None:
        evaluation = evaluate_entry(make_candle(breakout_high=float("nan")), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_BREAKOUT_HIGH", evaluation.reasons)
        self.assertIsNone(evaluation.breakout_high)

    def test_rejects_when_close_not_above_ma200(self) -> None:
        evaluation = evaluate_entry(make_candle(ma200=150.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", evaluation.reasons)

    def test_rejects_when_rsi_below_momentum_threshold(self) -> None:
        evaluation = evaluate_entry(make_candle(rsi=45.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_NOT_MOMENTUM_SUPPORTIVE", evaluation.reasons)

    def test_multiple_rejection_reasons_are_all_reported(self) -> None:
        evaluation = evaluate_entry(make_candle(rsi=30.0, ma200=150.0), self.state)

        self.assertIn("RSI_NOT_MOMENTUM_SUPPORTIVE", evaluation.reasons)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", evaluation.reasons)

    def test_exit_uses_stop_first_when_stop_and_target_hit_same_candle(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state)
        self.state.open_trade = entry
        self.assertIsNotNone(entry)

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=120.0, low=100.0, close=112.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")
        self.assertLess(exit_event.net_pnl, 0.0)
        self.assertIsNone(self.state.open_trade)

    def test_target_exit_hits_fixed_125r(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.target + 1.0, low=109.0, close=entry.target),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TARGET")
        self.assertGreater(exit_event.net_pnl, 0.0)

    def test_time_exit_after_max_holding_hours(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)

        exit_event = evaluate_exit(
            make_candle(close_time=3600000 + 24 * 3600000, high=110.5, low=109.0, close=110.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")

    def test_no_exit_when_no_conditions_met(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)

        exit_event = evaluate_exit(
            make_candle(close_time=3960000, high=110.5, low=109.5, close=110.2),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNone(exit_event)
        self.assertIsNotNone(self.state.open_trade)

    def test_evaluate_exit_returns_none_when_no_open_trade(self) -> None:
        self.assertIsNone(evaluate_exit(make_candle(), self.state, DEFAULT_PARAMETERS))

    def test_exit_updates_equity_and_daily_r(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)
        starting_equity = self.state.equity

        exit_event = evaluate_exit(
            make_candle(close_time=3600000 + 24 * 3600000, high=130.0, low=109.0, close=113.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(self.state.equity, starting_equity + exit_event.net_pnl)
        self.assertAlmostEqual(self.state.daily_r, exit_event.r_multiple)

    def test_reset_daily_guard_if_needed_still_works_with_shared_state(self) -> None:
        self.state.daily_r = -2.0
        self.state.daily_guard_day = "2026-07-09"

        reset_daily_guard_if_needed(self.state, pd.Timestamp("2026-07-10T01:00:00Z"))

        self.assertEqual(self.state.daily_r, 0.0)
        self.assertEqual(self.state.daily_guard_day, "2026-07-10")


class BreakoutMomentumIndicatorsTest(unittest.TestCase):
    def test_breakout_high_excludes_the_current_candles_own_high(self) -> None:
        dates = pd.date_range("2026-01-01", periods=25, freq="1h", tz="UTC")
        close_times = [int(ts.value // 1_000_000) for ts in dates]
        highs = [100.0] * 24 + [1000.0]  # the last candle has a huge high
        frame = pd.DataFrame(
            {
                "date": dates,
                "open_time": [c - 3_600_000 for c in close_times],
                "close_time": close_times,
                "open": [99.0] * 25,
                "high": highs,
                "low": [98.0] * 25,
                "close": [99.5] * 25,
                "volume": [10.0] * 25,
            }
        )

        enriched = add_indicators(frame)

        # Row 24's own high (1000.0) must NOT appear in row 24's own breakout_high.
        self.assertEqual(float(enriched["breakout_high"].iloc[24]), 100.0)

    def test_add_indicators_produces_expected_columns(self) -> None:
        dates = pd.date_range("2026-01-01", periods=210, freq="1h", tz="UTC")
        close_times = [int(ts.value // 1_000_000) for ts in dates]
        frame = pd.DataFrame(
            {
                "date": dates,
                "open_time": [c - 3_600_000 for c in close_times],
                "close_time": close_times,
                "open": [100.0] * 210,
                "high": [101.0] * 210,
                "low": [99.0] * 210,
                "close": [100.0 + (i % 5) for i in range(210)],
                "volume": [10.0] * 210,
            }
        )

        enriched = add_indicators(frame)

        self.assertTrue({"ma200", "rsi", "atr", "breakout_high"}.issubset(enriched.columns))
        self.assertTrue(enriched["ma200"].iloc[:199].isna().all())
        self.assertFalse(pd.isna(enriched["ma200"].iloc[-1]))


class BreakoutMomentumRegistrationTest(unittest.TestCase):
    def test_register_default_variant_records_original_parameters(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.parameters["rsi_momentum_min"], DEFAULT_PARAMETERS.rsi_momentum_min)
        self.assertEqual(variant.parameters["atr_stop_multiple"], DEFAULT_PARAMETERS.atr_stop_multiple)
        self.assertEqual(variant.parameters["reward_multiple"], DEFAULT_PARAMETERS.reward_multiple)
        self.assertEqual(variant.parameters["breakout_lookback"], DEFAULT_PARAMETERS.breakout_lookback)

    def test_registering_default_variant_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_mean_reversion_without_conflict(self) -> None:
        registry = StrategyRegistry()

        mr_variant = register_mean_reversion_v1(registry)
        bm_variant = register_default_variant(registry)

        self.assertNotEqual(mr_variant.strategy_id, bm_variant.strategy_id)
        self.assertEqual(registry.strategy_ids(), ["BREAKOUT_MOMENTUM", "MEAN_REVERSION"])


class RegimeScaledRiskSizingTest(unittest.TestCase):
    """H3 hypothesis: regime_scaled_risk defaults to False and must leave v1.0.0's
    sizing byte-for-byte unchanged; when explicitly enabled, risk_dollars must scale by
    the clamped median/current ATR% ratio."""

    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_default_is_disabled_and_matches_v1_sizing(self) -> None:
        from nero_core.strategies.breakout_momentum import BreakoutMomentumParameters

        self.assertFalse(DEFAULT_PARAMETERS.regime_scaled_risk)
        candle = make_candle(atr=2.0, atr_pct_median100=0.05)  # would scale if enabled
        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * DEFAULT_PARAMETERS.risk_per_trade, places=6)

    def test_enabled_scales_risk_dollars_by_clamped_ratio(self) -> None:
        from nero_core.strategies.breakout_momentum import BreakoutMomentumParameters

        params = BreakoutMomentumParameters(regime_scaled_risk=True)
        # current ATR% = 2.0/110.0 ~= 0.01818; set median to double that -> ratio = 2.0 (clamp ceiling)
        current_atr_pct = 2.0 / 110.0
        candle = make_candle(atr=2.0, atr_pct_median100=current_atr_pct * 2.0)

        trade = size_entry(candle, self.state, params)

        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * params.risk_per_trade * 2.0, places=4)

    def test_enabled_falls_back_to_base_risk_when_median_column_missing(self) -> None:
        from nero_core.strategies.breakout_momentum import BreakoutMomentumParameters

        params = BreakoutMomentumParameters(regime_scaled_risk=True)
        candle = make_candle(atr=2.0)  # no atr_pct_median100 key at all

        trade = size_entry(candle, self.state, params)

        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * params.risk_per_trade, places=6)


if __name__ == "__main__":
    unittest.main()
