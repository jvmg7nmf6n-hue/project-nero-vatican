from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.execution.candle_schedule import (
    DEFAULT_TOLERANCE_MINUTES,
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
        self.assertFalse(candle_boundary_due("12h", _utc(2026, 7, 17, 0, 45)))

    def test_24h_due_only_near_midnight(self) -> None:
        self.assertTrue(candle_boundary_due("24h", _utc(2026, 7, 17, 0, 0)))
        self.assertFalse(candle_boundary_due("24h", _utc(2026, 7, 17, 12, 0)))

    def test_1week_due_only_on_friday_near_midnight_utc(self) -> None:
        # 2026-07-17 is a Friday.
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 17, 0, 10)))

    def test_1week_not_due_on_thursday(self) -> None:
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 16, 0, 10)))

    def test_1week_not_due_on_friday_afternoon(self) -> None:
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 17, 14, 0)))

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

    def test_1week_due_at_actually_observed_delayed_run_time_on_friday(self) -> None:
        # 2026-07-17 and 2026-07-24 are both Fridays.
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 17, 1, 30)))
        self.assertTrue(candle_boundary_due("1week", _utc(2026, 7, 24, 1, 30)))

    def test_24h_and_1week_still_not_due_well_outside_the_widened_window(self) -> None:
        # SINGLE_SHOT_TOLERANCE_MINUTES is generous, not unlimited -- confirms the
        # widened window doesn't silently degrade into "always due".
        self.assertFalse(candle_boundary_due("24h", _utc(2026, 7, 17, 6, 0)))
        self.assertFalse(candle_boundary_due("1week", _utc(2026, 7, 17, 6, 0)))

    def test_1h_default_tolerance_is_unaffected_by_the_single_shot_widening(self) -> None:
        # "1h" gets 24 opportunities/day -- it must keep the narrow default, not
        # inherit SINGLE_SHOT_TOLERANCE_MINUTES meant only for "24h"/"1week".
        self.assertFalse(candle_boundary_due("1h", _utc(2026, 7, 17, 9, DEFAULT_TOLERANCE_MINUTES)))
        self.assertTrue(candle_boundary_due("1h", _utc(2026, 7, 17, 9, DEFAULT_TOLERANCE_MINUTES - 1)))

    def test_single_shot_tolerance_is_wider_than_the_generic_default(self) -> None:
        # Documents the actual relationship the fix depends on -- if someone
        # "simplifies" these back to one constant, this fails loudly.
        self.assertGreater(SINGLE_SHOT_TOLERANCE_MINUTES, DEFAULT_TOLERANCE_MINUTES)

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


if __name__ == "__main__":
    unittest.main()
