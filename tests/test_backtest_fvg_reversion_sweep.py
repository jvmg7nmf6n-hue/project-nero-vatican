from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_fvg_reversion_sweep import ASSETS, TIMEFRAMES, format_report, run_report

HOUR_MS = 3_600_000


def _row(close_time: int, high: float, low: float) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": (high + low) / 2,
        "volume": 10.0,
    }


def _uptrend_with_gap_and_touch(n_warmup: int = 260) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(n_warmup):
        price += 0.3
        rows.append(_row(close_time, high=price + 1, low=price - 1))
        close_time += HOUR_MS
    last = price
    anchor_high = last + 2
    rows.append(_row(close_time, high=anchor_high, low=last - 1))
    close_time += HOUR_MS
    rows.append(_row(close_time, high=last + 20, low=last + 15))  # filler, raised to avoid cascade
    close_time += HOUR_MS
    rows.append(_row(close_time, high=last + 30, low=last + 22))  # gap forms
    close_time += HOUR_MS
    rows.append(_row(close_time, high=last + 24, low=anchor_high + 0.5))  # touches the zone
    close_time += HOUR_MS
    for i in range(60):
        level = last + 25 + i
        rows.append(_row(close_time, high=level + 1, low=level - 1))
        close_time += HOUR_MS
    return pd.DataFrame(rows)


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset in ASSETS:
        return MarketDataResult(prices=_uptrend_with_gap_and_touch(), source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


class RunReportOfflineTest(unittest.TestCase):
    """The full sweep does a real bootstrap + random-entry baseline per half per
    (asset, timeframe) — computed ONCE in setUpClass and reused across assertions."""

    @classmethod
    def setUpClass(cls) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            cls.results = run_report()

    def test_produces_a_row_per_asset_per_timeframe(self) -> None:
        self.assertEqual(len(self.results), len(ASSETS) * len(TIMEFRAMES))

    def test_each_row_has_a_verdict_and_full_stat_shape(self) -> None:
        valid_verdicts = {"SURVIVED", "PROMISING-WATCHLIST", "DIED"}
        for row in self.results:
            if "error" in row:
                continue
            self.assertIn(row["verdict"], valid_verdicts)
            for split_name in ("train", "test"):
                stats = row[split_name]
                self.assertIn("ci", stats)
                self.assertIn("baseline", stats)
                self.assertIn("expectancy_r", stats)

    def test_format_report_runs_without_error_and_mentions_every_asset(self) -> None:
        text = format_report(self.results)
        for asset in ASSETS:
            self.assertIn(asset, text)


class FetchFailureTest(unittest.TestCase):
    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            results = run_report()

        for row in results:
            self.assertIn("error", row)


if __name__ == "__main__":
    unittest.main()
