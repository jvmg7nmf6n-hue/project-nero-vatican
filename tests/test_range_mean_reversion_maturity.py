from __future__ import annotations

import unittest
from dataclasses import replace

import pandas as pd

from nero_core.strategies.range_mean_reversion_maturity import (
    DEFAULT_MATURITY_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    RangeMaturityState,
    evaluate_maturity_entry,
    register_default_variant,
    run_backtest,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _make_candle(close_time=0, close=100.0, high=None, low=None, sma20=100.0,
                  bb_lower=95.0, bb_upper=105.0, adx=20.0, atr_value=2.0) -> pd.Series:
    high = high if high is not None else close + 1
    low = low if low is not None else close - 1
    return pd.Series({
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time, "close": close, "high": high, "low": low,
        "sma20": sma20, "bb_lower": bb_lower, "bb_upper": bb_upper, "adx": adx, "atr": atr_value,
    })


def _ohlc_row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "close_time": close_time,
        "open": close, "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5, "close": close, "volume": 100.0,
    }


class MaturityGateTest(unittest.TestCase):
    def test_rejects_entry_when_streak_below_bar(self) -> None:
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=20)
        state = RangeMaturityState(equity=10000.0, consecutive_ranging_bars=5)
        candle = _make_candle(close=90.0, adx=20.0)  # would pass v1.0.0's own gate
        evaluation = evaluate_maturity_entry(candle, state, params)
        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_MATURE_ENOUGH", evaluation.reasons)

    def test_allows_entry_when_streak_meets_bar(self) -> None:
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=20)
        state = RangeMaturityState(equity=10000.0, consecutive_ranging_bars=20)
        candle = _make_candle(close=90.0, adx=20.0)
        evaluation = evaluate_maturity_entry(candle, state, params)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_still_rejects_for_v1_reasons_even_when_mature(self) -> None:
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=20)
        state = RangeMaturityState(equity=10000.0, consecutive_ranging_bars=25)
        candle = _make_candle(close=90.0, adx=30.0)  # trending -> v1.0.0's own NOT_RANGING
        evaluation = evaluate_maturity_entry(candle, state, params)
        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_RANGING", evaluation.reasons)
        self.assertNotIn("NOT_MATURE_ENOUGH", evaluation.reasons)  # streak bar was actually met


class RunBacktestMaturityCounterTest(unittest.TestCase):
    def test_no_entry_before_streak_matures(self) -> None:
        # 5 ranging candles then a band-breach candle -- far short of a 20-candle
        # maturity bar, so no trade should open despite a valid band breach.
        rows = [_ohlc_row(i * 3_600_000, 100.0, high=100.5, low=99.5) for i in range(5)]
        rows.append(_ohlc_row(5 * 3_600_000, 80.0, high=81.0, low=79.0))
        frame = pd.DataFrame(rows)
        frame["sma20"] = 100.0
        frame["bb_lower"] = 95.0
        frame["bb_upper"] = 105.0
        frame["adx"] = 20.0
        frame["atr"] = 2.0
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=20)
        trades, state = run_backtest(frame, params)
        self.assertEqual(trades, [])
        self.assertIsNone(state.open_trade)

    def test_entry_fires_once_streak_matures(self) -> None:
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=3)
        rows = [_ohlc_row(i * 3_600_000, 100.0, high=100.5, low=99.5) for i in range(3)]
        rows.append(_ohlc_row(3 * 3_600_000, 80.0, high=81.0, low=79.0))
        frame = pd.DataFrame(rows)
        frame["sma20"] = 100.0
        frame["bb_lower"] = 95.0
        frame["bb_upper"] = 105.0
        frame["adx"] = 20.0
        frame["atr"] = 2.0
        trades, state = run_backtest(frame, params)
        self.assertIsNotNone(state.open_trade)
        self.assertEqual(state.open_trade.direction, "LONG")

    def test_streak_resets_after_a_trending_candle(self) -> None:
        params = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=3)
        rows = [_ohlc_row(i * 3_600_000, 100.0, high=100.5, low=99.5) for i in range(3)]
        rows.append(_ohlc_row(3 * 3_600_000, 100.0, high=100.5, low=99.5))  # trending candle
        rows.append(_ohlc_row(4 * 3_600_000, 80.0, high=81.0, low=79.0))  # only 1 ranging candle since
        frame = pd.DataFrame(rows)
        frame["sma20"] = 100.0
        frame["bb_lower"] = 95.0
        frame["bb_upper"] = 105.0
        frame["adx"] = [20.0, 20.0, 20.0, 30.0, 20.0]
        frame["atr"] = 2.0
        trades, state = run_backtest(frame, params)
        self.assertIsNone(state.open_trade)  # streak reset by the trending candle, too short again


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.5.0-range-maturity")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_default_maturity_bar_is_20(self) -> None:
        self.assertEqual(DEFAULT_MATURITY_PARAMETERS.mature_range_min_candles, 20)


if __name__ == "__main__":
    unittest.main()
