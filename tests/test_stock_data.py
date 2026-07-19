from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.stock_data import (
    CANDLE_COLUMNS,
    StockDataUnavailableError,
    fetch_stock_ohlcv,
    resample_1h_to_4h_market_hours_aware,
)


def _rth_day_hourly_rows(date_str: str, base_price: float = 100.0) -> list[dict]:
    """7 hourly bars for one RTH session (09:30-16:00 America/New_York), matching the
    empirically-confirmed real yfinance shape (docs/stock_data_calibration_audit.md):
    09:30,10:30,11:30,12:30,13:30,14:30,15:30 open times."""
    ts = pd.Timestamp(f"{date_str} 09:30:00", tz="America/New_York")
    rows = []
    for i in range(7):
        open_time_utc = ts.tz_convert("UTC")
        close_ms = int(open_time_utc.timestamp() * 1000) + 3_600_000
        close = base_price + i
        rows.append(
            {
                "date": pd.Timestamp(close_ms, unit="ms", tz="UTC"),
                "open_time": int(open_time_utc.timestamp() * 1000),
                "close_time": close_ms,
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
            }
        )
        ts += pd.Timedelta(hours=1)
    return rows


class TickerResolutionTest(unittest.TestCase):
    def test_empty_response_raises_stock_data_unavailable_not_silently_substituted(self) -> None:
        with patch("nero_core.data_sources.stock_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame()
            with self.assertRaises(StockDataUnavailableError):
                fetch_stock_ohlcv("SQ", "1day", sleep_fn=lambda _s: None)

    def test_fully_bogus_ticker_also_raises(self) -> None:
        with patch("nero_core.data_sources.stock_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.side_effect = Exception("404 not found")
            with self.assertRaises(StockDataUnavailableError):
                fetch_stock_ohlcv("NOTAREALTICKER", "1day", sleep_fn=lambda _s: None)


class RetryBehaviorTest(unittest.TestCase):
    def test_transient_empty_response_retries_then_succeeds(self) -> None:
        good = pd.DataFrame(
            {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5], "Volume": [500.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-07-15", tz="America/New_York")], name="Date"),
        )
        call_count = {"n": 0}

        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return pd.DataFrame()
            return good

        sleeps: list[float] = []
        with patch("nero_core.data_sources.stock_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.side_effect = _side_effect
            result = fetch_stock_ohlcv("AAPL", "1day", sleep_fn=sleeps.append)

        self.assertEqual(call_count["n"], 3)
        self.assertEqual(sleeps, [2.0, 5.0])
        self.assertEqual(len(result.prices), 1)


class NativeFetchTest(unittest.TestCase):
    def test_1day_fetch_produces_millisecond_precision_close_time_and_correct_columns(self) -> None:
        history = pd.DataFrame(
            {"Open": [100.0, 101.0], "High": [102.0, 103.0], "Low": [99.0, 100.0], "Close": [101.0, 102.0], "Volume": [1000.0, 1100.0]},
            index=pd.DatetimeIndex(
                [pd.Timestamp("2026-07-14", tz="America/New_York"), pd.Timestamp("2026-07-15", tz="America/New_York")],
                name="Date",
            ),
        )
        with patch("nero_core.data_sources.stock_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = history
            result = fetch_stock_ohlcv("SPY", "1day")

        self.assertEqual(list(result.prices.columns), CANDLE_COLUMNS)
        self.assertEqual(len(result.prices), 2)
        # A correct ms-precision epoch for 2026-07-15 must be a 13-digit number, not a
        # ~10-digit second-precision or ~6559-scale nanosecond-misread value (the exact
        # bug class fixed for GOLD/SILVER/PLATINUM in market_data.py).
        self.assertEqual(len(str(int(result.prices["close_time"].iloc[-1]))), 13)


class Resample4hMarketHoursAwareTest(unittest.TestCase):
    def test_one_complete_4h_bar_per_session_with_summed_volume(self) -> None:
        hourly = pd.DataFrame(_rth_day_hourly_rows("2026-07-15"))

        resampled = resample_1h_to_4h_market_hours_aware(hourly)

        self.assertEqual(len(resampled), 1)  # 7 bars -> one complete 4-bar group, 3 dropped
        row = resampled.iloc[0]
        self.assertEqual(row["open"], hourly.iloc[0]["open"])
        self.assertEqual(row["close"], hourly.iloc[3]["close"])
        self.assertEqual(row["high"], hourly.iloc[0:4]["high"].max())
        self.assertEqual(row["low"], hourly.iloc[0:4]["low"].min())
        self.assertEqual(row["volume"], hourly.iloc[0:4]["volume"].sum())

    def test_groups_never_span_two_different_trading_days(self) -> None:
        day1 = _rth_day_hourly_rows("2026-07-15")
        day2 = _rth_day_hourly_rows("2026-07-16", base_price=200.0)
        hourly = pd.DataFrame(day1 + day2)

        resampled = resample_1h_to_4h_market_hours_aware(hourly)

        # 2 sessions x 1 complete 4h bar each = 2 bars, never a bar mixing day1/day2 closes.
        self.assertEqual(len(resampled), 2)
        self.assertLess(resampled.iloc[0]["close"], 150.0)
        self.assertGreaterEqual(resampled.iloc[1]["close"], 200.0)

    def test_a_missing_session_day_holiday_is_simply_absent_not_bridged(self) -> None:
        # 2026-11-26 (Thanksgiving) is deliberately absent, simulating a market holiday —
        # the resampler must not merge the day before/after across the gap.
        day1 = _rth_day_hourly_rows("2026-11-25")
        day3 = _rth_day_hourly_rows("2026-11-27", base_price=300.0)
        hourly = pd.DataFrame(day1 + day3)

        resampled = resample_1h_to_4h_market_hours_aware(hourly)

        self.assertEqual(len(resampled), 2)
        self.assertLess(resampled.iloc[0]["close"], 150.0)
        self.assertGreaterEqual(resampled.iloc[1]["close"], 300.0)

    def test_empty_input_returns_empty_frame_with_correct_columns(self) -> None:
        result = resample_1h_to_4h_market_hours_aware(pd.DataFrame(columns=CANDLE_COLUMNS))
        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), CANDLE_COLUMNS)

    def test_4h_fetch_delegates_to_1h_and_resamples(self) -> None:
        day1 = _rth_day_hourly_rows("2026-07-15")
        history = pd.DataFrame(
            {
                "Open": [r["open"] for r in day1],
                "High": [r["high"] for r in day1],
                "Low": [r["low"] for r in day1],
                "Close": [r["close"] for r in day1],
                "Volume": [r["volume"] for r in day1],
            },
            index=pd.DatetimeIndex(
                [pd.Timestamp("2026-07-15 09:30:00", tz="America/New_York") + pd.Timedelta(hours=i) for i in range(7)],
                name="Datetime",
            ),
        )
        with patch("nero_core.data_sources.stock_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = history
            result = fetch_stock_ohlcv("SPY", "4h")

        self.assertEqual(result.timeframe, "4h")
        self.assertEqual(len(result.prices), 1)
        self.assertIn("RESAMPLED", result.source)


if __name__ == "__main__":
    unittest.main()
