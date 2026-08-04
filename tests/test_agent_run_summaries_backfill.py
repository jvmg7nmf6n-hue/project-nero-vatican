"""Regression test for the CC-1 review's item 2c: the 2026-08-03 real Adam
run's calibration figures (claimed 24-32 trades/year, measured 2.5-15/year,
~4.79x average overestimate, all 9 rejected TOO_SLOW) could not be
independently reconstructed from any committed file in this repository
(docs/site_data/agent_hypotheses.json and agent_test_results.json do not
exist; agent_performance.json's own runs list has no 2026-08-03 entry).
They are committed here as a backfilled entry, explicitly and permanently
tagged as chat-transcript-sourced rather than repo-verified -- this test
guards that tag against ever being silently dropped or relabeled."""
from __future__ import annotations

import json
import unittest

from tools.research_agent_run_summary import REPO_ROOT

RUN_SUMMARIES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_run_summaries.json"


class BackfilledEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = json.loads(RUN_SUMMARIES_PATH.read_text(encoding="utf-8"))
        backfilled = [e for e in self.entries if e.get("backfilled") is True]
        self.assertEqual(len(backfilled), 1, "expected exactly one backfilled 2026-08-03 entry")
        self.entry = backfilled[0]

    def test_source_is_explicitly_not_a_real_run(self) -> None:
        self.assertIn("chat-transcript-sourced", self.entry["source"])
        self.assertIn("not independently verified", self.entry["source"])
        self.assertNotEqual(self.entry["source"], "research_agent_run_summary.py")

    def test_carries_the_exact_figures_reported(self) -> None:
        calibration = self.entry["calibration"]
        self.assertEqual(calibration["average_ratio"], 4.79)
        self.assertEqual(calibration["claimed_trades_per_year_range"], [24, 32])
        self.assertEqual(calibration["measured_trades_per_year_range"], [2.5, 15])
        self.assertEqual(self.entry["run_aggregate"]["hypotheses_generated"], 9)
        self.assertEqual(self.entry["run_aggregate"]["too_slow_rejected"], 9)

    def test_data_completeness_is_marked_aggregate_only(self) -> None:
        self.assertIn("aggregate_only", self.entry["data_completeness"])

    def test_provenance_note_explains_why_it_could_not_be_reconstructed(self) -> None:
        note = self.entry["provenance_note"]
        self.assertIn("agent_hypotheses.json", note)
        self.assertIn("could NOT be independently reconstructed", note)

    def test_per_hypothesis_detail_is_absent_not_fabricated(self) -> None:
        # Only the aggregate figures were ever supplied -- per-hypothesis
        # names/individual values must stay null, never invented.
        self.assertIsNone(self.entry["per_hypothesis"])
        self.assertIsNone(self.entry["too_slow"])
        self.assertIsNone(self.entry["calibration"]["ratio_by_hypothesis_name"])


if __name__ == "__main__":
    unittest.main()
