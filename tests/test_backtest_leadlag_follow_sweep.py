from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_leadlag_follow_sweep import find_positive_both_halves, format_consolidated_table, format_positive_both_halves_summary, run_sweep


def _row(close_time: int, close: float, high=None, low=None) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close, "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5, "close": close, "volume": 100.0,
    }


def _pair_history(n: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_x, rows_y = [], []
    close_time = 0
    btc_price, alt_price = 100.0, 50.0
    for i in range(n):
        btc_price += 3.0 if i % 4 == 0 else -0.2
        alt_price *= 1.01 if i % 4 == 1 else 0.999
        rows_x.append(_row(close_time, btc_price, high=btc_price + 0.5, low=btc_price - 0.5))
        rows_y.append(_row(close_time, alt_price, high=alt_price * 1.02, low=alt_price * 0.97))
        close_time += 3_600_000
    return pd.DataFrame(rows_x), pd.DataFrame(rows_y)


class RunSweepOfflineTest(unittest.TestCase):
    def test_produces_one_row_per_pair(self) -> None:
        btc_df, sol_df = _pair_history()
        btc_result = MarketDataResult(prices=btc_df, source="test-fixture", asset="BTC", interval="12h")
        sol_result = MarketDataResult(prices=sol_df, source="test-fixture", asset="SOL", interval="12h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else sol_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            rows = run_sweep([{"alt": "SOL", "timeframe": "12h", "lag": 5}], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["alt"], "SOL")
        for split in ("full", "train", "test"):
            self.assertIn("trades", rows[0][split])

    def test_skipped_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            rows = run_sweep([{"alt": "SOL", "timeframe": "12h", "lag": 5}], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertIn("skip_reason", rows[0]["full"])


class FormattingTest(unittest.TestCase):
    def test_summary_reports_none_when_nothing_qualifies(self) -> None:
        self.assertIn("None.", format_positive_both_halves_summary([]))

    def test_consolidated_table_includes_pair_and_lag(self) -> None:
        rows = [
            {
                "alt": "SOL", "timeframe": "12h", "lag": 5,
                "full": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "train": {"trades": 20, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "test": {"trades": 10, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": True},
            }
        ]
        table = format_consolidated_table(rows)
        self.assertIn("BTC-SOL", table)
        self.assertIn("*", table)


if __name__ == "__main__":
    unittest.main()
