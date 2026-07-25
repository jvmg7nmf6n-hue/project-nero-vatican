"""Standalone dead-man's-switch check for the live scheduler, run by its own GitHub
Actions workflow (.github/workflows/scheduler_heartbeat_check.yml) on a schedule
independent of the scheduler's own cron -- so a scheduler outage (cron silently
stopped, a bug breaking every run, GitHub Actions itself degraded) produces a push
notification instead of going unnoticed for days.

Deliberately reads only the already-committed docs/site_data/heartbeat.json -- no
database access, no trading-related API keys -- so this watchdog can never itself be
the thing that breaks (a fragile watchdog is worse than no watchdog).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.execution.heartbeat import HEARTBEAT_PATH, is_stale, read_heartbeat

NTFY_URL = "https://ntfy.sh/Terminal3039"
NTFY_TIMEOUT_SECONDS = 10


def build_alert_message(now: datetime, heartbeat_path: Path = HEARTBEAT_PATH) -> str | None:
    """None means healthy -- no alert needed. A non-None return is always the exact
    message to send, so callers (and tests) never have to re-derive the wording."""
    status = read_heartbeat(heartbeat_path)
    if not is_stale(status, now):
        return None
    if status is None:
        return "VATICAN SCHEDULER DOWN — no heartbeat file found at all"
    return f"VATICAN SCHEDULER DOWN — no successful run since {status.last_successful_run}"


def send_ntfy_alert(message: str, url: str = NTFY_URL, timeout_seconds: int = NTFY_TIMEOUT_SECONDS) -> bool:
    """Best-effort delivery -- never raises. Mirrors notify_ntfy.send_ntfy_notification."""
    try:
        response = requests.post(url, data=message.encode("utf-8"), timeout=timeout_seconds)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"ntfy alert failed (non-fatal): {exc.__class__.__name__}: {exc}")
        return False


def main() -> None:
    now = datetime.now(timezone.utc)
    message = build_alert_message(now)
    if message is None:
        print("Scheduler heartbeat OK — no alert sent.")
        return
    print(f"Sending scheduler-down alert to {NTFY_URL}: {message}")
    send_ntfy_alert(message)


if __name__ == "__main__":
    main()
