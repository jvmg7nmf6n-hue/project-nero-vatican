from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_bos_continuation_sweep import ASSETS, TIMEFRAMES, format_report, run_report

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def _row(close_time: int, high: float, low: float, close: float | None = None) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
        "volume": 10.0,
    }


def _uptrend_with_bos(spacing_ms: int, n_warmup: int = 230) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(n_warmup):
        price += 0.3
        rows.append(_row(close_time, high=price + 1, low=price - 1))
        close_time += spacing_ms
    last = price
    rows += [
        _row(close_time, high=last + 2, low=last - 1),
        _row(close_time + spacing_ms, high=last + 3, low=last),
        _row(close_time + 2 * spacing_ms, high=last + 15, low=last + 5, close=last + 8),  # swing high candidate
        _row(close_time + 3 * spacing_ms, high=last + 12, low=last + 6),
        _row(close_time + 4 * spacing_ms, high=last + 11, low=last + 5),
        _row(close_time + 5 * spacing_ms, high=last + 10, low=last + 4),
        _row(close_time + 6 * spacing_ms, high=last + 9, low=last + 3),
        _row(close_time + 7 * spacing_ms, high=last + 8, low=last + 2, close=last + 20),  # confirms + breaks
    ]
    close_time += 8 * spacing_ms
    for i in range(40):
        level = last + 21 + i
        rows.append(_row(close_time, high=level + 1, low=level - 1))
        close_time += spacing_ms
    return pd.DataFrame(rows)


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset in ASSETS:
        spacing = {"4h": 4 * HOUR_MS, "12h": 12 * HOUR_MS}.get(interval, HOUR_MS)
        return MarketDataResult(prices=_uptrend_with_bos(spacing), source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


def _fake_load_daily(asset, days=365, twelve_data_api_key=None):
    if asset in ASSETS:
        return MarketDataResult(prices=_uptrend_with_bos(DAY_MS), source="test-fixture", asset=asset, interval="1d")
    raise MarketDataUnavailableError(f"no fixture for {asset}")


class RunReportOfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday), \
             patch.object(MarketDataClient, "load_daily", side_effect=_fake_load_daily):
            cls.results = run_report()

    def test_produces_a_row_per_asset_per_timeframe(self) -> None:
        self.assertEqual(len(self.results), len(ASSETS) * len(TIMEFRAMES))

    def test_each_row_has_a_verdict_and_stop_type_counts(self) -> None:
        valid_verdicts = {"SURVIVED", "PROMISING-WATCHLIST", "DIED"}
        for row in self.results:
            if "error" in row:
                continue
            self.assertIn(row["verdict"], valid_verdicts)
            for split_name in ("train", "test"):
                stats = row[split_name]
                self.assertIn("structural_stop_count", stats)
                self.assertIn("capped_stop_count", stats)
                self.assertEqual(stats["structural_stop_count"] + stats["capped_stop_count"], stats["trades"])

    def test_format_report_runs_without_error_and_mentions_stop_types(self) -> None:
        text = format_report(self.results)
        self.assertIn("structural=", text)
        self.assertIn("capped(3xATR)=", text)


class FetchFailureTest(unittest.TestCase):
    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")), \
             patch.object(MarketDataClient, "load_daily", side_effect=MarketDataUnavailableError("no data")):
            results = run_report()

        for row in results:
            self.assertIn("error", row)


if __name__ == "__main__":
    unittest.main()
