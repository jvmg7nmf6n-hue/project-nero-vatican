from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nero_core.execution.heartbeat import (
    STALE_ALERT_THRESHOLD_HOURS,
    HeartbeatStatus,
    compute_run_count_24h,
    is_stale,
    read_heartbeat,
    write_heartbeat,
)
from nero_core.truth_ledger.execution_log import insert_execution_metadata


def _now() -> datetime:
    return datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


class WriteHeartbeatTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.heartbeat_path = Path(self._tmp.name) / "site_data" / "heartbeat.json"
        self.addCleanup(self._tmp.cleanup)

    def test_write_heartbeat_creates_file_with_timestamp_and_run_count(self) -> None:
        insert_execution_metadata(
            run_id="run-1", start_time=_now(), end_time=_now(),
            assets_evaluated=["GOLD"], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )

        status = write_heartbeat(now=_now(), db_path=self.db_path, heartbeat_path=self.heartbeat_path)

        self.assertTrue(self.heartbeat_path.exists())
        on_disk = json.loads(self.heartbeat_path.read_text())
        self.assertEqual(on_disk["last_successful_run"], _now().isoformat())
        self.assertEqual(on_disk["run_count_24h"], 1)
        self.assertEqual(status.run_count_24h, 1)

    def test_write_heartbeat_overwrites_rather_than_appends(self) -> None:
        write_heartbeat(now=_now(), db_path=self.db_path, heartbeat_path=self.heartbeat_path)
        later = _now() + timedelta(minutes=30)

        write_heartbeat(now=later, db_path=self.db_path, heartbeat_path=self.heartbeat_path)

        on_disk = json.loads(self.heartbeat_path.read_text())
        self.assertEqual(on_disk["last_successful_run"], later.isoformat())

    def test_run_count_24h_excludes_runs_older_than_the_window(self) -> None:
        old_run = _now() - timedelta(hours=30)
        insert_execution_metadata(
            run_id="run-old", start_time=old_run, end_time=old_run,
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )
        insert_execution_metadata(
            run_id="run-recent", start_time=_now() - timedelta(hours=1), end_time=_now(),
            assets_evaluated=[], assets_skipped=[], errors_encountered=[], db_path=self.db_path,
        )

        count = compute_run_count_24h(_now(), db_path=self.db_path)

        self.assertEqual(count, 1)

    def test_read_heartbeat_returns_none_when_file_is_missing(self) -> None:
        self.assertIsNone(read_heartbeat(self.heartbeat_path))

    def test_read_heartbeat_round_trips_a_written_file(self) -> None:
        write_heartbeat(now=_now(), db_path=self.db_path, heartbeat_path=self.heartbeat_path)

        status = read_heartbeat(self.heartbeat_path)

        self.assertIsNotNone(status)
        self.assertEqual(status.last_successful_run, _now().isoformat())


class IsStaleTest(unittest.TestCase):
    def test_missing_status_is_always_stale(self) -> None:
        self.assertTrue(is_stale(None, _now()))

    def test_fresh_heartbeat_is_not_stale(self) -> None:
        fresh = HeartbeatStatus(last_successful_run=(_now() - timedelta(minutes=30)).isoformat(), run_count_24h=48)
        self.assertFalse(is_stale(fresh, _now()))

    def test_heartbeat_older_than_threshold_is_stale(self) -> None:
        stale = HeartbeatStatus(last_successful_run=(_now() - timedelta(hours=3)).isoformat(), run_count_24h=0)
        self.assertTrue(is_stale(stale, _now()))

    def test_heartbeat_exactly_at_threshold_is_not_yet_stale(self) -> None:
        at_threshold = HeartbeatStatus(
            last_successful_run=(_now() - timedelta(hours=STALE_ALERT_THRESHOLD_HOURS)).isoformat(),
            run_count_24h=10,
        )
        self.assertFalse(is_stale(at_threshold, _now()))


if __name__ == "__main__":
    unittest.main()
