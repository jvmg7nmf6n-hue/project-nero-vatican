from __future__ import annotations

import unittest
from unittest.mock import ANY, MagicMock

import pandas as pd

from nero_core.data_sources.market_data import CANDLE_COLUMNS, MarketDataResult
from tools.timeframe_data import fetch_timeframe_candles


def _hourly_candles(n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        open_time = i * 3_600_000
        close_time = open_time + 3_600_000
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": open_time,
                "close_time": close_time,
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows, columns=CANDLE_COLUMNS)


class FetchTimeframeCandlesYFinanceMetalsTest(unittest.TestCase):
    """SILVER/PLATINUM route through yfinance (Twelve Data 404s on this project's
    plan — see docs/metals_data_calibration_audit.md): only 1h and 1week are fetched
    natively, 2h/4h/12h must be resampled from a 1h fetch, mirroring GOLD's own
    12h-from-Twelve-Data-1h fallback but extended to three timeframes instead of one."""

    def test_2h_resamples_from_a_native_1h_fetch(self) -> None:
        client = MagicMock()
        client.load_intraday.return_value = MarketDataResult(_hourly_candles(20), "YFinance SI=F (continuous futures proxy, not spot) 1h candles", "SILVER", "1h")

        candles, method = fetch_timeframe_candles(client, "SILVER", "2h")

        client.load_intraday.assert_called_once_with("SILVER", interval="1h", candles=ANY)
        self.assertEqual(len(candles), 10)  # 20 1h candles -> 10 complete 2h groups
        self.assertIn("RESAMPLED", method)

    def test_4h_resamples_from_a_native_1h_fetch(self) -> None:
        client = MagicMock()
        client.load_intraday.return_value = MarketDataResult(_hourly_candles(20), "YFinance PL=F (continuous futures proxy, not spot) 1h candles", "PLATINUM", "1h")

        candles, method = fetch_timeframe_candles(client, "PLATINUM", "4h")

        self.assertEqual(len(candles), 5)  # 20 1h candles -> 5 complete 4h groups
        self.assertIn("RESAMPLED", method)

    def test_1week_is_fetched_natively_not_resampled(self) -> None:
        client = MagicMock()
        client.load_intraday.return_value = MarketDataResult(_hourly_candles(5), "YFinance SI=F (continuous futures proxy, not spot) 1week candles", "SILVER", "1week")

        candles, method = fetch_timeframe_candles(client, "SILVER", "1week")

        client.load_intraday.assert_called_once_with("SILVER", interval="1week", candles=ANY)
        self.assertIn("NATIVE", method)

    def test_24h_uses_load_daily_like_every_other_asset(self) -> None:
        client = MagicMock()
        client.load_daily.return_value = MarketDataResult(_hourly_candles(5), "YFinance SI=F (continuous futures proxy, not spot) daily candles", "SILVER", "1d")

        candles, method = fetch_timeframe_candles(client, "SILVER", "24h")

        client.load_daily.assert_called_once()
        self.assertIn("NATIVE", method)


if __name__ == "__main__":
    unittest.main()
