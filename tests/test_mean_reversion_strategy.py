from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    MeanReversionState,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    reset_daily_guard_if_needed,
    rsi,
    size_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T01:00:00Z"),
        "open_time": close_time - 3600000,
        "close_time": close_time,
        "open": 101.0,
        "high": 102.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1000.0,
        "rsi": 30.0,
        "ma20": 105.0,
        "bb_lower": 101.0,
        "ma200": 95.0,
        "atr": 2.0,
    }
    data.update(overrides)
    return pd.Series(data)


class MeanReversionEntryExitTest(unittest.TestCase):
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

    def test_rejects_when_rsi_not_below_threshold(self) -> None:
        evaluation = evaluate_entry(make_candle(rsi=40.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_NOT_BELOW_35", evaluation.reasons)

    def test_rejects_when_close_not_below_lower_band(self) -> None:
        evaluation = evaluate_entry(make_candle(close=101.0, bb_lower=101.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_BELOW_LOWER_BB", evaluation.reasons)

    def test_rejects_when_close_not_above_ma200(self) -> None:
        evaluation = evaluate_entry(make_candle(ma200=150.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", evaluation.reasons)

    def test_rejects_when_target_not_above_entry(self) -> None:
        evaluation = evaluate_entry(make_candle(ma20=99.0), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("TARGET_NOT_ABOVE_ENTRY", evaluation.reasons)

    def test_multiple_rejection_reasons_are_all_reported(self) -> None:
        evaluation = evaluate_entry(make_candle(rsi=80.0, ma200=150.0), self.state)

        self.assertIn("RSI_NOT_BELOW_35", evaluation.reasons)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", evaluation.reasons)

    def test_exit_uses_stop_first_when_stop_and_target_hit_same_candle(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state)
        self.state.open_trade = entry
        self.assertIsNotNone(entry)

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=110.0, low=90.0, close=104.0),
            self.state,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")
        self.assertLess(exit_event.net_pnl, 0.0)
        self.assertIsNone(self.state.open_trade)

    def test_time_exit_after_max_holding_hours(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)

        exit_event = evaluate_exit(
            make_candle(close_time=3600000 + 24 * 3600000, high=103.0, low=98.0, close=101.0),
            self.state,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")

    def test_no_exit_when_no_conditions_met(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)

        exit_event = evaluate_exit(
            make_candle(close_time=3960000, high=101.5, low=99.5, close=100.5),
            self.state,
        )

        self.assertIsNone(exit_event)
        self.assertIsNotNone(self.state.open_trade)

    def test_evaluate_exit_returns_none_when_no_open_trade(self) -> None:
        self.assertIsNone(evaluate_exit(make_candle(), self.state))

    def test_exit_updates_equity_and_daily_r(self) -> None:
        self.state.open_trade = size_entry(make_candle(close_time=3600000), self.state)
        starting_equity = self.state.equity

        exit_event = evaluate_exit(
            make_candle(close_time=3600000 + 24 * 3600000, high=108.0, low=99.0, close=107.0),
            self.state,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(self.state.equity, starting_equity + exit_event.net_pnl)
        self.assertAlmostEqual(self.state.daily_r, exit_event.r_multiple)

    def test_reset_daily_guard_if_needed_resets_on_new_day(self) -> None:
        self.state.daily_r = -2.0
        self.state.daily_guard_day = "2026-07-09"

        reset_daily_guard_if_needed(self.state, pd.Timestamp("2026-07-10T01:00:00Z"))

        self.assertEqual(self.state.daily_r, 0.0)
        self.assertEqual(self.state.daily_guard_day, "2026-07-10")

    def test_reset_daily_guard_if_needed_keeps_value_on_same_day(self) -> None:
        self.state.daily_r = -1.5
        self.state.daily_guard_day = "2026-07-10"

        reset_daily_guard_if_needed(self.state, pd.Timestamp("2026-07-10T05:00:00Z"))

        self.assertEqual(self.state.daily_r, -1.5)


class MeanReversionIndicatorsTest(unittest.TestCase):
    def test_rsi_is_high_for_a_strictly_rising_series(self) -> None:
        close = pd.Series([100.0 + i for i in range(30)])

        values = rsi(close, period=14)

        self.assertGreater(float(values.iloc[-1]), 90.0)

    def test_add_indicators_produces_expected_columns_without_lookahead(self) -> None:
        dates = pd.date_range("2026-01-01", periods=210, freq="1h", tz="UTC")
        close_times = [int(ts.value // 1_000_000) for ts in dates]
        frame = pd.DataFrame(
            {
                "date": dates,
                "open_time": [c - 3600000 for c in close_times],
                "close_time": close_times,
                "open": [100.0] * 210,
                "high": [101.0] * 210,
                "low": [99.0] * 210,
                "close": [100.0 + (i % 5) for i in range(210)],
                "volume": [10.0] * 210,
            }
        )

        enriched = add_indicators(frame)

        self.assertTrue({"ma20", "bb_lower", "ma200", "rsi", "atr"}.issubset(enriched.columns))
        # MA200 needs 200 observations; earlier rows must stay unset (no lookahead/backfill).
        self.assertTrue(enriched["ma200"].iloc[:199].isna().all())
        self.assertFalse(pd.isna(enriched["ma200"].iloc[-1]))


class MeanReversionRegistrationTest(unittest.TestCase):
    def test_register_default_variant_records_original_parameters(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.parameters["rsi_entry_below"], DEFAULT_PARAMETERS.rsi_entry_below)
        self.assertEqual(variant.parameters["daily_loss_guard_r"], DEFAULT_PARAMETERS.daily_loss_guard_r)
        self.assertEqual(variant.parameters["risk_per_trade"], DEFAULT_PARAMETERS.risk_per_trade)

    def test_registering_default_variant_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
