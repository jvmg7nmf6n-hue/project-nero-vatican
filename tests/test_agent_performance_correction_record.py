"""Regression test for the correction records appended to the real
docs/site_data/agent_performance.json (Eve engine v1 session, item 3b).

The two 2026-07-29 run entries predate `status`/`errors` (added in commit
8204f9e) -- CLAUDE.md's own audit-trail rule ("never mutate an audit entry")
means those two entries must never be edited to backfill the missing
fields. This test proves that rule was actually followed on the real
committed file, not just documented as an intention: the two original
entries carry none of the new fields, and the missing information instead
lives in a separate, appended `corrections` list."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_PATH = REPO_ROOT / "docs" / "site_data" / "agent_performance.json"

RUN_0_AT = "2026-07-29T16:45:14.151752+00:00"  # b3361b4: real scan run, api_key="" deliberately
RUN_1_AT = "2026-07-29T17:17:03.810695+00:00"  # 4189f6b: 3 calls, all 401 Unauthorized, $0 cost


class AgentPerformanceFileLoadsTest(unittest.TestCase):
    def test_file_exists_and_parses(self) -> None:
        self.assertTrue(PERFORMANCE_PATH.exists())
        json.loads(PERFORMANCE_PATH.read_text())


class OriginalRunEntriesNeverMutatedTest(unittest.TestCase):
    """HARD CHECK: the two pre-instrumentation run entries must never gain a
    status/errors key -- that would be editing an audit record after the
    fact, exactly what the correction-record mechanism exists to avoid."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(PERFORMANCE_PATH.read_text())
        cls.runs_by_at = {r["run_at"]: r for r in cls.data["runs"]}

    def test_both_2026_07_29_entries_are_present(self) -> None:
        self.assertIn(RUN_0_AT, self.runs_by_at)
        self.assertIn(RUN_1_AT, self.runs_by_at)

    def test_run_0_has_no_status_or_errors_key(self) -> None:
        run = self.runs_by_at[RUN_0_AT]
        self.assertNotIn("status", run)
        self.assertNotIn("errors", run)

    def test_run_1_has_no_status_or_errors_key(self) -> None:
        run = self.runs_by_at[RUN_1_AT]
        self.assertNotIn("status", run)
        self.assertNotIn("errors", run)

    def test_run_1_is_the_llm_calls_made_3_zero_cost_shape(self) -> None:
        # The exact shape the task text calls out as looking like success
        # when it wasn't: 3 calls made, $0 spent, nothing generated.
        run = self.runs_by_at[RUN_1_AT]
        self.assertEqual(run["llm_calls_made"], 3)
        self.assertEqual(run["total_llm_cost_usd"], 0.0)
        self.assertEqual(run["hypotheses_generated"], 0)


class CorrectionRecordsTest(unittest.TestCase):
    REQUIRED_KEYS = {
        "correction_id", "applies_to_run_at", "corrected_at",
        "reason_field_absent", "inferred_status", "inferred_status_basis", "note",
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(PERFORMANCE_PATH.read_text())
        cls.corrections = cls.data.get("corrections", [])
        cls.by_run_at = {c["applies_to_run_at"]: c for c in cls.corrections}

    def test_a_correction_exists_for_each_2026_07_29_run(self) -> None:
        self.assertIn(RUN_0_AT, self.by_run_at)
        self.assertIn(RUN_1_AT, self.by_run_at)

    def test_every_correction_has_all_required_keys(self) -> None:
        for correction in self.corrections:
            self.assertEqual(self.REQUIRED_KEYS - set(correction.keys()), set())

    def test_correction_ids_are_unique(self) -> None:
        ids = [c["correction_id"] for c in self.corrections]
        self.assertEqual(len(ids), len(set(ids)))

    def test_run_1_correction_infers_error_status(self) -> None:
        # Per commit 4189f6b's own message: "failed with 401 Unauthorized on
        # all 3 calls." This is a documented historical fact, not a guess
        # from the numbers alone -- the basis field must say so.
        correction = self.by_run_at[RUN_1_AT]
        self.assertEqual(correction["inferred_status"], "error")
        self.assertIn("401", correction["inferred_status_basis"])
        self.assertIn("4189f6b", correction["inferred_status_basis"])

    def test_run_0_correction_infers_clean_status(self) -> None:
        # Per commit b3361b4's own message: api_key="" was passed
        # deliberately, zero live calls attempted on purpose -- a clean,
        # not a failed, run.
        correction = self.by_run_at[RUN_0_AT]
        self.assertEqual(correction["inferred_status"], "clean")
        self.assertIn("b3361b4", correction["inferred_status_basis"])

    def test_inferred_status_is_a_valid_status_value(self) -> None:
        valid = {"disabled", "error", "clean"}
        for correction in self.corrections:
            self.assertIn(correction["inferred_status"], valid)


if __name__ == "__main__":
    unittest.main()
