from __future__ import annotations

import unittest

from tools.backtest_donchian_mechanism_validation import mechanism_verdict
from tools.backtest_statistics import RandomBaselineResult


def _baseline(edge_over_random: float) -> RandomBaselineResult:
    return RandomBaselineResult(
        real_expectancy_r=0.3, mean_random_expectancy_r=0.3 - edge_over_random,
        p95_random_expectancy_r=0.5, edge_over_random=edge_over_random,
        target_trade_count=50, realized_mean_trade_count=50.0, n_runs=200,
    )


class MechanismVerdictTest(unittest.TestCase):
    def test_timing_confirmed_when_edge_over_random_clearly_positive(self) -> None:
        row = {"near_breakout_baseline": _baseline(0.25)}
        self.assertEqual(mechanism_verdict(row), "TIMING-CONFIRMED")

    def test_proximity_only_when_edge_over_random_near_zero(self) -> None:
        row = {"near_breakout_baseline": _baseline(0.01)}
        self.assertEqual(mechanism_verdict(row), "PROXIMITY-ONLY")

    def test_proximity_only_when_edge_over_random_negative(self) -> None:
        row = {"near_breakout_baseline": _baseline(-0.1)}
        self.assertEqual(mechanism_verdict(row), "PROXIMITY-ONLY")

    def test_inconclusive_when_no_baseline(self) -> None:
        row = {"near_breakout_baseline": None}
        self.assertEqual(mechanism_verdict(row), "INCONCLUSIVE (no eligible near-breakout pool)")


if __name__ == "__main__":
    unittest.main()
