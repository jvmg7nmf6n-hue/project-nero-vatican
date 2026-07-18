from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import STRATEGY_ID as BASE_STRATEGY_ID
from nero_core.strategies.trend_pullback_bos_filtered import (
    STRATEGY_VERSION,
    DEFAULT_PARAMETERS,
    add_indicators,
    evaluate_entry,
    register_default_variant,
    run_backtest,
)
from tests.test_council_engine import _make_candle_row
from tools.backtest_compare import VARIANT_SPECS
from tools.backtest_compare import run_backtest as compare_run_backtest


def _uptrend_pullback_history() -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    price = 100.0
    for i in range(220):
        price = 100.0 + 0.5 * i
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    for delta in (-8, -12, -6, 2, 5):
        price += delta
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    for _ in range(15):
        price *= 1.02
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    return pd.DataFrame(rows)


class RegistrationTest(unittest.TestCase):
    def test_version_string_is_new_and_distinct(self) -> None:
        self.assertEqual(STRATEGY_VERSION, "trend-pullback-v1.4.0-bos-filtered")

    def test_register_default_variant_uses_base_strategy_id(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, BASE_STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


class AddIndicatorsTest(unittest.TestCase):
    def test_produces_bos_columns(self) -> None:
        history = _uptrend_pullback_history()
        enriched = add_indicators(history)
        for column in ("bos_up_recent_index", "bos_down_recent_index"):
            self.assertIn(column, enriched.columns)


class EvaluateEntryFilterTest(unittest.TestCase):
    def _base_passing_candle(self, index: int, bos_up_recent_index) -> pd.Series:
        row = _make_candle_row(index * 43_200_000, 100.0)
        row["ma50"] = 95.0
        row["ma200"] = 90.0
        row["rsi"] = 50.0
        row["atr"] = 2.0
        row["prior_near_ma50"] = True
        row["bos_up_recent_index"] = bos_up_recent_index
        return pd.Series(row, name=index)

    def test_rejects_when_no_bos_up_has_ever_happened(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._base_passing_candle(50, bos_up_recent_index=float("nan"))

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_BOS_UP_YET", evaluation.reasons)

    def test_rejects_when_the_last_bos_up_is_too_stale(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        # current index 50, last BOS-up at index 25 -> 25 candles ago, > 20 lookback.
        candle = self._base_passing_candle(50, bos_up_recent_index=25)

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("BOS_UP_TOO_STALE", evaluation.reasons)

    def test_passes_when_a_bos_up_happened_within_the_lookback(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        # current index 50, last BOS-up at index 35 -> 15 candles ago, within 20.
        candle = self._base_passing_candle(50, bos_up_recent_index=35)

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)

    def test_passes_at_exactly_the_lookback_boundary(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._base_passing_candle(50, bos_up_recent_index=30)  # exactly 20 candles ago

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)


class RunBacktestNeverExceedsUnfilteredTest(unittest.TestCase):
    def test_filtered_trade_count_never_exceeds_the_unfiltered_count(self) -> None:
        history = _uptrend_pullback_history()

        base_spec = VARIANT_SPECS["trend_pullback"]
        base_trades, _ = compare_run_backtest(history, base_spec)

        filtered_enriched = add_indicators(history)
        filtered_evaluable = filtered_enriched.dropna(subset=["ma50", "ma200", "rsi", "atr"]).reset_index(drop=True)
        filtered_trades, _ = run_backtest(filtered_evaluable)

        self.assertLessEqual(len(filtered_trades), len(base_trades))


if __name__ == "__main__":
    unittest.main()
