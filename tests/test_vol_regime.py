from __future__ import annotations

import unittest

import pandas as pd

from nero_core.quant.vol_regime import (
    MULTIPLIER_CEILING,
    MULTIPLIER_FLOOR,
    RECENT_WINDOW,
    position_multiplier,
    volatility_cluster_score,
)

LOOKBACK = 100
OLDER_DIFF_COUNT = LOOKBACK - RECENT_WINDOW  # 80 closes -> 79 pct-change observations
# RECENT_WINDOW=20 closes at the tail -> 20 pct-change observations, none NaN.


def _closes_from_alternating_diffs(older_magnitude: float, recent_magnitude: float, start: float = 100.0) -> pd.Series:
    """Builds exactly LOOKBACK closes: the first (OLDER_DIFF_COUNT - 1) diffs alternate
    +/- older_magnitude, the last RECENT_WINDOW diffs alternate +/- recent_magnitude —
    giving a fully deterministic, exactly-known ratio of recent-to-older mean abs %
    change (recent_magnitude / older_magnitude), with no randomness."""
    diffs = [((-1) ** i) * older_magnitude for i in range(OLDER_DIFF_COUNT - 1)]
    diffs += [((-1) ** i) * recent_magnitude for i in range(RECENT_WINDOW)]
    closes = [start]
    for diff in diffs:
        closes.append(closes[-1] * (1 + diff))
    series = pd.Series(closes)
    assert len(series) == LOOKBACK, len(series)
    return series


class VolatilityClusterScoreTest(unittest.TestCase):
    def test_flat_series_scores_zero(self) -> None:
        closes = _closes_from_alternating_diffs(older_magnitude=0.01, recent_magnitude=0.01)
        self.assertAlmostEqual(volatility_cluster_score(closes, lookback=LOOKBACK), 0.0, places=6)

    def test_recent_spike_10x_clamps_to_one(self) -> None:
        closes = _closes_from_alternating_diffs(older_magnitude=0.001, recent_magnitude=0.01)
        self.assertAlmostEqual(volatility_cluster_score(closes, lookback=LOOKBACK), 1.0, places=6)

    def test_recent_decay_from_high_older_vol_floors_at_zero(self) -> None:
        closes = _closes_from_alternating_diffs(older_magnitude=0.02, recent_magnitude=0.001)
        self.assertAlmostEqual(volatility_cluster_score(closes, lookback=LOOKBACK), 0.0, places=6)

    def test_exact_linear_midpoint(self) -> None:
        # ratio = recent/older = 1.5 -> score = (1.5 - 1.0) / (2.0 - 1.0) = 0.5
        closes = _closes_from_alternating_diffs(older_magnitude=0.01, recent_magnitude=0.015)
        self.assertAlmostEqual(volatility_cluster_score(closes, lookback=LOOKBACK), 0.5, places=3)

    def test_returns_zero_when_insufficient_history(self) -> None:
        closes = pd.Series([100.0 + i for i in range(LOOKBACK - 1)])
        self.assertEqual(volatility_cluster_score(closes, lookback=LOOKBACK), 0.0)

    def test_score_always_within_bounds(self) -> None:
        for older_mag, recent_mag in [(0.001, 0.05), (0.05, 0.001), (0.02, 0.02), (0.0001, 0.0002)]:
            closes = _closes_from_alternating_diffs(older_magnitude=older_mag, recent_magnitude=recent_mag)
            score = volatility_cluster_score(closes, lookback=LOOKBACK)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_rejects_lookback_not_exceeding_recent_window(self) -> None:
        with self.assertRaises(ValueError):
            volatility_cluster_score(pd.Series([1.0] * 50), lookback=RECENT_WINDOW)


class PositionMultiplierTest(unittest.TestCase):
    def test_score_zero_is_baseline_one(self) -> None:
        self.assertAlmostEqual(position_multiplier(0.0), 1.0)

    def test_score_one_is_double(self) -> None:
        self.assertAlmostEqual(position_multiplier(1.0), 2.0)

    def test_score_half_is_linear_midpoint(self) -> None:
        self.assertAlmostEqual(position_multiplier(0.5), 1.5)

    def test_below_baseline_score_reduces_multiplier(self) -> None:
        self.assertAlmostEqual(position_multiplier(-0.5), 0.5)

    def test_clamps_to_floor_and_ceiling_outside_domain(self) -> None:
        self.assertEqual(position_multiplier(-10.0), MULTIPLIER_FLOOR)
        self.assertEqual(position_multiplier(10.0), MULTIPLIER_CEILING)

    def test_monotonic_across_the_documented_domain(self) -> None:
        scores = [i / 10 for i in range(-5, 16)]
        multipliers = [position_multiplier(s) for s in scores]
        self.assertEqual(multipliers, sorted(multipliers))


if __name__ == "__main__":
    unittest.main()
