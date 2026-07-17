from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.breakout_momentum import DEFAULT_PARAMETERS as BM_PARAMETERS
from nero_core.strategies.breakout_momentum import add_indicators as bm_add_indicators
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as TP_PARAMETERS
from nero_core.strategies.trend_pullback import add_indicators as tp_add_indicators
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK
from tools.backtest_statistics import (
    PAIRS_REGIME_CAVEAT,
    bootstrap_mean_r_ci,
    breakout_momentum_regime_mask,
    random_entry_baseline_pairs,
    random_entry_baseline_single_asset,
    trend_pullback_regime_mask,
)


def _breakout_history(n_flat: int = 220, n_breakout: int = 20) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(n_flat):
        close = 100.0 + 0.05 * (i % 7)
        rows.append(_make_candle_row(close_time, close))
        close_time += 3_600_000
    price = rows[-1]["close"]
    for i in range(n_breakout):
        price *= 1.02 if i % 2 == 0 else 0.995
        rows.append(_make_candle_row(close_time, price))
        close_time += 3_600_000
    return pd.DataFrame(rows)


def _evaluable_breakout_momentum() -> pd.DataFrame:
    history = _breakout_history()
    enriched = bm_add_indicators(history, BM_PARAMETERS)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    return enriched.dropna(subset=dropna_columns).reset_index(drop=True)


class BootstrapMeanRCiTest(unittest.TestCase):
    def test_zero_trades_returns_none(self) -> None:
        self.assertIsNone(bootstrap_mean_r_ci([]))

    def test_deterministic_for_a_fixed_seed(self) -> None:
        values = [0.5, -0.3, 1.2, -0.8, 0.4, 0.1, -0.2, 0.9]

        first = bootstrap_mean_r_ci(values, iterations=500, seed=42)
        second = bootstrap_mean_r_ci(values, iterations=500, seed=42)

        self.assertEqual(first, second)

    def test_different_seed_can_change_the_ci_slightly(self) -> None:
        values = [0.5, -0.3, 1.2, -0.8, 0.4, 0.1, -0.2, 0.9]

        a = bootstrap_mean_r_ci(values, iterations=500, seed=1)
        b = bootstrap_mean_r_ci(values, iterations=500, seed=2)

        # Not asserting they differ (could coincide), just that both are valid CIs.
        self.assertLessEqual(a.lower_2_5, a.mean_r)
        self.assertGreaterEqual(b.upper_97_5, b.mean_r)

    def test_all_positive_r_values_gives_a_ci_entirely_above_zero(self) -> None:
        values = [0.5, 0.8, 1.1, 0.6, 0.9, 0.7, 1.0, 0.4]

        ci = bootstrap_mean_r_ci(values, iterations=2000, seed=7)

        self.assertGreater(ci.lower_2_5, 0.0)
        self.assertFalse(ci.crosses_zero)

    def test_noisy_mixed_r_values_can_cross_zero(self) -> None:
        values = [2.0, -2.1, 1.9, -1.8, 0.1, -0.2]

        ci = bootstrap_mean_r_ci(values, iterations=2000, seed=7)

        self.assertTrue(ci.crosses_zero)

    def test_mean_r_matches_simple_average(self) -> None:
        values = [1.0, 2.0, 3.0, -1.0]

        ci = bootstrap_mean_r_ci(values, seed=1)

        self.assertAlmostEqual(ci.mean_r, sum(values) / len(values), places=9)

    def test_sample_size_is_recorded(self) -> None:
        ci = bootstrap_mean_r_ci([1.0, 2.0, 3.0], seed=1)
        self.assertEqual(ci.sample_size, 3)


class RegimeMaskTest(unittest.TestCase):
    def test_breakout_momentum_mask_matches_close_above_ma200(self) -> None:
        frame = pd.DataFrame({"close": [10.0, 20.0, 5.0], "ma200": [15.0, 15.0, 15.0]})
        mask = breakout_momentum_regime_mask(frame)
        self.assertEqual(list(mask), [False, True, False])

    def test_trend_pullback_mask_requires_both_conditions(self) -> None:
        frame = pd.DataFrame(
            {
                "close": [20.0, 20.0, 5.0],
                "ma200": [15.0, 15.0, 15.0],
                "ma50": [16.0, 14.0, 16.0],
            }
        )
        mask = trend_pullback_regime_mask(frame)
        # row0: close>ma200 and ma50>ma200 -> True; row1: ma50<ma200 -> False; row2: close<ma200 -> False
        self.assertEqual(list(mask), [True, False, False])


class RandomEntryBaselineSingleAssetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluable = _evaluable_breakout_momentum()
        self.eligible_mask = breakout_momentum_regime_mask(self.evaluable)

    def test_empty_eligible_pool_returns_none(self) -> None:
        empty_mask = pd.Series([False] * len(self.evaluable))
        result = random_entry_baseline_single_asset(
            self.evaluable, empty_mask, BM_PARAMETERS, bm_size_entry, real_expectancy_r=0.5, target_trade_count=10
        )
        self.assertIsNone(result)

    def test_zero_target_trade_count_returns_none(self) -> None:
        result = random_entry_baseline_single_asset(
            self.evaluable, self.eligible_mask, BM_PARAMETERS, bm_size_entry, real_expectancy_r=0.5, target_trade_count=0
        )
        self.assertIsNone(result)

    def test_deterministic_for_a_fixed_seed(self) -> None:
        first = random_entry_baseline_single_asset(
            self.evaluable, self.eligible_mask, BM_PARAMETERS, bm_size_entry,
            real_expectancy_r=0.5, target_trade_count=5, n_runs=50, seed=99,
        )
        second = random_entry_baseline_single_asset(
            self.evaluable, self.eligible_mask, BM_PARAMETERS, bm_size_entry,
            real_expectancy_r=0.5, target_trade_count=5, n_runs=50, seed=99,
        )
        self.assertEqual(first, second)

    def test_realized_mean_trade_count_is_close_to_target(self) -> None:
        result = random_entry_baseline_single_asset(
            self.evaluable, self.eligible_mask, BM_PARAMETERS, bm_size_entry,
            real_expectancy_r=0.5, target_trade_count=3, n_runs=200, seed=1,
        )
        self.assertIsNotNone(result)
        # Loose tolerance: this is a stochastic sanity check, not an exact-match assertion.
        self.assertLess(abs(result.realized_mean_trade_count - 3), 2.0)

    def test_edge_over_random_matches_real_minus_mean_random(self) -> None:
        result = random_entry_baseline_single_asset(
            self.evaluable, self.eligible_mask, BM_PARAMETERS, bm_size_entry,
            real_expectancy_r=0.42, target_trade_count=4, n_runs=30, seed=5,
        )
        self.assertAlmostEqual(result.edge_over_random, 0.42 - result.mean_random_expectancy_r, places=9)

    def test_trend_pullback_can_also_use_the_generic_baseline(self) -> None:
        # Cross-family sanity check: the generic simulator works for any single-asset
        # strategy sharing the MeanReversionState/evaluate_exit/size_entry_fn contract.
        history = _breakout_history()
        enriched = tp_add_indicators(history, TP_PARAMETERS)
        dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
        evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
        mask = trend_pullback_regime_mask(evaluable)

        result = random_entry_baseline_single_asset(
            evaluable, mask, TP_PARAMETERS, tp_size_entry, real_expectancy_r=0.1, target_trade_count=2, n_runs=20, seed=3
        )
        # May legitimately be None if this fixture never satisfies the uptrend mask.
        if result is not None:
            self.assertEqual(result.n_runs, 20)


class RandomEntryBaselinePairsTest(unittest.TestCase):
    def setUp(self) -> None:
        x_df, y_df = _cointegrated_pair_frames(500)
        aligned = align_pair_candles(x_df, y_df, "BTC", "ETH")
        enriched = pairs_add_indicators(aligned, PAIRS_PARAMETERS, "BTC", "ETH")
        self.evaluable = enriched.dropna(subset=["zscore"]).reset_index(drop=True)

    def test_includes_the_pairs_regime_caveat(self) -> None:
        result = random_entry_baseline_pairs(
            self.evaluable, PAIRS_PARAMETERS, "BTC", "ETH", real_expectancy_r=0.05, target_trade_count=10, n_runs=30, seed=1
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.caveat, PAIRS_REGIME_CAVEAT)

    def test_deterministic_for_a_fixed_seed(self) -> None:
        first = random_entry_baseline_pairs(
            self.evaluable, PAIRS_PARAMETERS, "BTC", "ETH", real_expectancy_r=0.05, target_trade_count=10, n_runs=30, seed=1
        )
        second = random_entry_baseline_pairs(
            self.evaluable, PAIRS_PARAMETERS, "BTC", "ETH", real_expectancy_r=0.05, target_trade_count=10, n_runs=30, seed=1
        )
        self.assertEqual(first, second)

    def test_empty_frame_returns_none(self) -> None:
        empty = self.evaluable.iloc[0:0]
        result = random_entry_baseline_pairs(empty, PAIRS_PARAMETERS, "BTC", "ETH", real_expectancy_r=0.0, target_trade_count=5)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
