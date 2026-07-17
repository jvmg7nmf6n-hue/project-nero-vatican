"""Wall-clock "is this timeframe due" pre-filter for the live scheduler.

This is deliberately a CHEAP, GENEROUS pre-filter, not the source of correctness — the
actual "did a new candle really close" decision is made downstream by comparing the
freshly-fetched data's own close_time against the last candle_timestamp already logged
in execution_log (see nero_core.execution.replay / nero_core.execution.live_scheduler).
This module only decides whether a given (asset, strategy, timeframe) is even worth
fetching THIS run, so a strategy whose timeframe closes once a week isn't re-fetched and
re-evaluated on every 30-minute tick for no reason.

Being wrong in the generous direction (checking slightly too often) costs nothing beyond
an extra network call that finds no new closed candle. Being wrong in the strict
direction (missing the actual boundary) would silently skip a real signal — so every
tolerance window below is deliberately wider than the scheduler's own 30-minute run
cadence (see .github/workflows/live_scheduler.yml), to absorb realistic GitHub Actions
scheduling delay.
"""
from __future__ import annotations

from datetime import datetime, timezone

from nero_core.strategies.timeframe_calibration import HOURS_PER_TIMEFRAME

DEFAULT_TOLERANCE_MINUTES = 40

WEEKLY_CLOSE_WEEKDAY = 4  # Monday=0 ... Friday=4
WEEKLY_CLOSE_HOUR_UTC = 0


def _require_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware (UTC)")
    return now.astimezone(timezone.utc)


def candle_boundary_due(timeframe: str, now: datetime, tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES) -> bool:
    """True if `now` falls within `tolerance_minutes` after a candle-close boundary for
    `timeframe`. Raises ValueError for an unrecognized timeframe."""
    now_utc = _require_utc(now)

    if timeframe == "1week":
        if now_utc.weekday() != WEEKLY_CLOSE_WEEKDAY:
            return False
        minutes_since_boundary = (now_utc.hour - WEEKLY_CLOSE_HOUR_UTC) * 60 + now_utc.minute
        return 0 <= minutes_since_boundary < tolerance_minutes

    if timeframe == "1h":
        return now_utc.minute < tolerance_minutes

    hours = HOURS_PER_TIMEFRAME.get(timeframe)
    if hours is None:
        raise ValueError(f"unsupported timeframe for boundary check: {timeframe!r}")
    boundary_interval_minutes = hours * 60
    minutes_since_midnight = now_utc.hour * 60 + now_utc.minute
    offset = minutes_since_midnight % boundary_interval_minutes
    return offset < tolerance_minutes


def daily_time_due(hour_utc: int, now: datetime, tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES) -> bool:
    """True if `now` falls within `tolerance_minutes` after `hour_utc:00` UTC on any
    day — used for the once-daily News Sentiment run, which isn't tied to a candle close
    at all."""
    now_utc = _require_utc(now)
    minutes_since_boundary = (now_utc.hour - hour_utc) * 60 + now_utc.minute
    return 0 <= minutes_since_boundary < tolerance_minutes
