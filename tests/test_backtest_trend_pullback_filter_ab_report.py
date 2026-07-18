from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tests.test_council_engine import _make_candle_row
from tools.backtest_trend_pullback_filter_ab_report import ASSET, format_report, run_report


def _uptrend_pullback_rally_history() -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    price = 100.0
    for i in range(220):
        price = 100.0 + 0.5 * i
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    for delta in (-8, -12, -6, 2, 5):
        price += delta
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    for _ in range(30):
        price *= 1.02
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    return pd.DataFrame(rows)


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset == ASSET:
        return MarketDataResult(prices=_uptrend_pullback_rally_history(), source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


class RunReportOfflineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            cls.result = run_report()

    def test_produces_all_three_variants(self) -> None:
        for key in ("v1", "fvg_filtered", "bos_filtered"):
            self.assertIn(key, self.result)
            for split_name in ("train", "test"):
                self.assertIn(split_name, self.result[key])

    def test_filtered_trade_counts_never_exceed_v1(self) -> None:
        for key in ("fvg_filtered", "bos_filtered"):
            for split_name in ("train", "test"):
                self.assertLessEqual(self.result[key][split_name]["trades"], self.result["v1"][split_name]["trades"])

    def test_format_report_runs_without_error_and_mentions_every_variant(self) -> None:
        text = format_report(self.result)
        self.assertIn("v1 (unfiltered)", text)
        self.assertIn("fvg-filtered", text)
        self.assertIn("bos-filtered", text)


class FetchFailureTest(unittest.TestCase):
    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            result = run_report()

        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
