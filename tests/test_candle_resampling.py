from __future__ import annotations

import unittest

import pandas as pd

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid


def _hourly_candles(n: int, start_ms: int = 0) -> pd.DataFrame:
    """n consecutive, gap-free 1h candles starting at start_ms (UTC epoch ms), with a
    distinct, checkable open/high/low/close/volume per hour: open=i, high=i+0.5,
    low=i-0.5, close=i+0.25, volume=i (so aggregation results are hand-verifiable)."""
    rows = []
    open_time = start_ms
    for i in range(n):
        close_time = open_time + 3_600_000
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": open_time,
                "close_time": close_time,
                "open": float(i),
                "high": float(i) + 0.5,
                "low": float(i) - 0.5,
                "close": float(i) + 0.25,
                "volume": float(i),
            }
        )
        open_time = close_time
    return pd.DataFrame(rows)


class ResampleHourlyToGridTest(unittest.TestCase):
    def test_offset_zero_produces_standard_midnight_aligned_bins(self) -> None:
        # 48 hours starting exactly at 2024-01-01 00:00 UTC -> 4 clean 12h bins at offset 0.
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(48, start_ms)

        grid = resample_hourly_to_grid(hourly, target_hours=12, offset_hours=0)

        self.assertEqual(len(grid), 4)
        first_close = pd.Timestamp(grid["close_time"].iloc[0], unit="ms", tz="UTC")
        self.assertEqual(first_close.hour, 12)
        self.assertEqual(first_close.minute, 0)

    def test_offset_shifts_bin_boundaries_by_the_requested_hours(self) -> None:
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(60, start_ms)

        grid = resample_hourly_to_grid(hourly, target_hours=12, offset_hours=3)

        # Bin edges should fall at 03:00 and 15:00 UTC, not 00:00/12:00.
        close_hours = sorted({pd.Timestamp(ct, unit="ms", tz="UTC").hour for ct in grid["close_time"]})
        self.assertEqual(close_hours, [3, 15])

    def test_ohlcv_aggregation_is_open_first_high_max_low_min_close_last_volume_sum(self) -> None:
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(12, start_ms)  # hours 0..11 -> exactly one 12h bin at offset 0

        grid = resample_hourly_to_grid(hourly, target_hours=12, offset_hours=0)

        self.assertEqual(len(grid), 1)
        bin_row = grid.iloc[0]
        self.assertAlmostEqual(bin_row["open"], 0.0)  # first candle's open (i=0)
        self.assertAlmostEqual(bin_row["high"], 11.5)  # max high across i=0..11 (i=11 -> 11.5)
        self.assertAlmostEqual(bin_row["low"], -0.5)  # min low across i=0..11 (i=0 -> -0.5)
        self.assertAlmostEqual(bin_row["close"], 11.25)  # last candle's close (i=11 -> 11.25)
        self.assertAlmostEqual(bin_row["volume"], sum(range(12)))  # SUM of all 12 hourly volumes = 66

    def test_incomplete_leading_and_trailing_bins_are_dropped(self) -> None:
        # 27 hours starting at 00:00 UTC with offset=3h: first bin (00:00-02:59, 3 rows)
        # and last bin (27:00 onward, incomplete) must both be dropped, keeping only the
        # two full 12h bins in between.
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(27, start_ms)

        grid = resample_hourly_to_grid(hourly, target_hours=12, offset_hours=3)

        self.assertEqual(len(grid), 2)

    def test_gap_in_source_candles_drops_the_straddling_bin(self) -> None:
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(24, start_ms)
        # Remove one candle from the middle of the first 12h bin (offset 0) to simulate a
        # gap in the underlying live fetch — that bin must never be silently fabricated.
        hourly = hourly.drop(index=5).reset_index(drop=True)

        grid = resample_hourly_to_grid(hourly, target_hours=12, offset_hours=0)

        # Only the second (intact) 12h bin should survive; the gapped first bin is dropped.
        self.assertEqual(len(grid), 1)
        surviving_close = pd.Timestamp(grid["close_time"].iloc[0], unit="ms", tz="UTC")
        self.assertEqual(surviving_close.hour, 0)  # the 12:00-23:59 bin closes at hour 0 the next day

    def test_2h_grid_at_1h_offset(self) -> None:
        start_ms = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        hourly = _hourly_candles(10, start_ms)

        grid = resample_hourly_to_grid(hourly, target_hours=2, offset_hours=1)

        # Bins at [1,2],[3,4],[5,6],[7,8] UTC hours; [0] and [9] are leading/trailing partials.
        self.assertEqual(len(grid), 4)
        close_hours = [pd.Timestamp(ct, unit="ms", tz="UTC").hour for ct in grid["close_time"]]
        self.assertEqual(close_hours, [3, 5, 7, 9])

    def test_empty_input_returns_empty_frame(self) -> None:
        empty = pd.DataFrame(columns=["date", "open_time", "close_time", "open", "high", "low", "close", "volume"])

        grid = resample_hourly_to_grid(empty, target_hours=12, offset_hours=3)

        self.assertTrue(grid.empty)


if __name__ == "__main__":
    unittest.main()
