from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.grid_shift_robustness_audit import (
    LEADLAG_CONFIGS,
    PAIRS_CONFIG,
    SINGLE_ASSET_CONFIGS,
    format_report,
    run_leadlag_config,
    run_pairs_config,
    run_single_asset_config,
)


def _row(close_time: int, close: float, high=None, low=None, volume: float = 100.0) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "volume": volume,
    }


def _trend_hourly(n: int = 2000, start_price: float = 100.0) -> pd.DataFrame:
    """n consecutive, gap-free 1h candles with enough drift/noise for indicators to warm
    up and both entries and exits to occur across every resampled grid."""
    rows = []
    close_time = 0
    price = start_price
    for i in range(n):
        price *= 1.0006 if i % 5 else 0.994
        rows.append(_row(close_time, price, high=price * 1.01, low=price * 0.985))
        close_time += 3_600_000
    return pd.DataFrame(rows)


class RunSingleAssetConfigOfflineTest(unittest.TestCase):
    def test_produces_native_and_offset_grids_with_metrics(self) -> None:
        hourly = _trend_hourly()
        result = MarketDataResult(prices=hourly, source="test-fixture", asset="BTC", interval="1h")

        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            r = run_single_asset_config(SINGLE_ASSET_CONFIGS[0], MarketDataClient(), {})

        self.assertNotIn("error", r)
        grid_labels = [g["grid"] for g in r["grids"]]
        self.assertIn("native (exchange-provided)", grid_labels)
        self.assertIn("offset+0h (control)", grid_labels)
        self.assertIn("offset+3h", grid_labels)
        self.assertIn("offset+6h", grid_labels)
        for g in r["grids"]:
            if "error" in g:
                continue
            for split in ("full", "train", "test"):
                self.assertIn("trades", g[split])

    def test_2h_config_uses_2h_offsets_only(self) -> None:
        hourly = _trend_hourly()
        xrp_config = next(c for c in SINGLE_ASSET_CONFIGS if c["timeframe"] == "2h")
        result = MarketDataResult(prices=hourly, source="test-fixture", asset="XRP", interval="1h")

        with patch.object(MarketDataClient, "load_intraday", return_value=result):
            r = run_single_asset_config(xrp_config, MarketDataClient(), {})

        grid_labels = [g["grid"] for g in r["grids"]]
        self.assertIn("offset+1h", grid_labels)
        self.assertNotIn("offset+3h", grid_labels)

    def test_hourly_fetch_failure_is_reported_not_substituted(self) -> None:
        with patch.object(MarketDataClient, "load_intraday", side_effect=MarketDataUnavailableError("no data")):
            r = run_single_asset_config(SINGLE_ASSET_CONFIGS[0], MarketDataClient(), {})

        self.assertIn("error", r)


class RunPairsConfigOfflineTest(unittest.TestCase):
    def test_produces_grids_for_both_legs(self) -> None:
        btc_hourly = _trend_hourly(start_price=100.0)
        eth_hourly = _trend_hourly(start_price=50.0)
        btc_result = MarketDataResult(prices=btc_hourly, source="test-fixture", asset="BTC", interval="1h")
        eth_result = MarketDataResult(prices=eth_hourly, source="test-fixture", asset="ETH", interval="1h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else eth_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            r = run_pairs_config(PAIRS_CONFIG, MarketDataClient(), {})

        self.assertNotIn("error", r)
        grid_labels = [g["grid"] for g in r["grids"]]
        self.assertIn("offset+0h (control)", grid_labels)
        self.assertIn("offset+6h", grid_labels)


class RunLeadlagConfigOfflineTest(unittest.TestCase):
    def test_produces_grids_for_btc_and_alt(self) -> None:
        btc_hourly = _trend_hourly(start_price=100.0)
        sol_hourly = _trend_hourly(start_price=20.0)
        btc_result = MarketDataResult(prices=btc_hourly, source="test-fixture", asset="BTC", interval="1h")
        sol_result = MarketDataResult(prices=sol_hourly, source="test-fixture", asset="SOL", interval="1h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else sol_result

        config = next(c for c in LEADLAG_CONFIGS if c["alt"] == "SOL")
        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            r = run_leadlag_config(config, MarketDataClient(), {})

        self.assertNotIn("error", r)
        grid_labels = [g["grid"] for g in r["grids"]]
        self.assertIn("offset+0h (control)", grid_labels)
        self.assertIn("offset+3h", grid_labels)


class FormatReportTest(unittest.TestCase):
    def test_runs_without_error_on_mixed_results(self) -> None:
        results = {
            "single_asset": [{"label": "X", "error": "no data"}],
            "pairs": [{"label": "Y", "strategy": "Z", "grids": [{"grid": "native (exchange-provided)", "error": "boom"}]}],
            "leadlag": [],
            "out_of_scope": [{"label": "BTC-BNB / 24h lag1 / LEADLAG_FOLLOW", "reason": "no 24h offset specified"}],
        }

        text = format_report(results)

        self.assertIn("SKIPPED", text)
        self.assertIn("OUT OF SCOPE", text)


if __name__ == "__main__":
    unittest.main()
