from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.execution.candle_schedule import candle_boundary_due, daily_time_due


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
