from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_regime_scaled_risk_report import COMPARISONS, format_report, run_report


def _trend_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(280):
        price *= 1.0015 if i % 5 != 0 else 0.999
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price, "high": price * 1.015, "low": price * 0.97, "close": price, "volume": 100.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunReportOfflineTest(unittest.TestCase):
    def test_produces_a_row_per_comparison_with_v1_and_v2(self) -> None:
        history = _trend_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BNB", interval="12h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            results = run_report()

        self.assertEqual(len(results), len(COMPARISONS))
        for row in results:
            if "error" in row:
                continue
            self.assertEqual(len(row["variants"]), 2)
            labels = {v["label"] for v in row["variants"]}
            self.assertIn("v1 (fixed risk)", labels)
            self.assertIn("v2 (regime-scaled risk)", labels)

    def test_format_report_runs_without_error(self) -> None:
        history = _trend_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BNB", interval="12h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            results = run_report()

        text = format_report(results)
        self.assertIsInstance(text, str)

    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            with patch.object(MarketDataClient, "load_daily", side_effect=MarketDataUnavailableError("no data")):
                results = run_report()

        for row in results:
            self.assertIn("error", row)


if __name__ == "__main__":
    unittest.main()
