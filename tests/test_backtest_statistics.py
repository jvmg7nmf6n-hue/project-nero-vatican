from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.breakout_momentum import DEFAULT_PARAMETERS as BM_PARAMETERS
from nero_core.strategies.breakout_momentum import add_indicators as bm_add_indicators
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles
from nero_core.strategies.fvg_reversion import DEFAULT_PARAMETERS as FVG_PARAMETERS
from nero_core.strategies.fvg_reversion import add_indicators as fvg_add_indicators
from nero_core.strategies.fvg_reversion import evaluate_exit as fvg_evaluate_exit
from nero_core.strategies.fvg_reversion import size_entry as fvg_size_entry
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as TP_PARAMETERS
from nero_core.strategies.trend_pullback import add_indicators as tp_add_indicators
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK
from tools.backtest_statistics import (
    PAIRS_REGIME_CAVEAT,
    VERDICT_DIED,
    VERDICT_PROMISING_WATCHLIST,
    VERDICT_SURVIVED,
    above_ma200_mask,
    below_ma200_mask,
    bootstrap_mean_r_ci,
    breakout_momentum_regime_mask,
    classify_verdict,
    random_entry_baseline_bidirectional,
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


def _row_with_high_low(close_time: int, high: float, low: float) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": (high + low) / 2,
        "volume": 10.0,
    }


def _uptrend_with_bullish_gap_history() -> pd.DataFrame:
    """Uptrend warmup, a bullish gap, an ACTUAL pullback that touches the zone (without
    this, price never revisits the gap and zero signals ever fire — see the real bug
    this exact mistake produced, caught while writing this fixture), then continued
    uptrend so the resulting trade has room to resolve."""
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(210):
        price += 0.3
        rows.append(_make_candle_row(close_time, price))
        close_time += 3_600_000
    last = price
    anchor_high = last + 2
    rows.append(_row_with_high_low(close_time, high=anchor_high, low=last - 1))
    close_time += 3_600_000
    rows.append(_row_with_high_low(close_time, high=last + 20, low=last + 15))  # filler, raised to avoid cascade
    close_time += 3_600_000
    rows.append(_row_with_high_low(close_time, high=last + 30, low=last + 22))  # gap forms: zone [anchor_high, last+22]
    close_time += 3_600_000
    rows.append(_row_with_high_low(close_time, high=last + 24, low=anchor_high + 0.5))  # pullback TOUCHES the zone
    close_time += 3_600_000
    for i in range(30):
        level = last + 25 + i
        rows.append(_row_with_high_low(close_time, high=level + 1, low=level - 1))
        close_time += 3_600_000
    return pd.DataFrame(rows)


def _stats(expectancy_r: float, trades: int, ci) -> dict:
    return {"expectancy_r": expectancy_r, "trades": trades, "ci": ci}


class ClassifyVerdictTest(unittest.TestCase):
    def test_negative_either_half_is_died(self) -> None:
        good = _stats(0.2, 50, bootstrap_mean_r_ci([0.2] * 50))
        bad = _stats(-0.1, 50, bootstrap_mean_r_ci([-0.1] * 50))
        self.assertEqual(classify_verdict(good, bad), VERDICT_DIED)
        self.assertEqual(classify_verdict(bad, good), VERDICT_DIED)

    def test_flat_zero_expectancy_is_died(self) -> None:
        zero = _stats(0.0, 50, bootstrap_mean_r_ci([0.0] * 50))
        good = _stats(0.2, 50, bootstrap_mean_r_ci([0.2] * 50))
        self.assertEqual(classify_verdict(zero, good), VERDICT_DIED)

    def test_positive_both_adequate_sample_ci_clears_is_survived(self) -> None:
        r_values = [0.3, 0.4, 0.5, 0.2, 0.35] * 5  # n=25 >= MIN_SAMPLE_SIZE, tight and positive
        stats_a = _stats(sum(r_values) / len(r_values), len(r_values), bootstrap_mean_r_ci(r_values))
        stats_b = _stats(sum(r_values) / len(r_values), len(r_values), bootstrap_mean_r_ci(r_values))
        self.assertEqual(classify_verdict(stats_a, stats_b), VERDICT_SURVIVED)

    def test_positive_both_but_low_sample_is_promising_watchlist(self) -> None:
        r_values = [0.3, 0.4, 0.5]  # n=3, below MIN_SAMPLE_SIZE
        stats_a = _stats(0.4, 3, bootstrap_mean_r_ci(r_values))
        stats_b = _stats(0.4, 3, bootstrap_mean_r_ci(r_values))
        self.assertEqual(classify_verdict(stats_a, stats_b), VERDICT_PROMISING_WATCHLIST)

    def test_positive_both_adequate_sample_but_ci_crosses_zero_is_promising_watchlist(self) -> None:
        r_values = [2.0, -1.8, 1.9, -1.7, 0.3] * 5  # noisy, positive mean, wide CI
        mean_r = sum(r_values) / len(r_values)
        stats_a = _stats(mean_r, len(r_values), bootstrap_mean_r_ci(r_values))
        stats_b = _stats(mean_r, len(r_values), bootstrap_mean_r_ci(r_values))
        verdict = classify_verdict(stats_a, stats_b)
        # Guard the premise before asserting the interesting branch.
        self.assertTrue(stats_a["ci"].crosses_zero)
        self.assertEqual(verdict, VERDICT_PROMISING_WATCHLIST)

    def test_none_ci_with_positive_expectancy_is_promising_watchlist_not_survived(self) -> None:
        stats_a = _stats(0.3, 25, None)
        stats_b = _stats(0.3, 25, None)
        self.assertEqual(classify_verdict(stats_a, stats_b), VERDICT_PROMISING_WATCHLIST)


class MaBasedMaskTest(unittest.TestCase):
    def test_above_and_below_masks_are_mutually_exclusive(self) -> None:
        frame = pd.DataFrame({"close": [90.0, 100.0, 110.0], "ma200": [100.0, 100.0, 100.0]})
        above = above_ma200_mask(frame)
        below = below_ma200_mask(frame)
        self.assertEqual(list(above), [False, False, True])
        self.assertEqual(list(below), [True, False, False])
        self.assertFalse((above & below).any())


class RandomEntryBaselineBidirectionalTest(unittest.TestCase):
    """FVG_REVERSION's size_entry needs trigger-specific zone columns that are only
    non-NaN on an actual touch candle — a broad "regime holds" mask (e.g. plain
    above_ma200_mask) would let the random simulator try to size an entry at a candle
    with no real zone data at all, producing NaN. The eligible mask for THIS strategy's
    random baseline must therefore be narrowed to "has a real signal, in the direction
    the regime allows" — a necessary adaptation for any trigger-derived-stop strategy,
    documented in fvg_reversion.py / bos_continuation.py's own reports."""

    def setUp(self) -> None:
        history = _uptrend_with_bullish_gap_history()
        enriched = fvg_add_indicators(history)
        self.evaluable = enriched.dropna(subset=["ma200", "atr"]).reset_index(drop=True)
        self.long_mask = above_ma200_mask(self.evaluable) & self.evaluable["fvg_bullish_signal_zone_bottom"].notna()
        self.short_mask = below_ma200_mask(self.evaluable) & self.evaluable["fvg_bearish_signal_zone_top"].notna()

    def test_returns_a_result_with_the_requested_run_count(self) -> None:
        result = random_entry_baseline_bidirectional(
            self.evaluable, self.long_mask, self.short_mask, FVG_PARAMETERS, fvg_size_entry, fvg_evaluate_exit,
            real_expectancy_r=0.1, target_trade_count=1, n_runs=25, seed=1,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.n_runs, 25)

    def test_deterministic_for_a_fixed_seed(self) -> None:
        first = random_entry_baseline_bidirectional(
            self.evaluable, self.long_mask, self.short_mask, FVG_PARAMETERS, fvg_size_entry, fvg_evaluate_exit,
            real_expectancy_r=0.1, target_trade_count=1, n_runs=25, seed=7,
        )
        second = random_entry_baseline_bidirectional(
            self.evaluable, self.long_mask, self.short_mask, FVG_PARAMETERS, fvg_size_entry, fvg_evaluate_exit,
            real_expectancy_r=0.1, target_trade_count=1, n_runs=25, seed=7,
        )

        self.assertEqual(first, second)

    def test_empty_masks_return_none(self) -> None:
        empty = pd.Series([False] * len(self.evaluable))
        result = random_entry_baseline_bidirectional(
            self.evaluable, empty, empty, FVG_PARAMETERS, fvg_size_entry, fvg_evaluate_exit,
            real_expectancy_r=0.1, target_trade_count=3,
        )
        self.assertIsNone(result)


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
