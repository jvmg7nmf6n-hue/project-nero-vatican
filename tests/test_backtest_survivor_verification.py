from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tests.test_cointegration_pairs import _cointegrated_pair_frames
from tests.test_council_engine import _make_candle_row
from nero_core.strategies.timeframe_calibration import max_holding_hours_for_timeframe
from tools.backtest_survivor_verification import SINGLE_ASSET_SURVIVORS, format_report, run_report


def _breakout_history(n_flat: int = 300, n_breakout: int = 60) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(n_flat):
        close = 100.0 + 0.05 * (i % 7)
        rows.append(_make_candle_row(close_time, close))
        close_time += 3_600_000
    price = rows[-1]["close"]
    for i in range(n_breakout):
        price *= 1.03 if i % 2 == 0 else 0.99
        rows.append(_make_candle_row(close_time, price))
        close_time += 3_600_000
    return pd.DataFrame(rows)


def _fake_load_intraday(asset, interval="1h", candles=240, twelve_data_api_key=None):
    if asset in ("GOLD", "BNB"):
        return MarketDataResult(prices=_breakout_history(), source="test-fixture", asset=asset, interval=interval)
    if asset in ("BTC", "ETH"):
        x_df, y_df = _cointegrated_pair_frames(500)
        prices = x_df if asset == "BTC" else y_df
        return MarketDataResult(prices=prices, source="test-fixture", asset=asset, interval=interval)
    raise MarketDataUnavailableError(f"no fixture for {asset}")


class RunReportOfflineTest(unittest.TestCase):
    def test_produces_a_row_per_survivor(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        self.assertEqual(len(results), len(SINGLE_ASSET_SURVIVORS) + 1)  # +1 for the pairs config

    def test_each_row_has_train_and_test_with_ci_and_baseline_keys(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        for row in results:
            if "error" in row:
                continue
            for split_name in ("train", "test"):
                stats = row[split_name]
                self.assertIn("ci", stats)
                self.assertIn("baseline", stats)
                self.assertIn("expectancy_r", stats)
                self.assertIn("below_min_sample", stats)

    def test_format_report_runs_without_error_and_mentions_every_survivor(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=_fake_load_intraday):
            results = run_report()

        text = format_report(results)
        self.assertIn("GOLD", text)
        self.assertIn("BNB", text)
        self.assertIn("COINTEGRATION_PAIRS", text)

    def test_skipped_fetch_reported_plainly(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            results = run_report()

        for row in results:
            self.assertIn("error", row)

    def test_ci_none_when_zero_trades(self) -> None:
        flat_history = pd.DataFrame(
            [_make_candle_row(i * 3_600_000, 100.0) for i in range(300)]
        )

        def _flat_fixture(asset, interval="1h", candles=240, twelve_data_api_key=None):
            return MarketDataResult(prices=flat_history, source="test-fixture", asset=asset, interval=interval)

        with patch.object(MarketDataClient, "load_intraday", side_effect=_flat_fixture):
            results = run_report()

        for row in results:
            if "error" in row:
                continue
            for split_name in ("train", "test"):
                stats = row[split_name]
                if stats["trades"] == 0:
                    self.assertIsNone(stats["ci"])
                    self.assertIsNone(stats["baseline"])


class TimeframeCalibrationRegressionTest(unittest.TestCase):
    """Regression guard: trend_pullback's registered max_holding_hours=24 is a
    1h-reference default. On BNB/12h that's only a 2-candle hold cap, which silently
    forces nearly every trade closed via TIME before a real stop/target can fire — the
    exact bug class already fixed for GOLD/1week. This was caught by actually running
    this report against real data before committing (see
    docs/statistical_harness_upgrade.md) and produced falsely negative expectancy for
    BNB/TREND_PULLBACK until needs_timeframe_calibration was wired in."""

    def test_bnb_config_is_flagged_for_recalibration(self) -> None:
        config = next(c for c in SINGLE_ASSET_SURVIVORS if c["asset"] == "BNB")
        self.assertTrue(config["needs_timeframe_calibration"])

    def test_gold_config_is_not_recalibrated_its_already_baked_in(self) -> None:
        config = next(c for c in SINGLE_ASSET_SURVIVORS if c["asset"] == "GOLD")
        self.assertFalse(config["needs_timeframe_calibration"])

    def test_uncalibrated_trend_pullback_would_produce_a_two_candle_hold_cap_on_12h(self) -> None:
        # Documents WHY calibration matters, independent of the report's internals.
        from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS

        self.assertEqual(DEFAULT_PARAMETERS.max_holding_hours, 24)
        self.assertLess(DEFAULT_PARAMETERS.max_holding_hours, 12 * 3)  # < 3 candles' worth of hours

    def test_calibrated_max_holding_hours_for_12h_preserves_the_24_candle_cap(self) -> None:
        self.assertEqual(max_holding_hours_for_timeframe("12h"), 24 * 12)


if __name__ == "__main__":
    unittest.main()
