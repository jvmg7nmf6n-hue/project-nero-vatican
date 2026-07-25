"""Scheduler heartbeat: writes docs/site_data/heartbeat.json so a silently-stopped
GitHub Actions cron can be detected from the outside, rather than only noticed when
someone happens to look at the Truth Ledger and see stale timestamps.

Written once per successful live_scheduler run (see live_scheduler.main()) --
"successful" here means run_once() returned without raising, which is also exactly
when an execution_metadata row gets inserted (nero_core.truth_ledger.execution_log.
insert_execution_metadata). A run that raises before reaching that point (a bug
outside any single config's own try/except) does NOT update the heartbeat -- that's
the point: this is a "has anything completed recently" signal, not a "did the
process launch" signal.

A separate script (scheduler_heartbeat_alert.py) and workflow
(.github/workflows/scheduler_heartbeat_check.yml) read this file on their own
schedule and page Terminal3039 via ntfy if it goes stale -- kept wholly separate from
this module and from live_scheduler.py itself, for the same reason notify_ntfy.py is
separate from live_scheduler.py: an alerting bug must never be able to affect whether
a signal gets logged, and vice versa.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nero_core.truth_ledger.execution_log import list_execution_metadata
from nero_core.truth_ledger.models import DEFAULT_DB_PATH

HEARTBEAT_PATH = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "heartbeat.json"

# How long since the last successful run before the watchdog pages someone.
STALE_ALERT_THRESHOLD_HOURS = 2.0
# Window run_count_24h is computed over -- descriptive only (roughly 48 runs/day at
# the scheduler's 30-minute cadence when healthy), not itself an alert threshold.
RUN_COUNT_WINDOW_HOURS = 24.0


@dataclass(frozen=True)
class HeartbeatStatus:
    last_successful_run: str
    run_count_24h: int


def compute_run_count_24h(now: datetime, db_path: Path = DEFAULT_DB_PATH) -> int:
    window_start = now - timedelta(hours=RUN_COUNT_WINDOW_HOURS)
    return sum(1 for row in list_execution_metadata(db_path) if row.start_time >= window_start)


def write_heartbeat(
    now: datetime | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    heartbeat_path: Path = HEARTBEAT_PATH,
) -> HeartbeatStatus:
    """Overwrites (not appends) -- the heartbeat only ever needs to answer "when did
    the last successful run finish," not accumulate history; that history already
    lives in execution_metadata."""
    now = now or datetime.now(timezone.utc)
    status = HeartbeatStatus(
        last_successful_run=now.isoformat(),
        run_count_24h=compute_run_count_24h(now, db_path),
    )
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {"last_successful_run": status.last_successful_run, "run_count_24h": status.run_count_24h},
            indent=2,
        )
        + "\n"
    )
    return status


def read_heartbeat(heartbeat_path: Path = HEARTBEAT_PATH) -> HeartbeatStatus | None:
    if not heartbeat_path.exists():
        return None
    data = json.loads(heartbeat_path.read_text())
    return HeartbeatStatus(
        last_successful_run=data["last_successful_run"], run_count_24h=data["run_count_24h"]
    )


def is_stale(
    status: HeartbeatStatus | None, now: datetime, threshold_hours: float = STALE_ALERT_THRESHOLD_HOURS
) -> bool:
    """True if there is no heartbeat at all, OR the last successful run is older than
    threshold_hours. A missing heartbeat file is treated as stale (fail loud) rather
    than "nothing to alert on"."""
    if status is None:
        return True
    last_run = datetime.fromisoformat(status.last_successful_run)
    return (now - last_run) > timedelta(hours=threshold_hours)
