"""Repair Lab v1, Task 1: the eligibility gate must only ever let a DIED
hypothesis through. Every other verdict must be explicitly rejected with a
clear reason -- never a silent no-op, never a silent accept."""
from __future__ import annotations

import unittest

from nero_core.research_agent.repair_lab import check_eligibility


class EligibilityGateTest(unittest.TestCase):
    def test_died_is_eligible(self) -> None:
        # Real shape from this session's own EXT_WISE_MAN_HOLD_V5_ETH_4H DIED
        # result (feature/short-side-support's backward-compat baseline).
        result = {
            "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
            "verdict": "DIED", "review_status": "dead", "frequency_classification": "VIABLE",
            "reason": "train: N=176 ExpR=-0.330; test: N=53 ExpR=-0.057 -> DIED",
        }
        outcome = check_eligibility(result)
        self.assertTrue(outcome.eligible)
        self.assertIn("eligible", outcome.reason)

    def test_too_slow_is_rejected_with_the_specific_frequency_classification_named(self) -> None:
        # Real shape from this session's own EXT_ADX_RANGE_V3_BTC_1D TOO_SLOW result.
        result = {
            "hypothesis_name": "EXT_ADX_RANGE_V3_BTC_1D", "asset": "BTC", "timeframe": "24h",
            "verdict": "SKIPPED", "review_status": "rejected_too_slow", "frequency_classification": "TOO_SLOW",
            "reason": "Bidirectional: long 45 trigger(s) + short 61 trigger(s) = 106 combined over "
                      "3270 eligible days (11.84 trades/year) -> ~30.4 months to 30 resolved trades -> TOO_SLOW.",
        }
        outcome = check_eligibility(result)
        self.assertFalse(outcome.eligible)
        self.assertIn("not_eligible", outcome.reason)
        self.assertIn("TOO_SLOW", outcome.reason)
        self.assertIn("Repair Lab v1", outcome.reason)

    def test_unmeasurable_is_rejected_with_the_specific_frequency_classification_named(self) -> None:
        result = {
            "verdict": "SKIPPED", "review_status": "rejected_unmeasurable", "frequency_classification": "UNMEASURABLE",
        }
        outcome = check_eligibility(result)
        self.assertFalse(outcome.eligible)
        self.assertIn("UNMEASURABLE", outcome.reason)

    def test_untestable_is_rejected(self) -> None:
        result = {"verdict": "UNTESTABLE", "review_status": "untestable"}
        outcome = check_eligibility(result)
        self.assertFalse(outcome.eligible)
        self.assertIn("UNTESTABLE", outcome.reason)

    def test_survived_is_rejected_doesnt_need_repair(self) -> None:
        result = {"verdict": "SURVIVED", "review_status": "pending_human_approval"}
        outcome = check_eligibility(result)
        self.assertFalse(outcome.eligible)
        self.assertIn("SURVIVED", outcome.reason)

    def test_promising_watchlist_is_rejected_doesnt_need_repair(self) -> None:
        result = {"verdict": "PROMISING-WATCHLIST", "review_status": "pending_human_approval"}
        outcome = check_eligibility(result)
        self.assertFalse(outcome.eligible)
        self.assertIn("PROMISING-WATCHLIST", outcome.reason)

    def test_missing_or_unrecognized_verdict_is_rejected_not_silently_accepted(self) -> None:
        outcome = check_eligibility({})
        self.assertFalse(outcome.eligible)
        self.assertIn("not_eligible", outcome.reason)

        outcome2 = check_eligibility({"verdict": "SOMETHING_MADE_UP"})
        self.assertFalse(outcome2.eligible)
        self.assertIn("not_eligible", outcome2.reason)

    def test_every_rejection_reason_is_non_empty_and_never_a_bare_verdict_string(self) -> None:
        # Rejection reasons must always be explanatory (per the task's own
        # "never silently no-op" requirement), not just the verdict echoed back.
        for verdict in ("SKIPPED", "UNTESTABLE", "SURVIVED", "PROMISING-WATCHLIST", "GARBAGE"):
            with self.subTest(verdict=verdict):
                outcome = check_eligibility({"verdict": verdict, "frequency_classification": "TOO_SLOW"})
                self.assertFalse(outcome.eligible)
                self.assertGreater(len(outcome.reason), len(verdict))


if __name__ == "__main__":
    unittest.main()
