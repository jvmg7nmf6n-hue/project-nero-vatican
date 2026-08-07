"""CC-1 master directive (2026-08-07), "Close the backlog": explicit OUT OF SCOPE
guard. This entire directive (Part A repair-resolution fix, Part B's 3-rung
macro-conditioning ladder) must never touch the evidence bar: the 30/yr
frequency floor, the 70/30 train/test split, MIN_SAMPLE_SIZE, FDR alpha,
random-baseline K, or Trial admission criteria. This test asserts every one
of those real constants against their real, pre-directive values -- a
regression guard for THIS directive and every future one that touches any of
these modules.
"""
from __future__ import annotations

import unittest


class EvidenceBarConstantsUnchangedTest(unittest.TestCase):
    def test_frequency_gate_constants(self) -> None:
        from nero_core.research_agent.frequency_gate import (
            FAST_MAX_MONTHS,
            MIN_CANDLES_FOR_MEASUREMENT,
            TARGET_RESOLVED_TRADES,
            VIABLE_MAX_MONTHS,
        )

        self.assertEqual(TARGET_RESOLVED_TRADES, 30)
        self.assertEqual(FAST_MAX_MONTHS, 6.0)
        self.assertEqual(VIABLE_MAX_MONTHS, 12.0)
        self.assertEqual(MIN_CANDLES_FOR_MEASUREMENT, 60)
        # The real "30/yr floor" this directive's own B2e references is
        # DERIVED from these two constants, not a separate literal --
        # confirmed here so a future edit to either one is caught even if
        # no test asserts the derived number directly.
        self.assertEqual(TARGET_RESOLVED_TRADES / (VIABLE_MAX_MONTHS / 12.0), 30.0)

    def test_train_test_split_is_still_70_30_chronological(self) -> None:
        from tools.backtest_train_test_split import TRAIN_FRACTION

        self.assertEqual(TRAIN_FRACTION, 0.7)

    def test_min_sample_size_is_still_20(self) -> None:
        from nero_core.research_agent.auto_tester import MIN_SAMPLE_SIZE

        self.assertEqual(MIN_SAMPLE_SIZE, 20)

    def test_fdr_alpha_is_still_0_05(self) -> None:
        from nero_core.eve.scoring import DEFAULT_FDR_ALPHA

        self.assertEqual(DEFAULT_FDR_ALPHA, 0.05)

    def test_random_baseline_k_is_still_200(self) -> None:
        from nero_core.eve.random_baseline import DEFAULT_K

        self.assertEqual(DEFAULT_K, 200)

    def test_admit_to_trial_gate_is_still_dsl_validity_only(self) -> None:
        # Same regression this project's own AdmitToTrialNeverConsultsFreshnessTest
        # already guards (tests/test_trial_admission.py) -- re-asserted here as
        # part of this directive's own explicit evidence-bar checklist rather
        # than assumed transitively.
        import inspect

        from nero_core.research_agent.trial import admit_to_trial

        params = set(inspect.signature(admit_to_trial).parameters)
        self.assertNotIn("freshness_disqualified", params)


if __name__ == "__main__":
    unittest.main()
