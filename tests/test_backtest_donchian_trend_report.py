from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_donchian_trend_report import format_report, run_report


def _weekly_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 1000.0
    for i in range(260):
        price *= 1.003
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 7 * 86_400_000,
                "close_time": close_time,
                "open": price, "high": price * 1.02, "low": price * 0.98, "close": price, "volume": 100.0,
            }
        )
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


class RunReportOfflineTest(unittest.TestCase):
    def test_produces_donchian_and_comparison_rows(self) -> None:
        history = _weekly_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="GOLD", interval="1week")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            report = run_report()

        self.assertEqual(len(report["rows"]), 2)
        self.assertIn("DONCHIAN_TREND", report["rows"][0]["strategy"])
        self.assertIn("BREAKOUT_MOMENTUM", report["rows"][1]["strategy"])
        for row in report["rows"]:
            for split in ("full", "train", "test"):
                self.assertIn("trades", row[split])

    def test_format_report_includes_both_strategies_and_qualify_line(self) -> None:
        history = _weekly_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="GOLD", interval="1week")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            report = run_report()

        text = format_report(report)

        self.assertIn("DONCHIAN_TREND", text)
        self.assertIn("BREAKOUT_MOMENTUM", text)
        self.assertIn("positive in BOTH train and test", text)


if __name__ == "__main__":
    unittest.main()
