from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from nero_core.execution import scheduler_heartbeat_alert
from nero_core.execution.scheduler_heartbeat_alert import build_alert_message, send_ntfy_alert


def _now() -> datetime:
    return datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _write_heartbeat(path: Path, last_successful_run: datetime, run_count_24h: int = 48) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_successful_run": last_successful_run.isoformat(), "run_count_24h": run_count_24h})
    )


class BuildAlertMessageTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.heartbeat_path = Path(self._tmp.name) / "heartbeat.json"
        self.addCleanup(self._tmp.cleanup)

    def test_no_alert_when_heartbeat_is_fresh(self) -> None:
        _write_heartbeat(self.heartbeat_path, _now() - timedelta(minutes=30))

        message = build_alert_message(_now(), heartbeat_path=self.heartbeat_path)

        self.assertIsNone(message)

    def test_alert_fires_when_heartbeat_is_stale(self) -> None:
        last_run = _now() - timedelta(hours=5)
        _write_heartbeat(self.heartbeat_path, last_run)

        message = build_alert_message(_now(), heartbeat_path=self.heartbeat_path)

        self.assertIsNotNone(message)
        self.assertIn("VATICAN SCHEDULER DOWN", message)
        self.assertIn(last_run.isoformat(), message)

    def test_alert_fires_when_heartbeat_file_is_entirely_missing(self) -> None:
        message = build_alert_message(_now(), heartbeat_path=self.heartbeat_path)

        self.assertIsNotNone(message)
        self.assertIn("VATICAN SCHEDULER DOWN", message)
        self.assertIn("no heartbeat file found", message)

    def test_no_alert_right_at_the_two_hour_boundary(self) -> None:
        _write_heartbeat(self.heartbeat_path, _now() - timedelta(hours=2))

        message = build_alert_message(_now(), heartbeat_path=self.heartbeat_path)

        self.assertIsNone(message)

    def test_alert_fires_just_past_the_two_hour_boundary(self) -> None:
        _write_heartbeat(self.heartbeat_path, _now() - timedelta(hours=2, minutes=1))

        message = build_alert_message(_now(), heartbeat_path=self.heartbeat_path)

        self.assertIsNotNone(message)


class SendNtfyAlertTest(unittest.TestCase):
    def test_successful_post_returns_true_with_correct_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch.object(scheduler_heartbeat_alert.requests, "post", return_value=mock_response) as mock_post:
            result = send_ntfy_alert("VATICAN SCHEDULER DOWN — test", url="https://ntfy.sh/Terminal3039")

        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://ntfy.sh/Terminal3039")
        self.assertEqual(kwargs["data"], "VATICAN SCHEDULER DOWN — test".encode("utf-8"))

    def test_network_failure_is_caught_and_returns_false(self) -> None:
        with patch.object(
            scheduler_heartbeat_alert.requests, "post", side_effect=requests.ConnectionError("down")
        ):
            result = send_ntfy_alert("VATICAN SCHEDULER DOWN — test")

        self.assertFalse(result)

    def test_non_2xx_response_is_caught_and_returns_false(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500")

        with patch.object(scheduler_heartbeat_alert.requests, "post", return_value=mock_response):
            result = send_ntfy_alert("VATICAN SCHEDULER DOWN — test")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
