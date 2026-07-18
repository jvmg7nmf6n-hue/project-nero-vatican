from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import STRATEGY_ID as BASE_STRATEGY_ID
from nero_core.strategies.trend_pullback_fvg_filtered import (
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
        self.assertEqual(STRATEGY_VERSION, "trend-pullback-v1.3.0-fvg-filtered")

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
    def test_produces_range_and_fvg_columns(self) -> None:
        history = _uptrend_pullback_history()
        enriched = add_indicators(history)
        for column in ("range_low_10", "range_high_10", "fvg_open_bullish_gaps"):
            self.assertIn(column, enriched.columns)


class EvaluateEntryFilterTest(unittest.TestCase):
    """Tests the ADDED filter condition in isolation, via a hand-constructed candle
    satisfying every base TREND_PULLBACK condition — a real backtest fixture isn't
    reliable for this: a monotonic uptrend with a fixed percentage high/low spread
    routinely forms real bullish FVGs on its own (verified while writing this test),
    so "no gap happens to exist" can't be relied on from an end-to-end run."""

    def _base_passing_candle(self, open_bullish_gaps=(), range_low=90.0, range_high=110.0) -> pd.Series:
        row = _make_candle_row(0, 100.0)
        row["ma50"] = 95.0
        row["ma200"] = 90.0
        row["rsi"] = 50.0
        row["atr"] = 2.0
        row["prior_near_ma50"] = True
        row["fvg_open_bullish_gaps"] = open_bullish_gaps
        row["range_low_10"] = range_low
        row["range_high_10"] = range_high
        return pd.Series(row)

    def test_rejects_when_no_open_gap_overlaps_the_recent_range(self) -> None:
        from nero_core.strategies.mean_reversion import MeanReversionState

        state = MeanReversionState(equity=10_000.0)
        candle = self._base_passing_candle(open_bullish_gaps=((120.0, 130.0),), range_low=90.0, range_high=110.0)

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_OPEN_FVG_OVERLAPPING_RECENT_RANGE", evaluation.reasons)

    def test_passes_when_an_open_gap_overlaps_the_recent_range(self) -> None:
        from nero_core.strategies.mean_reversion import MeanReversionState

        state = MeanReversionState(equity=10_000.0)
        candle = self._base_passing_candle(open_bullish_gaps=((95.0, 105.0),), range_low=90.0, range_high=110.0)

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)

    def test_rejects_when_range_not_yet_available(self) -> None:
        from nero_core.strategies.mean_reversion import MeanReversionState

        state = MeanReversionState(equity=10_000.0)
        candle = self._base_passing_candle(range_low=float("nan"), range_high=float("nan"))

        evaluation = evaluate_entry(candle, state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RECENT_RANGE_NOT_YET_AVAILABLE", evaluation.reasons)


class RunBacktestNeverExceedsUnfilteredTest(unittest.TestCase):
    def test_filtered_trade_count_never_exceeds_the_unfiltered_count(self) -> None:
        # An added filter can only narrow the entry set, never widen it — regardless of
        # whether any real FVG happens to overlap in this fixture.
        history = _uptrend_pullback_history()

        base_spec = VARIANT_SPECS["trend_pullback"]
        base_trades, _ = compare_run_backtest(history, base_spec)

        filtered_enriched = add_indicators(history)
        filtered_evaluable = filtered_enriched.dropna(
            subset=["ma50", "ma200", "rsi", "atr", "range_low_10", "range_high_10"]
        ).reset_index(drop=True)
        filtered_trades, _ = run_backtest(filtered_evaluable)

        self.assertLessEqual(len(filtered_trades), len(base_trades))


if __name__ == "__main__":
    unittest.main()
