from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.backtest_macro_risk_on_sweep import format_report, run_asset, run_sweep


def _daily_candles(n: int, start: str = "2020-01-01") -> pd.DataFrame:
    rows = []
    price = 100.0
    for i, ts in enumerate(pd.date_range(start=start, periods=n, freq="D", tz="UTC")):
        price *= 1.001 if i % 7 else 0.995
        close_time = int(ts.timestamp() * 1000)
        rows.append(
            {
                "date": ts, "open_time": close_time - 86_400_000, "close_time": close_time,
                "open": price, "high": price * 1.02, "low": price * 0.98, "close": price, "volume": 100.0,
            }
        )
    return pd.DataFrame(rows)


def _macro_series(n_business_days: int, start: str, falling: bool) -> pd.Series:
    dates = pd.bdate_range(start=start, periods=n_business_days)
    if falling:
        values = [100.0 - 0.05 * i for i in range(n_business_days)]
    else:
        values = [100.0 + 0.05 * (i % 40) for i in range(n_business_days)]
    return pd.Series(values, index=dates)


class RunAssetOfflineTest(unittest.TestCase):
    def test_produces_full_train_test_rows(self) -> None:
        candles = _daily_candles(500)
        result = MarketDataResult(prices=candles, source="test-fixture", asset="BTC", interval="1d")
        dollar_series = _macro_series(500, "2019-06-01", falling=True)
        dfii10_series = _macro_series(500, "2019-06-01", falling=True)

        with patch.object(MarketDataClient, "load_daily", return_value=result):
            r = run_asset("BTC", MarketDataClient(), dollar_series, dfii10_series)

        self.assertNotIn("error", r)
        for split in ("full", "train", "test"):
            self.assertIn("trades", r[split])
            self.assertIn("pct_risk_on", r[split])

    def test_fetch_failure_reported_not_substituted(self) -> None:
        with patch.object(MarketDataClient, "load_daily", side_effect=MarketDataUnavailableError("no data")):
            r = run_asset("BTC", MarketDataClient(), pd.Series(dtype=float), pd.Series(dtype=float))

        self.assertIn("error", r)


class RunSweepOfflineTest(unittest.TestCase):
    def test_covers_both_assets(self) -> None:
        candles = _daily_candles(500)
        result = MarketDataResult(prices=candles, source="test-fixture", asset="BTC", interval="1d")
        dollar_series = _macro_series(500, "2019-06-01", falling=True)
        dfii10_series = _macro_series(500, "2019-06-01", falling=True)

        with patch("tools.backtest_macro_risk_on_sweep.fetch_dollar_proxy_daily", return_value=(dollar_series, "test-fixture")):
            with patch("tools.backtest_macro_risk_on_sweep.fetch_dfii10_daily", return_value=(dfii10_series, "test-fixture")):
                with patch.object(MarketDataClient, "load_daily", return_value=result):
                    results = run_sweep()

        self.assertEqual({r["asset"] for r in results}, {"BTC", "GOLD"})


class FormatReportTest(unittest.TestCase):
    def test_runs_without_error_on_mixed_results(self) -> None:
        results = [
            {"asset": "BTC", "error": "no data"},
            {
                "asset": "GOLD",
                "candle_source": "test",
                "full": {"candles": 100, "pct_risk_on": 40.0, "trades": 5, "win_rate": 0.6, "expectancy_r": 0.2, "profit_factor": 1.5, "max_drawdown": -0.1, "below_min_sample": True},
                "train": {"candles": 70, "pct_risk_on": 40.0, "trades": 3, "win_rate": 0.6, "expectancy_r": 0.2, "profit_factor": 1.5, "max_drawdown": -0.1, "below_min_sample": True},
                "test": {"candles": 30, "pct_risk_on": 40.0, "trades": 2, "win_rate": 0.6, "expectancy_r": 0.2, "profit_factor": 1.5, "max_drawdown": -0.1, "below_min_sample": True},
            },
        ]

        text = format_report(results)

        self.assertIn("SKIPPED", text)
        self.assertIn("LOW SAMPLE", text)


if __name__ == "__main__":
    unittest.main()
