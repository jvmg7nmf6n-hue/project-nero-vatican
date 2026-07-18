from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.funding_data import FundingDataUnavailableError, FundingHistoryResult
from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_funding_extreme_sweep import FUNDING_TIMEFRAMES, format_report, run_report

EIGHT_HOURS_MS = 8 * 3_600_000
START_MS = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)  # 8h/24h-grid-aligned epoch


def _hourly_candles(n: int, start_ms: int = START_MS) -> pd.DataFrame:
    rows = []
    open_time = start_ms
    price = 100.0
    for i in range(n):
        close_time = open_time + 3_600_000
        price *= 1.0002 if i % 11 != 0 else 0.999
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": open_time,
                "close_time": close_time,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.985,
                "close": price,
                "volume": 10.0,
            }
        )
        open_time = close_time
    return pd.DataFrame(rows)


def _daily_candles(n: int, start_ms: int = START_MS) -> pd.DataFrame:
    rows = []
    close_time = start_ms
    price = 100.0
    for i in range(n):
        price *= 1.0015 if i % 5 != 0 else 0.995
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 86_400_000,
                "close_time": close_time,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.98,
                "close": price,
                "volume": 100.0,
            }
        )
        close_time += 86_400_000
    return pd.DataFrame(rows)


def _funding_settlements(n: int, start_ms: int = START_MS) -> pd.DataFrame:
    """Mostly flat funding with a deep, sustained negative dip roughly a third of the
    way through — enough to plausibly trigger a real FUNDING_EXTREME entry, without
    asserting an exact trade count (this test is plumbing-level, not a strategy-logic
    test — that's tests/test_funding_extreme.py's job)."""
    times = [start_ms + i * EIGHT_HOURS_MS for i in range(n)]
    rates = []
    for i in range(n):
        if n // 3 <= i < n // 3 + 6:
            rates.append(-0.02)
        else:
            rates.append(0.0001 if i % 2 == 0 else -0.0001)
    return pd.DataFrame(
        {
            "settlement_time": times,
            "settlement_date": pd.to_datetime(times, unit="ms", utc=True),
            "funding_rate": rates,
        }
    )


N_HOURS = 150 * 24  # 150 days of hourly candles -> 450 8h candles
N_SETTLEMENTS = 150 * 3  # matches the 8h candle count exactly
N_DAYS = 150


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset in ("BTC", "ETH", "SOL", "BNB"):
        return MarketDataResult(prices=_hourly_candles(N_HOURS), source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


def _fake_load_daily(asset, days=365, twelve_data_api_key=None):
    if asset in ("BTC", "ETH", "SOL", "BNB"):
        return MarketDataResult(prices=_daily_candles(N_DAYS), source="test-fixture", asset=asset, interval="1d")
    raise MarketDataUnavailableError(f"no fixture for {asset}")


def _fake_load_funding_history(asset, cache_dir=None, use_cache=True, timeout_seconds=8):
    return FundingHistoryResult(
        asset=asset, settlements=_funding_settlements(N_SETTLEMENTS), source="test-fixture", from_cache=False
    )


class RunReportOfflineTest(unittest.TestCase):
    """run_report() does a real bootstrap (5000 iterations) + random-entry baseline
    (200 runs) per half per (asset, timeframe) — 8 configs x 2 halves. Computed ONCE in
    setUpClass and reused across every assertion in this class; each test method
    re-invoking it independently would multiply an already-nontrivial cost by the
    number of tests for no added coverage."""

    @classmethod
    def setUpClass(cls) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), \
             patch.object(MarketDataClient, "load_daily", side_effect=_fake_load_daily), \
             patch("tools.backtest_funding_extreme_sweep.load_funding_history", side_effect=_fake_load_funding_history):
            cls.results = run_report()

    def test_produces_a_row_per_asset_per_timeframe(self) -> None:
        self.assertEqual(len(self.results), 4 * len(FUNDING_TIMEFRAMES))

    def test_each_successful_row_has_train_test_ci_and_baseline(self) -> None:
        for row in self.results:
            if "error" in row:
                continue
            for split_name in ("train", "test"):
                stats = row[split_name]
                self.assertIn("ci", stats)
                self.assertIn("baseline", stats)
                self.assertIn("expectancy_r", stats)
            self.assertIn("funding_depth", row)

    def test_format_report_runs_without_error_and_mentions_every_asset(self) -> None:
        text = format_report(self.results)
        for asset in ("BTC", "ETH", "SOL", "BNB"):
            self.assertIn(asset, text)

    def test_price_fetch_failure_is_reported_as_skipped(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")), \
             patch.object(MarketDataClient, "load_daily", side_effect=MarketDataUnavailableError("no data")):
            results = run_report()

        for row in results:
            self.assertIn("error", row)
            self.assertIn("price data", row["error"])

    def test_funding_fetch_failure_is_reported_as_skipped(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), \
             patch.object(MarketDataClient, "load_daily", side_effect=_fake_load_daily), \
             patch(
                 "tools.backtest_funding_extreme_sweep.load_funding_history",
                 side_effect=FundingDataUnavailableError("no funding data"),
             ):
            results = run_report()

        for row in results:
            self.assertIn("error", row)
            self.assertIn("funding data", row["error"])


if __name__ == "__main__":
    unittest.main()
