from __future__ import annotations

import unittest

import pandas as pd

from nero_core.quant.quant_intelligence import (
    build_cointegration_report,
    build_cross_asset_driver_report,
    build_garch_volatility_report,
    build_granger_causality_report,
    build_kalman_beta_report,
    kalman_dynamic_beta,
    build_lead_lag_driver_report,
    build_quant_consensus_report,
    build_quant_snapshot,
    information_coefficient,
    log_returns,
    quant_driver_rows,
    rolling_beta,
    rolling_correlation,
    zscore,
)


class QuantIntelligenceTest(unittest.TestCase):
    def test_log_returns_uses_price_ratio(self) -> None:
        returns = log_returns(pd.Series([100.0, 110.0, 121.0]))

        self.assertAlmostEqual(float(returns.iloc[0]), 0.0953101798, places=6)
        self.assertAlmostEqual(float(returns.iloc[1]), 0.0953101798, places=6)

    def test_correlation_and_beta_detect_relationship(self) -> None:
        frame = pd.DataFrame(
            {
                "asset": [0.01, 0.02, 0.03, 0.04, 0.05],
                "driver": [0.005, 0.010, 0.015, 0.020, 0.025],
            }
        )

        corr = rolling_correlation(frame, "asset", "driver", window=5).iloc[-1]
        beta = rolling_beta(frame, "asset", "driver", window=5).iloc[-1]

        self.assertAlmostEqual(float(corr), 1.0, places=6)
        self.assertAlmostEqual(float(beta), 2.0, places=6)

    def test_zscore_flags_stretch(self) -> None:
        series = pd.Series([100.0] * 20 + [110.0])

        latest = zscore(series, window=20).iloc[-1]

        self.assertGreater(float(latest), 2.0)

    def test_quant_snapshot_returns_regime_and_rows(self) -> None:
        dates = pd.date_range("2026-01-01", periods=120, freq="D")
        closes = [100.0 + index * 0.5 for index in range(120)]
        prices = pd.DataFrame({"date": dates, "close": closes})

        snapshot = build_quant_snapshot(prices, asset="BTC", source="test")
        rows = quant_driver_rows(snapshot)

        self.assertEqual(snapshot.asset, "BTC")
        self.assertEqual(snapshot.observation_count, 120)
        self.assertIn("/", snapshot.regime)
        self.assertGreaterEqual(len(rows), 8)

    def test_information_coefficient_uses_rank_correlation(self) -> None:
        ic = information_coefficient(pd.Series([1, 2, 3, 4]), pd.Series([2, 4, 6, 8]))

        self.assertAlmostEqual(ic, 1.0, places=6)

    def test_cross_asset_driver_report_ranks_strongest_driver(self) -> None:
        prices = pd.DataFrame(
            {
                "btc": [100, 102, 104, 106, 108, 110, 112, 114, 116, 118],
                "spx": [50, 51, 52, 53, 54, 55, 56, 57, 58, 59],
                "dxy": [100, 99, 100, 99, 100, 99, 100, 99, 100, 99],
            }
        )

        report = build_cross_asset_driver_report("BTC", prices, windows=(3, 5))

        self.assertGreater(len(report.rows), 0)
        self.assertEqual(report.strongest_driver, "spx")
        self.assertGreater(report.strongest_correlation, 0.9)

    def test_cross_asset_driver_report_handles_empty_prices(self) -> None:
        report = build_cross_asset_driver_report("BTC", pd.DataFrame())

        self.assertEqual(report.rows, [])
        self.assertEqual(report.strongest_driver, "none")
        self.assertIn("No cross-asset price data", report.notes[0])

    def test_lead_lag_driver_report_detects_driver_lead(self) -> None:
        driver_returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.03, 0.04, -0.02, 0.01] * 12
        asset_returns = [0.0] + driver_returns[:-1]
        driver_prices = [100.0]
        asset_prices = [100.0]
        for d_ret, a_ret in zip(driver_returns, asset_returns):
            driver_prices.append(driver_prices[-1] * (1 + d_ret))
            asset_prices.append(asset_prices[-1] * (1 + a_ret))
        prices = pd.DataFrame({"btc": asset_prices, "ibit": driver_prices})

        report = build_lead_lag_driver_report("BTC", prices, max_lag=3, min_observations=30)

        self.assertEqual(report.strongest_leader, "ibit")
        self.assertEqual(report.strongest_lag_days, 1)
        self.assertGreater(report.strongest_lead_correlation, 0.9)

    def test_cointegration_report_handles_missing_or_empty_data(self) -> None:
        report = build_cointegration_report("BTC", pd.DataFrame())

        self.assertEqual(report.rows, [])
        self.assertEqual(report.strongest_pair, "none")
        self.assertIn("No cross-asset price data", report.notes[0])

    def test_cointegration_report_returns_rows_when_dependency_missing(self) -> None:
        prices = pd.DataFrame(
            {
                "btc": [100 + index * 0.5 for index in range(140)],
                "spx": [50 + index * 0.25 for index in range(140)],
            }
        )

        report = build_cointegration_report("BTC", prices, min_observations=60)

        self.assertGreaterEqual(len(report.rows), 1)
        self.assertIn(report.rows[0]["Status"], {"missing_statsmodels", "ok", "adf_failed"})

    def test_granger_report_handles_empty_prices(self) -> None:
        report = build_granger_causality_report("BTC", pd.DataFrame())

        self.assertEqual(report.rows, [])
        self.assertEqual(report.strongest_predictor, "none")
        self.assertIn("No cross-asset price data", report.notes[0])

    def test_granger_report_returns_rows_for_driver_data(self) -> None:
        driver_returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.03, 0.04, -0.02, 0.01] * 16
        asset_returns = [0.0] + driver_returns[:-1]
        driver_prices = [100.0]
        asset_prices = [100.0]
        for d_ret, a_ret in zip(driver_returns, asset_returns):
            driver_prices.append(driver_prices[-1] * (1 + d_ret))
            asset_prices.append(asset_prices[-1] * (1 + a_ret))
        prices = pd.DataFrame({"btc": asset_prices, "ibit": driver_prices})

        report = build_granger_causality_report("BTC", prices, max_lag=2, min_observations=60)

        self.assertGreaterEqual(len(report.rows), 1)
        self.assertIn(report.rows[0]["Status"], {"missing_statsmodels", "ok", "test_failed"})


    def test_garch_volatility_report_handles_short_history(self) -> None:
        report = build_garch_volatility_report(pd.DataFrame({"close": [100.0, 101.0]}), "BTC")

        self.assertEqual(report.regime, "NO_DATA")
        self.assertEqual(report.rows, [])

    def test_garch_volatility_report_returns_rows(self) -> None:
        dates = pd.date_range("2026-01-01", periods=140, freq="D")
        closes = []
        price = 100.0
        for index in range(140):
            ret = 0.01 if index % 5 else -0.015
            price *= 1 + ret
            closes.append(price)
        prices = pd.DataFrame({"date": dates, "close": closes})

        report = build_garch_volatility_report(prices, "BTC")

        self.assertGreater(len(report.rows), 0)
        self.assertGreaterEqual(report.conditional_vol, 0.0)
        self.assertIn(report.regime, {"VOL_STRESS", "VOL_ELEVATED", "VOL_COMPRESSED", "VOL_NORMAL"})

    def test_kalman_dynamic_beta_detects_relationship(self) -> None:
        driver = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02] * 30)
        asset = driver * 1.5

        beta = kalman_dynamic_beta(asset, driver)

        self.assertFalse(beta.empty)
        self.assertGreater(float(beta.iloc[-1]), 0.5)

    def test_kalman_beta_report_handles_empty_prices(self) -> None:
        report = build_kalman_beta_report("BTC", pd.DataFrame())

        self.assertEqual(report.rows, [])
        self.assertEqual(report.strongest_dynamic_driver, "none")
        self.assertIn("No cross-asset price data", report.notes[0])

    def test_kalman_beta_report_returns_rows(self) -> None:
        driver_returns = [0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.03, 0.04, -0.02, 0.01] * 14
        asset_returns = [item * 1.2 for item in driver_returns]
        driver_prices = [100.0]
        asset_prices = [100.0]
        for d_ret, a_ret in zip(driver_returns, asset_returns):
            driver_prices.append(driver_prices[-1] * (1 + d_ret))
            asset_prices.append(asset_prices[-1] * (1 + a_ret))
        prices = pd.DataFrame({"btc": asset_prices, "ibit": driver_prices})

        report = build_kalman_beta_report("BTC", prices, min_observations=60)

        self.assertGreaterEqual(len(report.rows), 1)
        self.assertEqual(report.strongest_dynamic_driver, "ibit")

    def test_quant_consensus_report_scores_snapshot(self) -> None:
        dates = pd.date_range("2026-01-01", periods=140, freq="D")
        closes = [100.0 + index for index in range(140)]
        prices = pd.DataFrame({"date": dates, "close": closes})
        snapshot = build_quant_snapshot(prices, asset="BTC", source="test")
        garch = build_garch_volatility_report(prices, "BTC")

        report = build_quant_consensus_report(snapshot, garch)

        self.assertGreaterEqual(report.score, 0.0)
        self.assertLessEqual(report.score, 100.0)
        self.assertTrue(report.rows)
        self.assertIn(report.label, {"QUANT_SUPPORTIVE", "QUANT_MILD_SUPPORT", "QUANT_NEUTRAL", "QUANT_WEAK", "QUANT_HOSTILE"})


if __name__ == "__main__":
    unittest.main()
