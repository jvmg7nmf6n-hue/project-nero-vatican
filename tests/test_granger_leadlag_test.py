from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from nero_core.data_sources.market_data import MarketDataClient, MarketDataResult, MarketDataUnavailableError
from tools.granger_leadlag_test import BONFERRONI_THRESHOLD, NUM_TESTS, format_report, run_pair_test


def _row(close_time: int, close: float) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 10.0,
    }


def _btc_leads_alt_series(n: int, lag: int = 2, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """BTC log returns are i.i.d. noise; the alt's return at time t is (mostly) BTC's
    return at time t-lag, plus its own noise — a textbook Granger-causal relationship."""
    rng = np.random.default_rng(seed)
    btc_returns = rng.normal(0, 0.01, size=n)
    alt_returns = np.zeros(n)
    for t in range(n):
        base = btc_returns[t - lag] if t - lag >= 0 else 0.0
        alt_returns[t] = 0.8 * base + rng.normal(0, 0.003)

    btc_prices = 100.0 * np.exp(np.cumsum(btc_returns))
    alt_prices = 50.0 * np.exp(np.cumsum(alt_returns))

    close_time = 0
    btc_rows, alt_rows = [], []
    for i in range(n):
        btc_rows.append(_row(close_time, float(btc_prices[i])))
        alt_rows.append(_row(close_time, float(alt_prices[i])))
        close_time += 3_600_000
    return pd.DataFrame(btc_rows), pd.DataFrame(alt_rows)


def _independent_series(n: int, seed: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    btc_returns = rng.normal(0, 0.01, size=n)
    alt_returns = rng.normal(0, 0.01, size=n)  # fully independent of BTC
    btc_prices = 100.0 * np.exp(np.cumsum(btc_returns))
    alt_prices = 50.0 * np.exp(np.cumsum(alt_returns))

    close_time = 0
    btc_rows, alt_rows = [], []
    for i in range(n):
        btc_rows.append(_row(close_time, float(btc_prices[i])))
        alt_rows.append(_row(close_time, float(alt_prices[i])))
        close_time += 3_600_000
    return pd.DataFrame(btc_rows), pd.DataFrame(alt_rows)


class RunPairTestOfflineTest(unittest.TestCase):
    def test_detects_a_genuine_lead_lag_relationship(self) -> None:
        btc_df, alt_df = _btc_leads_alt_series(300, lag=2)
        btc_result = MarketDataResult(prices=btc_df, source="test-fixture", asset="BTC", interval="12h")
        alt_result = MarketDataResult(prices=alt_df, source="test-fixture", asset="ETH", interval="12h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else alt_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            result = run_pair_test(MarketDataClient(), "ETH", "12h")

        self.assertEqual(result["status"], "ok")
        self.assertLess(result["best_pvalue"], 0.05)

    def test_independent_series_do_not_show_strong_significance(self) -> None:
        btc_df, alt_df = _independent_series(300)
        btc_result = MarketDataResult(prices=btc_df, source="test-fixture", asset="BTC", interval="12h")
        alt_result = MarketDataResult(prices=alt_df, source="test-fixture", asset="ETH", interval="12h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else alt_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            result = run_pair_test(MarketDataClient(), "ETH", "12h")

        self.assertEqual(result["status"], "ok")
        # not a strict guarantee with random noise, but should not pass the strict
        # Bonferroni bar in the vast majority of seeds/draws
        self.assertFalse(result["significant"])

    def test_skipped_when_one_leg_fails(self) -> None:
        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            if asset == "ETH":
                raise MarketDataUnavailableError("no data")
            btc_df, _ = _independent_series(50)
            return MarketDataResult(prices=btc_df, source="test-fixture", asset="BTC", interval=interval)

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            result = run_pair_test(MarketDataClient(), "ETH", "12h")

        self.assertEqual(result["status"], "SKIPPED")

    def test_insufficient_data_status_is_reported_not_raised(self) -> None:
        btc_df, alt_df = _independent_series(20)  # far below granger_causality_pvalues' minimum
        btc_result = MarketDataResult(prices=btc_df, source="test-fixture", asset="BTC", interval="12h")
        alt_result = MarketDataResult(prices=alt_df, source="test-fixture", asset="ETH", interval="12h")

        def fake_load_intraday(self, asset, interval="1h", candles=240, twelve_data_api_key=None):
            return btc_result if asset == "BTC" else alt_result

        with patch.object(MarketDataClient, "load_intraday", fake_load_intraday):
            result = run_pair_test(MarketDataClient(), "ETH", "12h")

        self.assertEqual(result["status"], "insufficient_data")


class BonferroniConstantsTest(unittest.TestCase):
    def test_num_tests_matches_6_alts_times_2_timeframes(self) -> None:
        self.assertEqual(NUM_TESTS, 12)

    def test_threshold_matches_005_over_12(self) -> None:
        self.assertAlmostEqual(BONFERRONI_THRESHOLD, 0.05 / 12, places=8)


class FormatReportTest(unittest.TestCase):
    def test_reports_all_pairs_regardless_of_significance(self) -> None:
        results = [
            {"alt": "ETH", "timeframe": "12h", "status": "ok", "candle_count": 300, "best_lag": 2, "best_pvalue": 0.001, "significant": True},
            {"alt": "SOL", "timeframe": "12h", "status": "ok", "candle_count": 300, "best_lag": 1, "best_pvalue": 0.3, "significant": False},
        ]

        text = format_report(results)

        self.assertIn("ETH", text)
        self.assertIn("SOL", text)
        self.assertIn("LEADLAG_FOLLOW", text)

    def test_reports_null_result_plainly_when_nothing_significant(self) -> None:
        results = [
            {"alt": "ETH", "timeframe": "12h", "status": "ok", "candle_count": 300, "best_lag": 2, "best_pvalue": 0.3, "significant": False},
        ]

        text = format_report(results)

        self.assertIn("null result", text)
        self.assertIn("no LEADLAG_FOLLOW strategy is built", text)


if __name__ == "__main__":
    unittest.main()
