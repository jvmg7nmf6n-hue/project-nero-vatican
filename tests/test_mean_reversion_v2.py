from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import STRATEGY_ID as V1_STRATEGY_ID
from nero_core.strategies.mean_reversion import STRATEGY_VERSION as V1_STRATEGY_VERSION
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.mean_reversion import evaluate_entry as evaluate_entry_v1
from nero_core.strategies.mean_reversion import register_default_variant as register_v1
from nero_core.strategies.mean_reversion_v2 import (
    DEFAULT_V2_PARAMETERS,
    STRATEGY_VERSION as V2_STRATEGY_VERSION,
    evaluate_entry_v2,
    register_default_variant as register_v2,
)
from nero_core.strategies.registry import StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


def _calm_price_history(rows: int = 150) -> pd.DataFrame:
    """Small, STATIONARY alternating returns (+0.3%/-0.25% each candle). A constant-
    amplitude noise process keeps the EWMA (recency-weighted) conditional vol and the
    30D/90D realized vol baseline converging to nearly the same steady state, so the
    ratio-based regime classifier lands on VOL_NORMAL rather than spiking on a
    near-zero baseline (which a perfectly smooth/linear series would otherwise cause)."""
    closes: list[float] = []
    price = 100.0
    for i in range(rows):
        delta = 0.003 if i % 2 == 0 else -0.0025
        price *= 1 + delta
        closes.append(price)
    return pd.DataFrame({"close": closes})


def _volatile_price_history(rows: int = 150) -> pd.DataFrame:
    """Calm history followed by a burst of large alternating swings in the most recent
    candles, so recency-weighted EWMA conditional vol spikes far above the 90D baseline."""
    calm = _calm_price_history(rows - 20)
    closes = calm["close"].tolist()
    price = closes[-1]
    swings = [0.14, -0.13, 0.15, -0.14, 0.16, -0.15, 0.14, -0.13, 0.15, -0.14] * 2
    for swing in swings:
        price *= 1 + swing
        closes.append(price)
    return pd.DataFrame({"close": closes})


def _bullish_daily_history(rows: int = 90) -> pd.DataFrame:
    closes = [100.0 + 1.0 * i for i in range(rows)]
    return pd.DataFrame({"close": closes})


def _bearish_daily_history(rows: int = 90) -> pd.DataFrame:
    closes = [200.0 - 1.2 * i for i in range(rows)]
    return pd.DataFrame({"close": closes})


class MeanReversionV2VolatilityFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)
        self.candle = make_candle()  # passes all v1 entry conditions
        self.daily_history = _bullish_daily_history()

    def test_v1_confirms_this_candle_passes_baseline_conditions(self) -> None:
        base = evaluate_entry_v1(self.candle, self.state)
        self.assertTrue(base.passed)

    def test_calm_volatility_regime_allows_entry(self) -> None:
        evaluation = evaluate_entry_v2(self.candle, _calm_price_history(), self.daily_history, self.state)

        self.assertTrue(evaluation.passed)

    def test_stressed_volatility_regime_blocks_entry(self) -> None:
        evaluation = evaluate_entry_v2(self.candle, _volatile_price_history(), self.daily_history, self.state)

        self.assertFalse(evaluation.passed)
        self.assertTrue(any(reason.startswith("REGIME_FILTER_UNFAVORABLE_VOLATILITY") for reason in evaluation.reasons))

    def test_insufficient_volatility_data_blocks_with_clear_reason(self) -> None:
        short_history = pd.DataFrame({"close": [100.0, 101.0, 102.0]})

        evaluation = evaluate_entry_v2(self.candle, short_history, self.daily_history, self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("REGIME_FILTER_INSUFFICIENT_VOLATILITY_DATA", evaluation.reasons)


class MeanReversionV2HigherTimeframeFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)
        self.candle = make_candle()
        self.calm_history = _calm_price_history()

    def test_bullish_daily_trend_allows_entry(self) -> None:
        evaluation = evaluate_entry_v2(self.candle, self.calm_history, _bullish_daily_history(), self.state)

        self.assertTrue(evaluation.passed)

    def test_bearish_daily_trend_blocks_entry(self) -> None:
        evaluation = evaluate_entry_v2(self.candle, self.calm_history, _bearish_daily_history(), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("HIGHER_TIMEFRAME_TREND_CONTRADICTS", evaluation.reasons)

    def test_missing_daily_history_blocks_with_clear_reason(self) -> None:
        evaluation = evaluate_entry_v2(self.candle, self.calm_history, pd.DataFrame(), self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("HIGHER_TIMEFRAME_INSUFFICIENT_DATA", evaluation.reasons)

    def test_short_daily_history_blocks_with_clear_reason(self) -> None:
        short_daily = pd.DataFrame({"close": [100.0, 101.0, 99.0]})

        evaluation = evaluate_entry_v2(self.candle, self.calm_history, short_daily, self.state)

        self.assertFalse(evaluation.passed)
        self.assertIn("HIGHER_TIMEFRAME_INSUFFICIENT_DATA", evaluation.reasons)


class MeanReversionV2BaseRuleInheritanceTest(unittest.TestCase):
    def test_v1_rejection_reasons_still_surface_through_v2(self) -> None:
        state = MeanReversionState(equity=10000.0)
        bad_candle = make_candle(rsi=80.0)  # fails v1's RSI condition

        evaluation = evaluate_entry_v2(bad_candle, _calm_price_history(), _bullish_daily_history(), state)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_NOT_BELOW_35", evaluation.reasons)

    def test_all_filters_favorable_passes_end_to_end(self) -> None:
        state = MeanReversionState(equity=10000.0)

        evaluation = evaluate_entry_v2(make_candle(), _calm_price_history(), _bullish_daily_history(), state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())


class MeanReversionV2RegistrationTest(unittest.TestCase):
    def test_v1_and_v2_register_as_separate_versions_of_the_same_strategy(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        v2_variant = register_v2(registry)

        self.assertEqual(v1_variant.strategy_id, V1_STRATEGY_ID)
        self.assertEqual(v1_variant.version, V1_STRATEGY_VERSION)
        self.assertEqual(v2_variant.strategy_id, V1_STRATEGY_ID)  # same strategy_id as v1
        self.assertEqual(v2_variant.version, V2_STRATEGY_VERSION)
        self.assertNotEqual(v1_variant.version, v2_variant.version)

        versions = registry.list_versions("MEAN_REVERSION")
        self.assertEqual({v.version for v in versions}, {V1_STRATEGY_VERSION, V2_STRATEGY_VERSION})

    def test_v2_parameters_include_all_v1_fields_plus_filter_thresholds(self) -> None:
        registry = StrategyRegistry()
        variant = register_v2(registry)

        # core v1 fields carried through unchanged
        self.assertEqual(variant.parameters["rsi_entry_below"], 35.0)
        self.assertEqual(variant.parameters["atr_stop_multiple"], 1.5)
        # new v2-only fields present
        self.assertIn("favorable_volatility_regimes", variant.parameters)
        self.assertIn("higher_timeframe_bear_short_threshold", variant.parameters)


if __name__ == "__main__":
    unittest.main()
