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

BUG FOUND 2026-07-28 (PEAD zero-signal investigation): "24h" and "1week" get only ONE
boundary opportunity per period (a day, a week), unlike every other supported timeframe
("1h"/"2h"/"4h"/"12h"), which gets several opportunities within the same period even if
one run is missed. DEFAULT_TOLERANCE_MINUTES (40) was applied uniformly to all of them.
Querying this project's own execution_metadata history end to end confirmed every
observed day's first post-midnight-UTC run landed between roughly 15 and 105 minutes
after 00:00 UTC, and MOST days landed outside the 40-minute window entirely (GitHub's
own scheduled-workflow docs note `schedule` runs are delayed most at exactly the popular
top-of-hour/midnight slots this project's cron ("0,30 * * * *") uses) -- so
candle_boundary_due("24h", ...) and ("1week", ...) returned True on only 1 of 143
observed runs each over 10+ days. This silently starved every "24h"/"1week" strategy of
its only per-period evaluation almost every time, including GOLD/1week/BREAKOUT_MOMENTUM
(this project's own flagship SURVIVOR, never evaluated even once in the observed
history) and all 14 PEAD configs -- not a PEAD-specific defect. Given a missed "24h"/
"1week" window costs an entire day/week (no other opportunity that period) while a wider
tolerance costs nothing (the next real boundary is still 24h/1week away, and downstream
replay functions already dedupe on the last logged candle_timestamp regardless of how
many "due" runs land inside the window), SINGLE_SHOT_TOLERANCE_MINUTES below is
deliberately generous.

FOLLOW-UP 2026-07-29 (health check's first real run surfaced two more instances of
the SAME underlying pattern): the new nero_core.execution.health_check watchdog
found "12h" (BNB/TREND_PULLBACK, BTC-ETH/COINTEGRATION_PAIRS) at zero signals in
143 runs, and NEWS_SENTIMENT's daily_time_due gate missing its 48h health-check
threshold by 77.5h. Queried execution_metadata's real run-time history for both
gates specifically (not assumed):
  - "12h" has TWO boundary opportunities per day (00:00 and 12:00 UTC), unlike
    "24h"/"1week"'s single shot -- but BOTH windows individually showed the same
    congestion pattern: the day's first run after 00:00 UTC landed 15-106 minutes
    late (median 87), and after 12:00 UTC landed 8-74 minutes late (median 54).
    139 of 143 real runs recorded NOT_DUE for both BNB and BTC-ETH. Because "12h"
    keeps its same-day redundancy (missing the AM window still leaves the PM one),
    it doesn't need the full single-shot tolerance -- MULTI_SHOT_TOLERANCE_MINUTES
    below reliably covers the observed 106-minute worst case with real margin
    while staying meaningfully narrower than SINGLE_SHOT_TOLERANCE_MINUTES.
  - daily_time_due (hour_utc=19 for NEWS_SENTIMENT) has ZERO same-day
    redundancy -- exactly "24h"/"1week"'s severity class, just a different anchor
    hour and a different gate FUNCTION (not tied to a candle close at all). Its
    real run-time history showed 18-76 minutes of steady-state delay (matching
    the "12h"-PM pattern) plus one 229-minute outlier on 2026-07-17, the
    workflow's first-ever calendar day (a one-time startup artifact, not a
    recurring pattern -- but still real data, and SINGLE_SHOT_TOLERANCE_MINUTES
    (240) comfortably covers it too, so daily_time_due now defaults to the same
    constant rather than inventing a third number to explain.
"""
from __future__ import annotations

from datetime import datetime, timezone

from nero_core.strategies.timeframe_calibration import HOURS_PER_TIMEFRAME

DEFAULT_TOLERANCE_MINUTES = 40

# See the BUG FOUND note above -- "24h", "1week", and daily_time_due's own gate only
# get one shot per period, so their default tolerance must reliably absorb realistic
# GitHub Actions `schedule` delay (empirically up to ~230 minutes -- see the
# FOLLOW-UP note above for daily_time_due's own worst observed case) rather than the
# generic 40-minute default sized for timeframes with multiple daily opportunities.
SINGLE_SHOT_TOLERANCE_MINUTES = 240

# See the FOLLOW-UP note above -- "12h" gets two opportunities per day (unlike the
# single-shot timeframes above), so a missed window isn't as costly, but empirically
# both of ITS windows individually showed the same congestion pattern as the
# single-shot gates (observed worst case ~106 minutes) -- narrower than
# SINGLE_SHOT_TOLERANCE_MINUTES, but still well past DEFAULT_TOLERANCE_MINUTES.
MULTI_SHOT_TOLERANCE_MINUTES = 150

WEEKLY_CLOSE_WEEKDAY = 4  # Monday=0 ... Friday=4
WEEKLY_CLOSE_HOUR_UTC = 0


def _require_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware (UTC)")
    return now.astimezone(timezone.utc)


def candle_boundary_due(timeframe: str, now: datetime, tolerance_minutes: int | None = None) -> bool:
    """True if `now` falls within the applicable tolerance window after a candle-close
    boundary for `timeframe`. Raises ValueError for an unrecognized timeframe.

    `tolerance_minutes`: explicit override, used as-is when given. When omitted
    (None, the default), the effective tolerance depends on the timeframe:
    SINGLE_SHOT_TOLERANCE_MINUTES for "24h"/"1week" (only one boundary opportunity per
    period -- see this module's BUG FOUND docstring), MULTI_SHOT_TOLERANCE_MINUTES for
    "12h" (two opportunities per day, but each individually shows the same congestion
    pattern -- see the FOLLOW-UP docstring note), DEFAULT_TOLERANCE_MINUTES for every
    other timeframe (several opportunities per period, so a narrower window is
    fine)."""
    now_utc = _require_utc(now)

    if timeframe == "1week":
        effective_tolerance = tolerance_minutes if tolerance_minutes is not None else SINGLE_SHOT_TOLERANCE_MINUTES
        if now_utc.weekday() != WEEKLY_CLOSE_WEEKDAY:
            return False
        minutes_since_boundary = (now_utc.hour - WEEKLY_CLOSE_HOUR_UTC) * 60 + now_utc.minute
        return 0 <= minutes_since_boundary < effective_tolerance

    if timeframe == "1h":
        effective_tolerance = tolerance_minutes if tolerance_minutes is not None else DEFAULT_TOLERANCE_MINUTES
        return now_utc.minute < effective_tolerance

    hours = HOURS_PER_TIMEFRAME.get(timeframe)
    if hours is None:
        raise ValueError(f"unsupported timeframe for boundary check: {timeframe!r}")
    if hours == 24:
        default_tolerance = SINGLE_SHOT_TOLERANCE_MINUTES
    elif hours == 12:
        default_tolerance = MULTI_SHOT_TOLERANCE_MINUTES
    else:
        default_tolerance = DEFAULT_TOLERANCE_MINUTES
    effective_tolerance = tolerance_minutes if tolerance_minutes is not None else default_tolerance
    boundary_interval_minutes = hours * 60
    minutes_since_midnight = now_utc.hour * 60 + now_utc.minute
    offset = minutes_since_midnight % boundary_interval_minutes
    return offset < effective_tolerance


def daily_time_due(hour_utc: int, now: datetime, tolerance_minutes: int = SINGLE_SHOT_TOLERANCE_MINUTES) -> bool:
    """True if `now` falls within `tolerance_minutes` after `hour_utc:00` UTC on any
    day — used for the once-daily News Sentiment run, which isn't tied to a candle close
    at all.

    Like "24h"/"1week" in candle_boundary_due, this gate has zero same-day redundancy --
    missing the window costs the entire day -- so it defaults to
    SINGLE_SHOT_TOLERANCE_MINUTES rather than DEFAULT_TOLERANCE_MINUTES (see this
    module's FOLLOW-UP 2026-07-29 docstring note)."""
    now_utc = _require_utc(now)
    minutes_since_boundary = (now_utc.hour - hour_utc) * 60 + now_utc.minute
    return 0 <= minutes_since_boundary < tolerance_minutes
