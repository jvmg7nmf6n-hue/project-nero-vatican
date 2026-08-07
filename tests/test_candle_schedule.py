from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.execution.candle_schedule import (
    DEFAULT_TOLERANCE_MINUTES,
    MULTI_SHOT_TOLERANCE_MINUTES,
    SINGLE_SHOT_TOLERANCE_MINUTES,
    candle_boundary_due,
    daily_time_due,
)


def _utc(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class CandleBoundaryDueTest(unittest.TestCase):
    def test_12h_due_right_at_midnight_utc(self) -> None:
        self.assertTrue(candle_boundary_due("12h", _utc(2026, 7, 17, 0, 5)))

    def test_12h_due_right_at_noon_utc(self) -> None:
        self.assertTrue(candle_boundary_due("12h", _utc(2026, 7, 17, 12, 10)))

    def test_12h_not_due_mid_window(self) -> None:
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 6, 0)))

    def test_12h_not_due_just_outside_tolerance(self) -> None:
        # MULTI_SHOT_TOLERANCE_MINUTES (150) -- 0:45 is well inside it now; use a time
        # genuinely past the widened window instead (well short of the 12:00 boundary).
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 3, 0)))

    def test_24h_due_only_near_midnight(self) -> None:
        self.assertTrue(candle_boundary_due("24h", _utc(2026, 7, 17, 0, 0)))
        self.assertFalse(candle_boundary_due("24h", _utc(2026, 7, 17, 12, 0)))

    def test_1week_due_only_on_monday_near_midnight_utc(self) -> None:
        # 2026-07-13 is a Monday. CC-1 DIRECTIVE FIX (2026-08-07): was Friday
        # (2026-07-17) -- confirmed via real execution_log data across all 4
        # affected configs (GOLD, EUR/USD, GBP/USD, USD/JPY) that Twelve
        # Data's real native "1week" bar for these instruments closes/labels
        # on Monday, not Friday. See candle_schedule.py's own updated
        # WEEKLY_CLOSE_WEEKDAY comment for the full trace.
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 13, 0, 10)))

    def test_1week_not_due_on_sunday(self) -> None:
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 12, 0, 10)))

    def test_1week_not_due_on_monday_afternoon(self) -> None:
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 13, 14, 0)))

    # Regression tests for a real incident (2026-07-28 PEAD zero-signal investigation):
    # "24h" and "1week" get only ONE boundary opportunity per period, so their default
    # tolerance must survive realistic GitHub Actions `schedule` delay, not just the
    # generic 40-minute window sized for timeframes with several daily opportunities.
    # Querying this project's own execution_metadata confirmed the live scheduler's
    # actual first-run-of-the-day timestamps landed at (among others) 00:59, 01:04,
    # 01:07, 01:21, 01:27, 01:29, 01:30, 01:45 UTC -- every one of which the OLD
    # 40-minute default would have rejected, which is exactly how PEAD (and GOLD/
    # 1week/BREAKOUT_MOMENTUM, this project's own flagship SURVIVOR) went 10+ days
    # without a single "24h"/"1week" evaluation.
    def test_24h_due_at_actually_observed_delayed_run_times(self) -> None:
        for hour, minute in ((0, 59), (1, 4), (1, 7), (1, 21), (1, 27), (1, 29), (1, 30), (1, 45)):
            with self.subTest(hour=hour, minute=minute):
                self.assertTrue(candle_boundary_due("24h", _utc(2026, 7, 17, hour, minute)))

    def test_1week_due_at_actually_observed_delayed_run_time_on_monday(self) -> None:
        # 2026-07-13 and 2026-07-20 are both Mondays.
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 13, 1, 30)))
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 20, 1, 30)))

    def test_24h_and_1week_still_not_due_well_outside_the_widened_window(self) -> None:
        # SINGLE_SHOT_TOLERANCE_MINUTES is generous, not unlimited -- confirms the
        # widened window doesn't silently degrade into "always due".
        self.assertFalse(candle_boundary_due("24h", _utc(2026, 7, 17, 6, 0)))
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 13, 6, 0)))

    def test_1h_default_tolerance_is_unaffected_by_the_single_shot_widening(self) -> None:
        # "1h" gets 24 opportunities/day -- it must keep the narrow default, not
        # inherit SINGLE_SHOT_TOLERANCE_MINUTES meant only for "24h"/"1week".
        self.assertFalse(candle_boundary_due("1h", _utc(2026, 7, 17, 9, DEFAULT_TOLERANCE_MINUTES)))
        self.assertTrue(candle_boundary_due("1h", _utc(2026, 7, 17, 9, DEFAULT_TOLERANCE_MINUTES - 1)))

    def test_single_shot_tolerance_is_wider_than_the_generic_default(self) -> None:
        # Documents the actual relationship the fix depends on -- if someone
        # "simplifies" these back to one constant, this fails loudly.
        self.assertGreater(SINGLE_SHOT_TOLERANCE_MINUTES, DEFAULT_TOLERANCE_MINUTES)

    # Regression tests for a follow-up incident (2026-07-29 health check first real
    # run): "12h" (BNB/TREND_PULLBACK, BTC-ETH/COINTEGRATION_PAIRS) recorded ZERO
    # signals across 143 runs -- same GitHub Actions cron-congestion pattern as the
    # 24h/1week incident above, just with "12h"'s own two-opportunity-per-day rhythm.
    # Querying execution_metadata's real run-time history confirmed the AM window
    # (after 00:00 UTC) landed 15-106 minutes late and the PM window (after 12:00 UTC)
    # landed 8-74 minutes late -- both of which the OLD 40-minute default rejected.
    def test_12h_due_at_actually_observed_delayed_run_times(self) -> None:
        for hour, minute in ((0, 15), (1, 45), (1, 46), (12, 8), (13, 14)):
            with self.subTest(hour=hour, minute=minute):
                self.assertTrue(candle_boundary_due("12h", _utc(2026, 7, 17, hour, minute)))

    def test_12h_still_not_due_well_outside_the_widened_window(self) -> None:
        # MULTI_SHOT_TOLERANCE_MINUTES is generous, not unlimited.
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 6, 0)))
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 18, 0)))

    def test_multi_shot_tolerance_is_between_default_and_single_shot(self) -> None:
        # Documents the actual relationship the fix depends on: "12h" keeps same-day
        # redundancy (unlike "24h"/"1week"), so it gets a narrower window than the
        # single-shot gates, but still much wider than the generic default.
        self.assertGreater(MULTI_SHOT_TOLERANCE_MINUTES, DEFAULT_TOLERANCE_MINUTES)
        self.assertLess(MULTI_SHOT_TOLERANCE_MINUTES, SINGLE_SHOT_TOLERANCE_MINUTES)

    def test_1h_due_near_top_of_hour(self) -> None:
        self.assertTrue(candle_boundary_due("1h", _utc(2026, 7, 17, 9, 5)))
        self.assertFalse(candle_boundary_due("1h", _utc(2026, 7, 17, 9, 45)))

    def test_unsupported_timeframe_raises(self) -> None:
        with self.assertRaises(ValueError):
            candle_boundary_due("3h", _utc(2026, 7, 17, 0, 0))

    def test_naive_datetime_raises(self) -> None:
        with self.assertRaises(ValueError):
            candle_boundary_due("12h", datetime(2026, 7, 17, 0, 0))

    def test_custom_tolerance_is_respected(self) -> None:
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 0, 5), tolerance_minutes=2))
        self.assertTrue(candle_boundary_due("12h", _utc(2026, 7, 17, 0, 5), tolerance_minutes=10))


class DailyTimeDueTest(unittest.TestCase):
    def test_due_right_at_the_hour(self) -> None:
        self.assertTrue(daily_time_due(19, _utc(2026, 7, 17, 19, 5)))

    def test_not_due_far_from_the_hour(self) -> None:
        self.assertFalse(daily_time_due(19, _utc(2026, 7, 17, 10, 0)))

    def test_due_on_any_day_of_week(self) -> None:
        self.assertTrue(daily_time_due(19, _utc(2026, 7, 18, 19, 0)))

    def test_naive_datetime_raises(self) -> None:
        with self.assertRaises(ValueError):
            daily_time_due(19, datetime(2026, 7, 17, 19, 0))

    # Regression tests for the same 2026-07-29 follow-up incident: NEWS_SENTIMENT's
    # daily_time_due(hour_utc=19, ...) gate was missing its own 48h health-check
    # staleness threshold by 77.5h. Like "24h"/"1week", this gate has ZERO same-day
    # redundancy, so it now defaults to SINGLE_SHOT_TOLERANCE_MINUTES instead of
    # DEFAULT_TOLERANCE_MINUTES. Real execution_metadata history showed 18-76 minutes
    # of steady-state delay plus one 229-minute outlier on 2026-07-17 (the workflow's
    # first-ever calendar day).
    def test_due_at_actually_observed_delayed_run_times(self) -> None:
        for hour, minute in ((19, 18), (19, 45), (20, 16), (20, 35)):
            with self.subTest(hour=hour, minute=minute):
                self.assertTrue(daily_time_due(19, _utc(2026, 7, 17, hour, minute)))

    def test_due_at_the_observed_229_minute_startup_outlier(self) -> None:
        self.assertTrue(daily_time_due(19, _utc(2026, 7, 17, 22, 48)))

    def test_still_not_due_well_outside_the_widened_window(self) -> None:
        self.assertFalse(daily_time_due(19, _utc(2026, 7, 17, 23, 30)))

    def test_default_tolerance_is_now_single_shot(self) -> None:
        # Documents the actual relationship the fix depends on -- if someone
        # "simplifies" the default parameter back to DEFAULT_TOLERANCE_MINUTES, this
        # fails loudly.
        self.assertGreater(SINGLE_SHOT_TOLERANCE_MINUTES, DEFAULT_TOLERANCE_MINUTES)
        self.assertTrue(daily_time_due(19, _utc(2026, 7, 17, 22, 0)))


if __name__ == "__main__":
    unittest.main()
