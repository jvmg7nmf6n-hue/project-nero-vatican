from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_short_momentum_sweep import (
    MIN_SAMPLE_SIZE,
    find_positive_both_halves,
    format_consolidated_table,
    format_positive_both_halves_summary,
    run_sweep,
)


def _downtrend_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 200.0
    for i in range(230):
        price -= 0.3
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price, "high": price + 4.0, "low": price - 4.0, "close": price, "volume": 100.0,
            }
        )
        close_time += 3_600_000
    for _ in range(15):
        price *= 0.95
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price, "high": price * 1.01, "low": price * 0.98, "close": price, "volume": 100.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunSweepOfflineTest(unittest.TestCase):
    def test_produces_one_row_per_asset_timeframe(self) -> None:
        history = _downtrend_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="4h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            rows = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset"], "BTC")
        for split in ("full", "train", "test"):
            self.assertIn("trades", rows[0][split])

    def test_skipped_fetch_is_reported(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            rows = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertIn("skip_reason", rows[0]["full"])


class FindPositiveBothHalvesTest(unittest.TestCase):
    def _row(self, train_n, train_expr, test_n, test_expr) -> dict[str, object]:
        base = {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True}
        return {
            "asset": "BTC", "timeframe": "4h", "strategy": "SHORT_MOMENTUM",
            "full": dict(base),
            "train": {**base, "trades": train_n, "expectancy_r": train_expr},
            "test": {**base, "trades": test_n, "expectancy_r": test_expr},
        }

    def test_qualifies_when_both_halves_positive_with_adequate_sample(self) -> None:
        rows = [self._row(25, 0.1, 30, 0.2)]
        self.assertEqual(len(find_positive_both_halves(rows)), 1)

    def test_rejects_when_sample_too_small(self) -> None:
        rows = [self._row(10, 0.5, 30, 0.2)]
        self.assertEqual(find_positive_both_halves(rows), [])

    def test_rejects_when_either_half_negative(self) -> None:
        rows = [self._row(25, 0.1, 30, -0.1)]
        self.assertEqual(find_positive_both_halves(rows), [])


class FormattingTest(unittest.TestCase):
    def test_consolidated_table_includes_asset_and_flags_low_sample(self) -> None:
        rows = [
            {
                "asset": "BTC", "timeframe": "4h", "strategy": "SHORT_MOMENTUM (short-momentum-v1.0.0)",
                "full": {"trades": 5, "win_rate": 0.4, "expectancy_r": 0.1, "profit_factor": 1.1, "below_min_sample": True},
                "train": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.2, "profit_factor": 1.5, "below_min_sample": False},
                "test": {"trades": 2, "win_rate": 0.0, "expectancy_r": -0.5, "profit_factor": 0.0, "below_min_sample": True},
            }
        ]
        table = format_consolidated_table(rows)
        self.assertIn("BTC", table)
        self.assertIn("*", table)

    def test_summary_reports_none_when_nothing_qualifies(self) -> None:
        self.assertIn("None.", format_positive_both_halves_summary([]))


if __name__ == "__main__":
    unittest.main()
