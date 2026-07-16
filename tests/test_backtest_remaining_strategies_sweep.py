from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_compare import VARIANT_SPECS
from tools.backtest_remaining_strategies_sweep import (
    MIN_SAMPLE_SIZE,
    PAIRS_ASSET_LABEL,
    SINGLE_ASSET_VARIANT_KEYS,
    find_positive_both_halves,
    format_consolidated_table,
    format_positive_both_halves_summary,
    run_pairs_rows,
    run_single_asset_rows,
)


def _trend_history() -> pd.DataFrame:
    """Long uptrend with a pullback and recovery leg — enough to exercise
    TREND_PULLBACK and the MEAN_REVERSION-family ports without asserting exact trade
    counts (this test is about wiring/shape, not strategy edge)."""
    rows: list[dict[str, object]] = []
    close_time = 0
    price = 100.0
    for i in range(260):
        price *= 1.002
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": price,
                "high": price * 1.01,
                "low": price * 0.97,
                "close": price,
                "volume": 100.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunSingleAssetRowsOfflineTest(unittest.TestCase):
    def test_produces_one_row_per_asset_timeframe_variant(self) -> None:
        history = _trend_history()
        result = MarketDataResult(prices=history, source="test-fixture", asset="BTC", interval="4h")
        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            rows = run_single_asset_rows(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(SINGLE_ASSET_VARIANT_KEYS))
        strategies = {row["strategy"] for row in rows}
        expected = {VARIANT_SPECS[k].label for k in SINGLE_ASSET_VARIANT_KEYS}
        self.assertEqual(strategies, expected)
        for row in rows:
            for split in ("full", "train", "test"):
                self.assertIn("trades", row[split])

    def test_skipped_fetch_is_reported_for_every_variant(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            rows = run_single_asset_rows(["BTC"], ["4h"], MarketDataClient())

        self.assertEqual(len(rows), len(SINGLE_ASSET_VARIANT_KEYS))
        for row in rows:
            self.assertIn("skip_reason", row["full"])


def _cointegrated_pair_history(n: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_x: list[dict[str, object]] = []
    rows_y: list[dict[str, object]] = []
    close_time = 0
    for t in range(n):
        x = 100.0 + 15.0 * math.sin(t * 0.05)
        spread_component = 6.0 * math.sin(t * 0.19)
        y = 2.0 * x + spread_component
        rows_x.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": x, "high": x + 0.1, "low": x - 0.1, "close": x, "volume": 10.0,
            }
        )
        rows_y.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "open_time": close_time - 3_600_000,
                "close_time": close_time,
                "open": y, "high": y + 0.1, "low": y - 0.1, "close": y, "volume": 10.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows_x), pd.DataFrame(rows_y)


class RunPairsRowsOfflineTest(unittest.TestCase):
    def test_produces_one_row_per_timeframe(self) -> None:
        x_df, y_df = _cointegrated_pair_history(900)
        x_result = MarketDataResult(prices=x_df, source="test-fixture", asset="BTC", interval="4h")
        y_result = MarketDataResult(prices=y_df, source="test-fixture", asset="ETH", interval="4h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return x_result if asset == "BTC" else y_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            rows = run_pairs_rows(["4h"], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset"], PAIRS_ASSET_LABEL)
        for split in ("full", "train", "test"):
            self.assertIn("trades", rows[0][split])

    def test_skipped_when_one_leg_fails(self) -> None:
        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "ETH":
                raise MarketDataUnavailableError("no ETH data")
            x_df, _ = _cointegrated_pair_history(300)
            return MarketDataResult(prices=x_df, source="test-fixture", asset="BTC", interval=interval)

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            rows = run_pairs_rows(["4h"], MarketDataClient())

        self.assertEqual(len(rows), 1)
        self.assertIn("skip_reason", rows[0]["full"])


class FindPositiveBothHalvesTest(unittest.TestCase):
    def _row(self, train_n, train_expr, test_n, test_expr, skip=False) -> dict[str, object]:
        base = {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True}
        row = {
            "asset": "BTC", "timeframe": "4h", "strategy": "X",
            "full": dict(base),
            "train": {**base, "trades": train_n, "expectancy_r": train_expr, "below_min_sample": train_n < MIN_SAMPLE_SIZE},
            "test": {**base, "trades": test_n, "expectancy_r": test_expr, "below_min_sample": test_n < MIN_SAMPLE_SIZE},
        }
        if skip:
            row["train"]["skip_reason"] = "x"
        return row

    def test_qualifies_when_both_halves_positive_with_adequate_sample(self) -> None:
        rows = [self._row(25, 0.1, 30, 0.2)]

        qualifying = find_positive_both_halves(rows)

        self.assertEqual(len(qualifying), 1)

    def test_rejects_when_train_sample_too_small(self) -> None:
        rows = [self._row(10, 0.5, 30, 0.2)]

        self.assertEqual(find_positive_both_halves(rows), [])

    def test_rejects_when_test_expectancy_negative(self) -> None:
        rows = [self._row(25, 0.1, 30, -0.1)]

        self.assertEqual(find_positive_both_halves(rows), [])

    def test_rejects_skipped_rows(self) -> None:
        rows = [self._row(25, 0.1, 30, 0.2, skip=True)]

        self.assertEqual(find_positive_both_halves(rows), [])

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(find_positive_both_halves([]), [])


class FormattingTest(unittest.TestCase):
    def test_consolidated_table_includes_strategy_and_asset(self) -> None:
        rows = [
            {
                "asset": "BTC", "timeframe": "4h", "strategy": "TREND_PULLBACK (trend-pullback-v1.0.0)",
                "full": {"trades": 30, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "train": {"trades": 20, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": False},
                "test": {"trades": 10, "win_rate": 0.5, "expectancy_r": 0.1, "profit_factor": 1.2, "below_min_sample": True},
            }
        ]

        table = format_consolidated_table(rows)

        self.assertIn("BTC", table)
        self.assertIn("TREND_PULLBACK", table)
        self.assertIn("*", table)

    def test_summary_reports_none_when_nothing_qualifies(self) -> None:
        summary = format_positive_both_halves_summary([])
        self.assertIn("None.", summary)

    def test_summary_lists_qualifying_rows(self) -> None:
        rows = [
            {
                "asset": "BTC", "timeframe": "4h", "strategy": "TREND_PULLBACK (trend-pullback-v1.0.0)",
                "train": {"trades": 25, "expectancy_r": 0.15},
                "test": {"trades": 22, "expectancy_r": 0.08},
            }
        ]

        summary = format_positive_both_halves_summary(rows)

        self.assertIn("TREND_PULLBACK", summary)
        self.assertIn("0.150", summary)


if __name__ == "__main__":
    unittest.main()
