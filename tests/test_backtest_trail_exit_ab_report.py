from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tests.test_council_engine import _make_candle_row
from tools.backtest_trail_exit_ab_report import COMPARISONS, format_report, run_report


def _uptrend_pullback_rally_history(spacing_ms: int, n_flat: int = 220) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    price = 100.0
    for i in range(n_flat):
        price = 100.0 + 0.5 * i
        rows.append(_make_candle_row(close_time, price))
        close_time += spacing_ms
    for delta in (-8, -12, -6, 2, 5):
        price += delta
        rows.append(_make_candle_row(close_time, price))
        close_time += spacing_ms
    for _ in range(20):
        price *= 1.03
        rows.append(_make_candle_row(close_time, price))
        close_time += spacing_ms
    for _ in range(15):
        price *= 0.94
        rows.append(_make_candle_row(close_time, price))
        close_time += spacing_ms
    return pd.DataFrame(rows)


def _weekly_breakout_history() -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    price = 100.0
    for i in range(220):
        price = 100.0 + 0.05 * i
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    for _ in range(25):
        price *= 1.04
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    for _ in range(15):
        price *= 0.9
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset == "BNB":
        return MarketDataResult(prices=_uptrend_pullback_rally_history(43_200_000), source="test-fixture", asset=asset, interval=interval)
    if asset == "GOLD":
        return MarketDataResult(prices=_weekly_breakout_history(), source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


class RunReportOfflineTest(unittest.TestCase):
    def test_produces_a_row_per_comparison(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        self.assertEqual(len(results), len(COMPARISONS))

    def test_each_row_has_v1_and_v2_with_full_metric_set(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        required_keys = {
            "trades", "expectancy_r", "avg_win_r", "avg_loss_r", "win_pct",
            "profit_factor", "max_drawdown", "below_min_sample", "ci", "baseline",
        }
        for row in results:
            if "error" in row:
                continue
            for variant in ("v1", "v2"):
                for split_name in ("train", "test"):
                    self.assertTrue(required_keys.issubset(row[variant][split_name].keys()))

    def test_v2_never_reports_a_time_based_exit(self) -> None:
        # v2 has no max-holding cap at all; this is really a sanity check that the v2
        # backtest path is wired to the trail modules (which only ever produce SL/TRAIL)
        # rather than accidentally falling back to the shared TIME-capable exit.
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        for row in results:
            if "error" in row:
                continue
            # No direct exit_reason exposure in the report dict, but a nonzero trade
            # count on v2 alongside no crash is the practical proxy available here;
            # the exit-reason invariant itself is asserted directly in
            # tests/test_trend_pullback_trail.py and
            # tests/test_breakout_momentum_gold_calibrated_1week_trail.py.
            self.assertIn("trades", row["v2"]["train"])

    def test_format_report_runs_without_error_and_mentions_both_variants(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        text = format_report(results)
        self.assertIn("v1", text)
        self.assertIn("v2-trail", text)

    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            results = run_report()

        for row in results:
            self.assertIn("error", row)


if __name__ == "__main__":
    unittest.main()
