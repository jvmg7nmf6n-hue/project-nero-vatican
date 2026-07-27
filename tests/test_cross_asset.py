from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from nero_core.quant import cross_asset as ca


def _closes_from_returns(returns: list[float], start: float = 100.0) -> list[float]:
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * math.exp(r))
    return closes


def _write_candle_file(directory: Path, filename: str, asset: str, timeframe: str, closes: list[float], times: list[int] | None = None) -> None:
    if times is None:
        times = list(range(len(closes)))
    payload = {
        "schema_version": 1,
        "asset": asset,
        "timeframe": timeframe,
        "last_updated": "2026-07-01T00:00:00+00:00",
        "candles": [
            {"time": t, "open": c, "high": c, "low": c, "close": c, "volume": 1000.0} for t, c in zip(times, closes)
        ],
    }
    (directory / filename).write_text(json.dumps(payload))


class CorrelationMatrixTest(unittest.TestCase):
    def test_perfectly_correlated_pair_reports_correlation_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns_a = [0.01 * math.sin(i * 0.7) for i in range(40)]
            returns_b = [2.0 * r for r in returns_a]  # positive scalar multiple -> corr == 1.0
            times = list(range(41))
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns_a), times)
            _write_candle_file(d, "B_24h.json", "B", "24h", _closes_from_returns(returns_b), times)

            result = ca.rolling_correlation_matrix(d, window=30)
            pair = result["pairs"][0]
            self.assertAlmostEqual(pair["correlation"], 1.0, places=8)
            self.assertEqual(pair["window_used"], 30)

    def test_perfectly_anti_correlated_pair_reports_correlation_negative_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns_a = [0.01 * math.sin(i * 0.7) for i in range(40)]
            returns_b = [-3.0 * r for r in returns_a]  # negative scalar multiple -> corr == -1.0
            times = list(range(41))
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns_a), times)
            _write_candle_file(d, "B_24h.json", "B", "24h", _closes_from_returns(returns_b), times)

            result = ca.rolling_correlation_matrix(d, window=30)
            pair = result["pairs"][0]
            self.assertAlmostEqual(pair["correlation"], -1.0, places=8)

    def test_uncorrelated_square_waves_report_correlation_near_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Period-2 square wave vs period-4 square wave -- orthogonal over any
            # whole number of period-4 blocks, both zero-mean, equal magnitude ->
            # exactly zero correlation, not just "small."
            r = 0.01
            n_blocks = 12  # 48 returns, 4 full period-4 blocks' worth and more
            returns_a = [r if i % 2 == 0 else -r for i in range(n_blocks * 4)]
            returns_b = [r, r, -r, -r] * n_blocks
            times = list(range(len(returns_a) + 1))
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns_a), times)
            _write_candle_file(d, "B_24h.json", "B", "24h", _closes_from_returns(returns_b), times)

            result = ca.rolling_correlation_matrix(d, window=30)
            pair = result["pairs"][0]
            self.assertAlmostEqual(pair["correlation"], 0.0, places=8)

    def test_pairs_at_different_timeframes_are_never_compared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.7) for i in range(40)]
            times = list(range(41))
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns), times)
            _write_candle_file(d, "B_1week.json", "B", "1week", _closes_from_returns(returns), times)

            result = ca.rolling_correlation_matrix(d, window=30)
            self.assertEqual(result["pairs"], [])

    def test_same_timeframe_label_but_no_overlapping_timestamps_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.7) for i in range(40)]
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns), list(range(41)))
            # Same timeframe LABEL, but a completely disjoint calendar grid --
            # exactly the real SILVER-vs-BTC/GOLD situation confirmed against
            # actual Day 1 exports.
            _write_candle_file(d, "B_24h.json", "B", "24h", _closes_from_returns(returns), list(range(10_000, 10_041)))

            result = ca.rolling_correlation_matrix(d, window=30)
            pair = result["pairs"][0]
            self.assertIsNone(pair["correlation"])
            self.assertEqual(pair["window_used"], 0)

    def test_below_window_overlap_is_null_not_fabricated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.7) for i in range(20)]  # only 20 returns, below window=30
            times = list(range(21))
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns), times)
            _write_candle_file(d, "B_24h.json", "B", "24h", _closes_from_returns(returns), times)

            result = ca.rolling_correlation_matrix(d, window=30)
            pair = result["pairs"][0]
            self.assertIsNone(pair["correlation"])
            self.assertEqual(pair["window_used"], 20)

    def test_only_one_asset_at_a_timeframe_produces_no_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.7) for i in range(40)]
            _write_candle_file(d, "A_12h.json", "A", "12h", _closes_from_returns(returns), list(range(41)))
            result = ca.rolling_correlation_matrix(d, window=30)
            self.assertEqual(result["pairs"], [])


class VolatilityRegimeTest(unittest.TestCase):
    def test_high_vol_series_lands_in_high_or_extreme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            high_vol_returns = [0.10 if i % 2 == 0 else -0.10 for i in range(70)]
            _write_candle_file(d, "HV_24h.json", "HV", "24h", _closes_from_returns(high_vol_returns))

            result = ca.volatility_regimes(d)
            entry = result["entries"][0]
            self.assertIn(entry["regime"], {"HIGH", "EXTREME"})
            self.assertIn(entry["model_used"], {"GARCH(1,1)", "EWMA fallback"})

    def test_low_vol_series_lands_in_low_or_normal_and_has_less_conditional_vol_than_high_vol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            low_vol_returns = [0.001 if i % 2 == 0 else -0.001 for i in range(70)]
            high_vol_returns = [0.10 if i % 2 == 0 else -0.10 for i in range(70)]
            _write_candle_file(d, "LV_24h.json", "LV", "24h", _closes_from_returns(low_vol_returns))
            _write_candle_file(d, "HV_24h.json", "HV", "24h", _closes_from_returns(high_vol_returns))

            result = ca.volatility_regimes(d)
            by_asset = {e["asset"]: e for e in result["entries"]}
            self.assertIn(by_asset["LV"]["regime"], {"LOW", "NORMAL"})
            self.assertLess(by_asset["LV"]["conditional_vol"], by_asset["HV"]["conditional_vol"])

    def test_regime_labels_use_the_task_vocabulary_never_the_internal_vol_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.10 if i % 2 == 0 else -0.10 for i in range(70)]
            _write_candle_file(d, "X_24h.json", "X", "24h", _closes_from_returns(returns))
            result = ca.volatility_regimes(d)
            self.assertIn(result["entries"][0]["regime"], {"LOW", "NORMAL", "HIGH", "EXTREME"})


class CointegrationTest(unittest.TestCase):
    def _write_pair(self, d: Path) -> None:
        import numpy as np

        rng = np.random.default_rng(42)
        n = 150
        increments = rng.normal(0, 1, n)
        a_closes = (1000 + increments.cumsum()).tolist()
        noise = rng.normal(0, 0.5, n)
        b_closes = (a_closes + noise).tolist()
        times = list(range(n))
        _write_candle_file(d, "GOLD_24h.json", "GOLD", "24h", a_closes, times)
        _write_candle_file(d, "SILVER_24h.json", "SILVER", "24h", b_closes, times)

    def test_pvalue_is_a_real_float_not_nan_for_an_adequate_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_pair(d)
            result = ca.cointegration_report(d)
            entry = next(e for e in result["entries"] if e["asset_a"] == "GOLD" and e["asset_b"] == "SILVER")
            self.assertIsInstance(entry["pvalue"], float)
            self.assertFalse(math.isnan(entry["pvalue"]))
            self.assertIsInstance(entry["cointegrated"], bool)

    def test_a_true_cointegrated_pair_by_construction_is_detected(self) -> None:
        # B = A + stationary noise -- a textbook cointegrated construction (both
        # I(1) with the identical stochastic trend, residual is stationary).
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_pair(d)
            result = ca.cointegration_report(d)
            entry = next(e for e in result["entries"] if e["asset_a"] == "GOLD" and e["asset_b"] == "SILVER")
            self.assertLess(entry["pvalue"], 0.05)
            self.assertTrue(entry["cointegrated"])
            self.assertIn("Cointegrated", entry["note"])

    def test_a_computed_pair_note_carries_the_descriptive_statistic_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_pair(d)
            result = ca.cointegration_report(d)
            entry = next(e for e in result["entries"] if e["asset_a"] == "GOLD" and e["asset_b"] == "SILVER")
            self.assertIn("Descriptive statistic", entry["note"])
            self.assertNotIn("Trade Signal", entry["note"])
            self.assertNotIn("Recommendation", entry["note"])

    def test_missing_candle_file_for_a_requested_pair_is_null_with_a_clear_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)  # completely empty -- none of the 4 requested pairs exist
            result = ca.cointegration_report(d)
            self.assertEqual(len(result["entries"]), 4)
            for entry in result["entries"]:
                self.assertIsNone(entry["pvalue"])
                self.assertIsNone(entry["cointegrated"])


class LeadLagTest(unittest.TestCase):
    def test_detects_the_known_lag_in_a_synthetic_lead_lag_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            lag = 2
            n = 80
            benchmark_returns = [0.01 * math.sin(i * 0.9) for i in range(n)]
            other_returns = [0.0] * lag + benchmark_returns[: n - lag]
            times = list(range(n + 1))
            _write_candle_file(d, "BTC_12h.json", "BTC", "12h", _closes_from_returns(benchmark_returns), times)
            _write_candle_file(d, "BNB_12h.json", "BNB", "12h", _closes_from_returns(other_returns), times)

            result = ca.lead_lag_report(d)
            entry = next(e for e in result["entries"] if e["asset"] == "BNB")
            self.assertEqual(entry["best_lag"], lag)
            self.assertAlmostEqual(entry["correlation"], 1.0, places=6)

    def test_only_crypto_class_assets_are_compared_against_the_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.9) for i in range(80)]
            times = list(range(81))
            _write_candle_file(d, "BTC_12h.json", "BTC", "12h", _closes_from_returns(returns), times)
            _write_candle_file(d, "AAPL_12h.json", "AAPL", "12h", _closes_from_returns(returns), times)  # not crypto

            result = ca.lead_lag_report(d)
            assets_compared = {e["asset"] for e in result["entries"]}
            self.assertNotIn("AAPL", assets_compared)

    def test_no_shared_timeframe_with_benchmark_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.9) for i in range(80)]
            _write_candle_file(d, "BTC_24h.json", "BTC", "24h", _closes_from_returns(returns), list(range(81)))
            _write_candle_file(d, "BNB_12h.json", "BNB", "12h", _closes_from_returns(returns), list(range(81)))

            result = ca.lead_lag_report(d)
            entry = result["entries"][0]
            self.assertIsNone(entry["best_lag"])
            self.assertIn("No BTC candle file shares", entry["note"])

    def test_below_min_observations_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.9) for i in range(20)]  # below LEAD_LAG_MIN_OBSERVATIONS (60)
            times = list(range(21))
            _write_candle_file(d, "BTC_12h.json", "BTC", "12h", _closes_from_returns(returns), times)
            _write_candle_file(d, "BNB_12h.json", "BNB", "12h", _closes_from_returns(returns), times)

            result = ca.lead_lag_report(d)
            entry = result["entries"][0]
            self.assertIsNone(entry["best_lag"])


class LoadCandleSeriesFailIndependenceTest(unittest.TestCase):
    def test_a_corrupt_file_is_reported_and_excluded_others_still_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            returns = [0.01 * math.sin(i * 0.7) for i in range(40)]
            _write_candle_file(d, "A_24h.json", "A", "24h", _closes_from_returns(returns))
            (d / "CORRUPT_24h.json").write_text("{not valid json")

            series, errors = ca.load_candle_series(d)
            self.assertEqual([s.asset for s in series], ["A"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0]["file"], "CORRUPT_24h.json")


if __name__ == "__main__":
    unittest.main()
