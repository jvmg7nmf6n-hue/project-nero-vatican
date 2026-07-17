from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.robustness_audit import (
    PAIRS_CONFIG,
    SINGLE_ASSET_CONFIGS,
    _bucket_stats,
    _largest_bucket_share,
    audit_trades,
    format_report,
    run_pairs_audit,
    run_single_asset_audit,
)


@dataclass
class _FakeTrade:
    r_multiple: float
    exit_close_time: int


class BucketStatsTest(unittest.TestCase):
    def test_groups_by_key_and_sums_r(self) -> None:
        trades = [_FakeTrade(r_multiple=1.0, exit_close_time=0), _FakeTrade(r_multiple=-0.5, exit_close_time=0), _FakeTrade(r_multiple=2.0, exit_close_time=0)]

        buckets = _bucket_stats(trades, lambda t: "A" if t.r_multiple > 0 else "B")

        self.assertEqual(buckets["A"]["n"], 2)
        self.assertAlmostEqual(buckets["A"]["sum_r"], 3.0)
        self.assertAlmostEqual(buckets["A"]["mean_r"], 1.5)
        self.assertEqual(buckets["B"]["n"], 1)
        self.assertAlmostEqual(buckets["B"]["sum_r"], -0.5)


class LargestBucketShareTest(unittest.TestCase):
    def test_identifies_the_dominant_positive_bucket(self) -> None:
        buckets = {"2023": {"sum_r": 10.0}, "2024": {"sum_r": 2.0}, "2025": {"sum_r": -3.0}}

        key, share = _largest_bucket_share(buckets)

        self.assertEqual(key, "2023")
        self.assertAlmostEqual(share, 10.0 / 12.0)

    def test_returns_none_when_no_positive_buckets(self) -> None:
        buckets = {"2023": {"sum_r": -1.0}, "2024": {"sum_r": -2.0}}

        key, share = _largest_bucket_share(buckets)

        self.assertIsNone(key)
        self.assertEqual(share, 0.0)

    def test_empty_buckets_returns_none(self) -> None:
        key, share = _largest_bucket_share({})

        self.assertIsNone(key)
        self.assertEqual(share, 0.0)


class AuditTradesTest(unittest.TestCase):
    def test_buckets_by_day_hour_and_year_from_exit_close_time(self) -> None:
        # 2024-01-01 00:00:00 UTC is a Monday.
        ts = int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp() * 1000)
        trades = [_FakeTrade(r_multiple=1.0, exit_close_time=ts)]

        result = audit_trades("test", trades)

        self.assertEqual(result["total_trades"], 1)
        self.assertIn("Monday", result["by_day"])
        self.assertIn(0, result["by_hour"])
        self.assertIn(2024, result["by_year"])


def _trend_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(260):
        price *= 1.002
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "open_time": close_time - 3_600_000,
                "close_time": close_time, "open": price, "high": price * 1.01, "low": price * 0.97, "close": price, "volume": 100.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunAuditsOfflineTest(unittest.TestCase):
    def test_single_asset_audit_produces_bucket_breakdowns(self) -> None:
        history = _trend_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="12h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            r = run_single_asset_audit(SINGLE_ASSET_CONFIGS[0], MarketDataClient())

        self.assertNotIn("error", r)
        self.assertIn("by_day", r)
        self.assertIn("by_hour", r)
        self.assertIn("by_year", r)

    def test_single_asset_audit_reports_skip_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            r = run_single_asset_audit(SINGLE_ASSET_CONFIGS[0], MarketDataClient())

        self.assertIn("error", r)

    def test_pairs_audit_produces_bucket_breakdowns(self) -> None:
        import math

        rows_x, rows_y = [], []
        close_time = 0
        for t in range(500):
            x = 100.0 + 15.0 * math.sin(t * 0.05)
            y = 2.0 * x + 6.0 * math.sin(t * 0.19)
            rows_x.append({"date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "open_time": close_time - 3_600_000, "close_time": close_time, "open": x, "high": x + 0.1, "low": x - 0.1, "close": x, "volume": 10.0})
            rows_y.append({"date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "open_time": close_time - 3_600_000, "close_time": close_time, "open": y, "high": y + 0.1, "low": y - 0.1, "close": y, "volume": 10.0})
            close_time += 3_600_000
        btc_result = MarketDataResult(prices=pd.DataFrame(rows_x), source="test-fixture", asset="BTC", interval="12h")
        eth_result = MarketDataResult(prices=pd.DataFrame(rows_y), source="test-fixture", asset="ETH", interval="12h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else eth_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            r = run_pairs_audit(PAIRS_CONFIG, MarketDataClient())

        self.assertNotIn("error", r)
        self.assertIn("by_year", r)


class FormatReportTest(unittest.TestCase):
    def test_runs_without_error_on_mixed_results(self) -> None:
        results = [
            {"label": "X", "error": "no data"},
            audit_trades("Y", [_FakeTrade(r_multiple=1.0, exit_close_time=int(pd.Timestamp("2024-06-01T12:00:00Z").timestamp() * 1000))]),
        ]

        text = format_report(results)

        self.assertIn("SKIPPED", text)
        self.assertIn("Concentration", text)


if __name__ == "__main__":
    unittest.main()
