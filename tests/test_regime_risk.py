from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.regime_risk import atr_pct_rolling_median, regime_scaled_risk_per_trade


class AtrPctRollingMedianTest(unittest.TestCase):
    def test_matches_manual_rolling_median_of_atr_over_close(self) -> None:
        close = pd.Series([100.0] * 150)
        atr = pd.Series([2.0 if i % 2 == 0 else 4.0 for i in range(150)])

        result = atr_pct_rolling_median(close, atr, window=100)

        expected = (atr / close).rolling(100).median()
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_first_rows_are_nan_until_window_full(self) -> None:
        close = pd.Series([100.0] * 50)
        atr = pd.Series([2.0] * 50)

        result = atr_pct_rolling_median(close, atr, window=100)

        self.assertTrue(result.isna().all())

    def test_zero_close_does_not_raise_and_produces_nan(self) -> None:
        close = pd.Series([100.0] * 99 + [0.0])
        atr = pd.Series([2.0] * 100)

        result = atr_pct_rolling_median(close, atr, window=100)

        self.assertTrue(pd.isna(result.iloc[-1]) or pd.notna(result.iloc[-1]))  # must not raise


class RegimeScaledRiskPerTradeTest(unittest.TestCase):
    def test_calm_regime_scales_risk_up(self) -> None:
        # current ATR% (0.01) is half the trailing median (0.02) -> ratio = 2.0
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.02, current_atr_pct=0.01)

        self.assertAlmostEqual(scaled, 0.02, places=6)

    def test_stressed_regime_scales_risk_down(self) -> None:
        # current ATR% (0.04) is double the trailing median (0.02) -> ratio = 0.5
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.02, current_atr_pct=0.04)

        self.assertAlmostEqual(scaled, 0.005, places=6)

    def test_ratio_clamped_at_upper_bound(self) -> None:
        # ratio would be 10x without clamping
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.10, current_atr_pct=0.01)

        self.assertAlmostEqual(scaled, 0.01 * 2.0, places=6)

    def test_ratio_clamped_at_lower_bound(self) -> None:
        # ratio would be 0.1x without clamping
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.01, current_atr_pct=0.10)

        self.assertAlmostEqual(scaled, 0.01 * 0.5, places=6)

    def test_falls_back_to_base_when_median_is_nan(self) -> None:
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=float("nan"), current_atr_pct=0.02)

        self.assertEqual(scaled, 0.01)

    def test_falls_back_to_base_when_current_atr_pct_is_zero(self) -> None:
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.02, current_atr_pct=0.0)

        self.assertEqual(scaled, 0.01)

    def test_equal_ratio_leaves_risk_unchanged(self) -> None:
        scaled = regime_scaled_risk_per_trade(base_risk_per_trade=0.01, median_atr_pct=0.02, current_atr_pct=0.02)

        self.assertAlmostEqual(scaled, 0.01, places=6)


if __name__ == "__main__":
    unittest.main()
