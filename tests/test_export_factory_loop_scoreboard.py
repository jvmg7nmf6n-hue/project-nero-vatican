"""Regression tests for nero_core/execution/export_factory_loop_scoreboard.py
-- the real Active-vs-Live distinction, the manual-vs-automated Repair Lab
separation, and honest error handling per section."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.execution import export_factory_loop_scoreboard as scoreboard
from nero_core.research_agent import repair_lab
from nero_core.truth_ledger.execution_log import insert_execution_log_row

NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


class LiveSchedulerSectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_active_count_reuses_stats_json_open_position_never_recomputed(self) -> None:
        strategies_path = self.tmp / "strategies.json"
        stats_path = self.tmp / "stats.json"
        strategies_path.write_text(json.dumps({"strategies": [{"name": "X"}, {"name": "Y"}]}))
        stats_path.write_text(json.dumps({"strategies": [
            {"strategy": "X", "strategy_version": "v1", "asset": "BTC", "open_position": {"entry_price": 100.0, "entry_timestamp": "2026-08-01T00:00:00+00:00"}},
            {"strategy": "Y", "strategy_version": "v1", "asset": "ETH", "open_position": None},
        ]}))
        with patch.object(scoreboard, "DEFAULT_STRATEGIES_PATH", strategies_path), \
             patch.object(scoreboard, "DEFAULT_STATS_PATH", stats_path):
            section = scoreboard._live_scheduler_section()

        self.assertEqual(section["tracked_count"], 2)
        self.assertEqual(section["active_count"], 1)
        self.assertEqual(section["active"][0]["strategy"], "X")
        self.assertEqual(section["active"][0]["entry_price"], 100.0)


class ForwardTrialActiveDetectionTest(unittest.TestCase):
    """The real fix this module exists for: an admitted-but-since-closed
    trial must NOT report as active, unlike a naive ENTRY-only read of
    trial_entries.json would (the real bug found 2026-08-08 --
    ETH_BIDIRECTIONAL_ZSCORE_FADE entered 2026-08-05, exited 2026-08-08,
    but the stale export still listed it as an open entry)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "forward_tracking.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _log(self, trial_id: str, signal_type: str, ts: str, price: float | None = None) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=f"TRIAL:{trial_id}", strategy_version="v1", asset="ETH",
            signal_type=signal_type, entry_price=price if signal_type == "ENTRY" else None,
            exit_price=price if signal_type == "EXIT" else None, reasoning="{}",
            candle_timestamp=0, timestamp=datetime.fromisoformat(ts), db_path=self.db_path,
        )

    def test_a_closed_trial_is_never_reported_active(self) -> None:
        self._log("closed-trial", "ENTRY", "2026-08-05T23:07:36+00:00", price=1916.6)
        self._log("closed-trial", "EXIT", "2026-08-08T00:17:06+00:00", price=1914.5)

        active = scoreboard._forward_trial_active_trial_ids(db_path=self.db_path)

        self.assertNotIn("closed-trial", active)

    def test_a_trial_with_an_unmatched_entry_is_reported_active(self) -> None:
        self._log("open-trial", "ENTRY", "2026-08-08T06:44:55+00:00", price=65046.0)

        active = scoreboard._forward_trial_active_trial_ids(db_path=self.db_path)

        self.assertIn("open-trial", active)
        self.assertEqual(active["open-trial"]["entry_price"], 65046.0)

    def test_a_trial_with_no_rows_at_all_is_never_reported_active(self) -> None:
        active = scoreboard._forward_trial_active_trial_ids(db_path=self.db_path)
        self.assertEqual(active, {})


class RepairLabSectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.candidates_path = self.tmp / "repair_candidates.json"
        self.events_path = self.tmp / "repair_attempts.json"
        self.candidates_path.write_text(json.dumps([
            {"parent_strategy": "X", "hypothesis_name": "X_FIX", "failure_pattern": "p", "diagnosis": "d", "proposed_fix": "f", "status": "candidate"},
        ]))
        self.events_path.write_text("[]")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_manual_and_automated_are_reported_as_two_separate_blocks(self) -> None:
        candidates = json.loads(self.candidates_path.read_text())
        with patch.object(repair_lab, "load_repair_candidates", return_value=candidates), \
             patch.object(repair_lab, "read_json_list", return_value=[]), \
             patch("tools.repair_alert.find_newly_launchable_candidates", return_value=[]):
            section = scoreboard._repair_lab_section()

        self.assertIn("manual_candidates", section)
        self.assertIn("automated_chains", section)
        self.assertEqual(section["manual_candidates"]["count"], 1)
        self.assertEqual(section["automated_chains"]["count"], 0)
        # Never merged into one combined number.
        self.assertNotIn("total_count", section)

    def test_a_real_launched_chain_reports_open_status_and_zero_healthy(self) -> None:
        events = [
            {"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": "RC-Y", "original_hypothesis_name": "Y", "opened_at": NOW.isoformat()},
            {"event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": "RC-Y", "attempt_id": "A1", "fresh_data_method": "forward_testing", "modification_type": "exit_structure", "launched_at": NOW.isoformat()},
        ]
        self.events_path.write_text(json.dumps(events))
        candidates = json.loads(self.candidates_path.read_text())

        with patch.object(repair_lab, "load_repair_candidates", return_value=candidates), \
             patch.object(repair_lab, "read_json_list", return_value=events), \
             patch("tools.repair_alert.find_newly_launchable_candidates", return_value=[]):
            section = scoreboard._repair_lab_section()

        self.assertEqual(section["automated_chains"]["count"], 1)
        self.assertEqual(section["automated_chains"]["open_chains"], 1)
        self.assertEqual(section["automated_chains"]["healthy_count"], 0)
        self.assertEqual(section["automated_chains"]["chains"][0]["chain_status"], repair_lab.CHAIN_OPEN)

    def test_a_survived_attempt_counts_as_healthy(self) -> None:
        events = [
            {"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": "RC-Z", "original_hypothesis_name": "Z", "opened_at": NOW.isoformat()},
            {"event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": "RC-Z", "attempt_id": "A1", "fresh_data_method": "forward_testing", "modification_type": "exit_structure", "launched_at": NOW.isoformat()},
            {"event": repair_lab.EVENT_ATTEMPT_RESOLVED, "repair_chain_id": "RC-Z", "attempt_id": "A1", "status": repair_lab.ATTEMPT_SURVIVED, "resolved_at": NOW.isoformat()},
        ]
        self.events_path.write_text(json.dumps(events))
        candidates = json.loads(self.candidates_path.read_text())

        with patch.object(repair_lab, "load_repair_candidates", return_value=candidates), \
             patch.object(repair_lab, "read_json_list", return_value=events), \
             patch("tools.repair_alert.find_newly_launchable_candidates", return_value=[]):
            section = scoreboard._repair_lab_section()

        self.assertEqual(section["automated_chains"]["healthy_count"], 1)
        self.assertEqual(section["automated_chains"]["chains"][0]["chain_status"], repair_lab.CHAIN_RESOLVED)


class BuildScoreboardFailIndependentTest(unittest.TestCase):
    def test_real_committed_data_builds_a_complete_scoreboard_without_raising(self) -> None:
        payload = scoreboard.build_scoreboard(NOW)
        for key in ("live_scheduler", "forward_trial", "repair_lab", "graveyard", "recent_activity"):
            self.assertIn(key, payload)
        self.assertIsInstance(payload["repair_lab"]["manual_candidates"]["count"], int)
        self.assertIsInstance(payload["repair_lab"]["automated_chains"]["count"], int)


if __name__ == "__main__":
    unittest.main()
