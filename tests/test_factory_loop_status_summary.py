"""CC-1 Factory Loop directive, item 9: live status snapshot generator.

Covers compute_summary_data's three sub-objects against fixture data,
matching tools/research_agent_run_summary.py's own test-the-pure-function
convention (no I/O in the function under test)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from nero_core.research_agent import repair_lab
from tools import factory_loop_status_summary as summary


class ForwardTrialSummaryTest(unittest.TestCase):
    def test_empty_records(self) -> None:
        result = summary.compute_summary_data([], [], [])
        self.assertEqual(result["forward_trial"], {"count": 0, "by_origin": {"adam": 0, "eve": 0, "repaired": 0}, "unmeasurable_count": 0})

    def test_counts_by_origin(self) -> None:
        records = [
            {"status": "OPEN", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "adam"}, "projected_time_to_min_sample_years": 0.5},
            {"status": "OPEN", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "eve"}, "projected_time_to_min_sample_years": 0.5},
            {"status": "SURVIVED_TRIAL", "source_hypothesis_ref": {"origin": "repaired", "origin_agent": "adam"}, "projected_time_to_min_sample_years": 1.0},
        ]
        result = summary.compute_summary_data(records, [], [])
        self.assertEqual(result["forward_trial"]["by_origin"], {"adam": 1, "eve": 1, "repaired": 1})
        self.assertEqual(result["forward_trial"]["count"], 3)

    def test_unmeasurable_count_only_counts_open_beyond_horizon_or_none(self) -> None:
        records = [
            {"status": "OPEN", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "adam"}, "projected_time_to_min_sample_years": 5.0},
            {"status": "OPEN", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "adam"}, "projected_time_to_min_sample_years": None},
            {"status": "OPEN", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "adam"}, "projected_time_to_min_sample_years": 0.5},
            # SURVIVED_TRIAL, not OPEN -- must never count even with a huge projected time
            {"status": "SURVIVED_TRIAL", "source_hypothesis_ref": {"origin": "fresh", "origin_agent": "adam"}, "projected_time_to_min_sample_years": 40.0},
        ]
        result = summary.compute_summary_data(records, [], [])
        self.assertEqual(result["forward_trial"]["unmeasurable_count"], 2)


class GraveyardSummaryTest(unittest.TestCase):
    def test_counts_real_entries(self) -> None:
        result = summary.compute_summary_data([], [{"name": "A"}, {"name": "B"}], [])
        self.assertEqual(result["graveyard"], {"count": 2, "distilled_this_period": 0, "pending_review": 0})

    def test_pending_review_counts_real_drafts_at_review_pending(self) -> None:
        # CC-1 Master Directive Phase 2: tools.factory_loop_run is now the
        # first real writer of a distillation-drafts file -- this closes the
        # module's own previously documented KNOWN LIMITATION (this field
        # used to be a hardcoded 0 with no way to ever become non-zero).
        drafts = [
            {"name": "DRAFT_A", "review_status": "pending_human_approval"},
            {"name": "DRAFT_B", "review_status": "pending_human_approval"},
            {"name": "DRAFT_C", "review_status": "approved"},
        ]
        result = summary.compute_summary_data([], [], [], drafts)
        self.assertEqual(result["graveyard"]["pending_review"], 2)

    def test_missing_drafts_file_is_honestly_zero_not_fabricated(self) -> None:
        result = summary.compute_summary_data([], [], [], None)
        self.assertEqual(result["graveyard"]["pending_review"], 0)


class RepairSummaryTest(unittest.TestCase):
    def test_open_and_resolved_chains_counted_correctly(self) -> None:
        events = [
            {"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": "RC-OPEN", "original_hypothesis_name": "X", "opened_at": "2026-08-01T00:00:00+00:00"},
            {"event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": "RC-OPEN", "attempt_id": "A1", "fresh_data_method": "historical_reservation", "launched_at": "2026-08-01T00:00:00+00:00"},

            {"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": "RC-RESOLVED", "original_hypothesis_name": "Y", "opened_at": "2026-08-01T00:00:00+00:00"},
            {"event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": "RC-RESOLVED", "attempt_id": "A1", "fresh_data_method": "historical_reservation", "launched_at": "2026-08-01T00:00:00+00:00"},
            {"event": repair_lab.EVENT_ATTEMPT_RESOLVED, "repair_chain_id": "RC-RESOLVED", "attempt_id": "A1", "status": repair_lab.ATTEMPT_SURVIVED, "result": {}, "resolved_at": "2026-08-02T00:00:00+00:00"},
        ]
        result = summary.compute_summary_data([], [], events)
        self.assertEqual(result["repair"], {"count": 2, "open_chains": 1, "resolved_chains": 1})

    def test_empty_events(self) -> None:
        result = summary.compute_summary_data([], [], [])
        self.assertEqual(result["repair"], {"count": 0, "open_chains": 0, "resolved_chains": 0})


class WriteStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "factory_loop_status.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_status_produces_valid_json_with_schema_and_timestamp(self) -> None:
        summary_data = summary.compute_summary_data([], [], [])
        summary.write_status(summary_data, path=self.path)

        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(written["schema_version"], summary.SCHEMA_VERSION)
        self.assertIn("last_updated", written)
        self.assertEqual(written["forward_trial"]["count"], 0)
        self.assertEqual(written["graveyard"]["count"], 0)
        self.assertEqual(written["repair"]["count"], 0)

    def test_key_is_forward_trial_not_trial(self) -> None:
        # item 8c's locked naming decision -- must never regress to "trial".
        summary_data = summary.compute_summary_data([], [], [])
        summary.write_status(summary_data, path=self.path)
        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("forward_trial", written)
        self.assertNotIn("trial", written)


if __name__ == "__main__":
    unittest.main()
