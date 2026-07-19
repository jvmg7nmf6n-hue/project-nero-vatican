from __future__ import annotations

import unittest
from dataclasses import dataclass

from tools.rmr_variant_research_stage2_diagnosis import exit_reason_profile, implied_short_leg_cost


@dataclass
class _FakeTrade:
    exit_reason: str
    holding_hours: float
    r_multiple: float


class ExitReasonProfileTest(unittest.TestCase):
    def test_empty_trades_returns_zero_profile(self) -> None:
        profile = exit_reason_profile([])
        self.assertEqual(profile["n"], 0)
        self.assertIsNone(profile["mean_holding_hours"])

    def test_counts_and_holding_hours_computed_correctly(self) -> None:
        trades = [
            _FakeTrade("STOP", 10.0, -1.0),
            _FakeTrade("STOP", 20.0, -1.0),
            _FakeTrade("REGIME_BREAK", 30.0, 0.5),
            _FakeTrade("REVERSION_TARGET", 40.0, 1.0),
        ]
        profile = exit_reason_profile(trades)
        self.assertEqual(profile["n"], 4)
        self.assertEqual(profile["counts"], {"STOP": 2, "REGIME_BREAK": 1, "REVERSION_TARGET": 1})
        self.assertAlmostEqual(profile["mean_holding_hours"], 25.0)
        self.assertAlmostEqual(profile["median_holding_hours"], 25.0)


class ImpliedShortLegCostTest(unittest.TestCase):
    def test_computes_difference_in_total_r_and_count(self) -> None:
        baseline = [_FakeTrade("STOP", 1.0, -1.0), _FakeTrade("STOP", 1.0, 2.0), _FakeTrade("STOP", 1.0, -0.5)]
        long_only = [_FakeTrade("STOP", 1.0, 2.0)]
        cost = implied_short_leg_cost(baseline, long_only)
        self.assertEqual(cost["baseline_n"], 3)
        self.assertEqual(cost["long_only_n"], 1)
        self.assertAlmostEqual(cost["baseline_total_r"], 0.5)
        self.assertAlmostEqual(cost["long_only_total_r"], 2.0)
        self.assertAlmostEqual(cost["implied_short_leg_total_r"], -1.5)
        self.assertEqual(cost["implied_short_leg_n"], 2)


if __name__ == "__main__":
    unittest.main()
