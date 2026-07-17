from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_compare import VARIANT_SPECS
from tools.backtest_volume_confirmed_sweep import (
    VARIANT_KEYS,
    find_positive_both_halves,
    format_consolidated_table,
    format_positive_both_halves_summary,
    format_trade_count_comparison,
    run_sweep,
)


def _breakout_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    close_time = 0
    for i in range(220):
        close = 100.0 + 0.01 * i
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "open_time": close_time - 3_600_000,
                "close_time": close_time, "open": close, "high": close + 0.2, "low": close - 0.2, "close": close,
                "volume": 100.0,
            }
        )
        close_time += 3_600_000
    price = 100.0 + 0.01 * 219
    for i in range(20):
        price *= 1.02
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "open_time": close_time - 3_600_000,
                "close_time": close_time, "open": price, "high": price * 1.01, "low": price * 0.99, "close": price,
                "volume": 500.0 if i % 2 == 0 else 50.0,  # alternating volume so both variants see some diverging entries
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunSweepOfflineTest(unittest.TestCase):
    def test_produces_two_rows_per_asset_timeframe(self) -> None:
        history = _breakout_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="4h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            rows = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(VARIANT_KEYS))
        strategies = {row["strategy"] for row in rows}
        self.assertEqual(strategies, {VARIANT_SPECS[k].label for k in VARIANT_KEYS})

    def test_skipped_fetch_reported_for_both_variants(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            rows = run_sweep(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(VARIANT_KEYS))
        for row in rows:
            self.assertIn("skip_reason", row["full"])


class FormattingTest(unittest.TestCase):
    def test_trade_count_comparison_reports_both_counts(self) -> None:
        rows = [
            {
                "asset": "BTC", "timeframe": "4h", "strategy": VARIANT_SPECS["breakout_momentum"].label,
                "full": {"trades": 100, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.1, "below_min_sample": False},
                "train": {"trades": 70, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.1, "below_min_sample": False},
                "test": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.1, "below_min_sample": False},
            },
            {
                "asset": "BTC", "timeframe": "4h", "strategy": VARIANT_SPECS["breakout_momentum_volume_confirmed"].label,
                "full": {"trades": 40, "win_rate": 0.55, "expectancy_r": 0.15, "profit_factor": 1.3, "below_min_sample": False},
                "train": {"trades": 28, "win_rate": 0.55, "expectancy_r": 0.15, "profit_factor": 1.3, "below_min_sample": False},
                "test": {"trades": 12, "win_rate": 0.55, "expectancy_r": 0.15, "profit_factor": 1.3, "below_min_sample": True},
            },
        ]

        text = format_trade_count_comparison(rows)

        self.assertIn("plain=  100", text)
        self.assertIn("volume-confirmed=   40", text)
        self.assertIn("TOTAL", text)

    def test_summary_reports_none_when_nothing_qualifies(self) -> None:
        self.assertIn("None.", format_positive_both_halves_summary([]))

    def test_consolidated_table_includes_both_strategies(self) -> None:
        rows = [
            {
                "asset": "BTC", "timeframe": "4h", "strategy": "BREAKOUT_MOMENTUM (breakout-momentum-v1.0.0)",
                "full": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "train": {"trades": 20, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "test": {"trades": 10, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": True},
            }
        ]
        table = format_consolidated_table(rows)
        self.assertIn("BREAKOUT_MOMENTUM", table)
        self.assertIn("*", table)


if __name__ == "__main__":
    unittest.main()
