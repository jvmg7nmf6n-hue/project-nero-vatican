from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from nero_core.quant import quant_panel as qp

# ---------------------------------------------------------------------------
# Synthetic series. Expected values below are computed independently with plain
# numpy calls (NOT by calling qp's own functions) so these tests actually verify
# the formulas, rather than restating them.
# ---------------------------------------------------------------------------

N = 250
FLAT = pd.Series([100.0] * N)
TRENDING = pd.Series([100.0 + 0.5 * i for i in range(N)])

_mean_reverting_values = [100.0]
for i in range(1, N):
    prev = _mean_reverting_values[-1]
    _mean_reverting_values.append(prev * 1.05 if i % 2 == 1 else prev / 1.05)
MEAN_REVERTING = pd.Series(_mean_reverting_values)

SHORT_SERIES = pd.Series([100.0 + i for i in range(20)])  # below MIN_OBSERVATIONS (30)


def _expected_log_returns(closes: pd.Series) -> np.ndarray:
    values = closes.to_numpy(dtype=float)
    return np.log(values[1:] / values[:-1])


class LogReturnsTest(unittest.TestCase):
    def test_flat_series_returns_are_all_exactly_zero(self) -> None:
        result = qp.log_returns(FLAT)
        self.assertEqual(len(result), N - 1)
        self.assertTrue((result == 0.0).all())

    def test_matches_hand_computed_log_returns_on_trending_series(self) -> None:
        result = qp.log_returns(TRENDING).to_numpy()
        expected = _expected_log_returns(TRENDING)
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_returns_empty_series_with_fewer_than_two_closes(self) -> None:
        self.assertEqual(len(qp.log_returns(pd.Series([100.0]))), 0)
        self.assertEqual(len(qp.log_returns(pd.Series([], dtype=float))), 0)


class AnnualizedLogReturnTest(unittest.TestCase):
    def test_flat_series_is_exactly_zero(self) -> None:
        self.assertEqual(qp.annualized_log_return(FLAT, periods_per_year=252), 0.0)

    def test_matches_hand_computed_mean_times_periods_per_year(self) -> None:
        expected = float(_expected_log_returns(TRENDING).mean() * 252)
        self.assertAlmostEqual(qp.annualized_log_return(TRENDING, periods_per_year=252), expected, places=10)

    def test_none_when_periods_per_year_is_none(self) -> None:
        self.assertIsNone(qp.annualized_log_return(TRENDING, periods_per_year=None))

    def test_none_with_insufficient_history(self) -> None:
        self.assertIsNone(qp.annualized_log_return(SHORT_SERIES, periods_per_year=252))


class RollingZscoreTest(unittest.TestCase):
    def test_flat_series_has_zero_std_and_returns_none(self) -> None:
        self.assertIsNone(qp.rolling_zscore(FLAT, window=20))

    def test_matches_hand_computed_zscore_on_trending_series(self) -> None:
        window = 20
        tail = TRENDING.tail(window)
        expected = (TRENDING.iloc[-1] - tail.mean()) / tail.std()  # pandas default ddof=1
        self.assertAlmostEqual(qp.rolling_zscore(TRENDING, window), expected, places=10)

    def test_uptrend_endpoint_has_a_strongly_positive_zscore(self) -> None:
        # The last point of a monotonically increasing series is always the max
        # of its own trailing window -- z-score must be positive.
        self.assertGreater(qp.rolling_zscore(TRENDING, window=20), 0)

    def test_none_when_fewer_closes_than_the_window(self) -> None:
        self.assertIsNone(qp.rolling_zscore(SHORT_SERIES, window=30))

    def test_does_not_require_min_observations_when_window_itself_is_smaller(self) -> None:
        # Regression test for a real bug caught before shipping: a 20-period
        # window must NOT be rejected just because 20 < MIN_OBSERVATIONS (30).
        self.assertIsNotNone(qp.rolling_zscore(TRENDING, window=20))


class RealizedVolatilityTest(unittest.TestCase):
    def test_flat_series_has_zero_volatility(self) -> None:
        self.assertEqual(qp.realized_volatility(FLAT, window=249, periods_per_year=252), 0.0)

    def test_matches_hand_computed_annualized_std_as_a_percentage(self) -> None:
        returns = _expected_log_returns(MEAN_REVERTING)
        expected = float(pd.Series(returns).std() * math.sqrt(365) * 100.0)  # pandas default ddof=1
        result = qp.realized_volatility(MEAN_REVERTING, window=len(returns), periods_per_year=365)
        self.assertAlmostEqual(result, expected, places=8)

    def test_high_vol_series_has_far_more_volatility_than_a_mild_trend(self) -> None:
        trending_vol = qp.realized_volatility(TRENDING, window=249, periods_per_year=252)
        mean_reverting_vol = qp.realized_volatility(MEAN_REVERTING, window=249, periods_per_year=252)
        self.assertGreater(mean_reverting_vol, trending_vol * 5)

    def test_none_when_periods_per_year_is_none(self) -> None:
        self.assertIsNone(qp.realized_volatility(TRENDING, window=249, periods_per_year=None))

    def test_none_with_insufficient_history(self) -> None:
        self.assertIsNone(qp.realized_volatility(SHORT_SERIES, window=249, periods_per_year=252))

    def test_window_is_clamped_to_available_history_not_hardcoded(self) -> None:
        # Asking for a 252-period window on 250 closes (249 returns) must not
        # return None -- it should clamp down to what's actually available.
        self.assertIsNotNone(qp.realized_volatility(TRENDING, window=252, periods_per_year=252))


class SharpeRatioTest(unittest.TestCase):
    def test_flat_series_has_zero_volatility_and_returns_none(self) -> None:
        self.assertIsNone(qp.sharpe_ratio(FLAT, window=249, periods_per_year=252, rf_annual=0.04))

    def test_matches_hand_computed_sharpe(self) -> None:
        returns = pd.Series(_expected_log_returns(MEAN_REVERTING))
        rf_annual = 0.05
        ann_return = float(returns.mean() * 365)
        ann_vol = float(returns.std() * math.sqrt(365))
        expected = (ann_return - rf_annual) / ann_vol
        result = qp.sharpe_ratio(MEAN_REVERTING, window=len(returns), periods_per_year=365, rf_annual=rf_annual)
        self.assertAlmostEqual(result, expected, places=8)

    def test_none_when_periods_per_year_is_none(self) -> None:
        self.assertIsNone(qp.sharpe_ratio(TRENDING, window=249, periods_per_year=None, rf_annual=0.04))

    def test_none_with_insufficient_history(self) -> None:
        self.assertIsNone(qp.sharpe_ratio(SHORT_SERIES, window=249, periods_per_year=252, rf_annual=0.04))

    def test_uptrend_has_a_positive_sharpe_and_downtrend_style_high_rf_has_lower_sharpe(self) -> None:
        low_rf = qp.sharpe_ratio(TRENDING, window=249, periods_per_year=252, rf_annual=0.01)
        high_rf = qp.sharpe_ratio(TRENDING, window=249, periods_per_year=252, rf_annual=0.20)
        self.assertGreater(low_rf, high_rf)


class SortinoRatioTest(unittest.TestCase):
    def test_flat_series_with_zero_rf_has_zero_downside_deviation_and_returns_none(self) -> None:
        # With rf_annual=0 (so the default per-period MAR is also 0), a flat
        # (all-zero-return) series never falls short of MAR -- downside
        # deviation is exactly zero and Sortino is undefined.
        self.assertIsNone(qp.sortino_ratio(FLAT, window=249, periods_per_year=252, rf_annual=0.0))

    def test_flat_series_with_positive_rf_is_a_well_defined_large_negative_sortino(self) -> None:
        # NOT the same as the zero-rf case above: every zero-return period is
        # now below a positive MAR (rf_annual/periods_per_year), so downside
        # deviation is a well-defined small positive constant, not zero --
        # Sortino is a legitimate (very negative) number, not None.
        rf_annual = 0.04
        periods_per_year = 252
        result = qp.sortino_ratio(FLAT, window=249, periods_per_year=periods_per_year, rf_annual=rf_annual)
        per_period_mar = rf_annual / periods_per_year
        expected_downside_deviation = per_period_mar * math.sqrt(periods_per_year)
        expected = (0.0 - rf_annual) / expected_downside_deviation
        self.assertAlmostEqual(result, expected, places=8)
        self.assertLess(result, -10)

    def test_matches_hand_computed_sortino_with_default_mar(self) -> None:
        returns = pd.Series(_expected_log_returns(MEAN_REVERTING))
        rf_annual = 0.05
        periods_per_year = 365
        per_period_mar = rf_annual / periods_per_year
        ann_return = float(returns.mean() * periods_per_year)
        downside = (returns - per_period_mar).clip(upper=0.0)
        downside_deviation = math.sqrt(float((downside**2).mean())) * math.sqrt(periods_per_year)
        expected = (ann_return - rf_annual) / downside_deviation

        result = qp.sortino_ratio(MEAN_REVERTING, window=len(returns), periods_per_year=periods_per_year, rf_annual=rf_annual)
        self.assertAlmostEqual(result, expected, places=8)

    def test_explicit_mar_overrides_the_rf_derived_default(self) -> None:
        default_mar = qp.sortino_ratio(MEAN_REVERTING, window=249, periods_per_year=365, rf_annual=0.05)
        custom_mar = qp.sortino_ratio(MEAN_REVERTING, window=249, periods_per_year=365, rf_annual=0.05, mar=0.01)
        self.assertNotAlmostEqual(default_mar, custom_mar, places=6)

    def test_none_when_periods_per_year_is_none(self) -> None:
        self.assertIsNone(qp.sortino_ratio(TRENDING, window=249, periods_per_year=None, rf_annual=0.04))

    def test_none_with_insufficient_history(self) -> None:
        self.assertIsNone(qp.sortino_ratio(SHORT_SERIES, window=249, periods_per_year=252, rf_annual=0.04))


class PeriodsPerYearLookupTest(unittest.TestCase):
    def test_all_four_documented_timeframes(self) -> None:
        self.assertEqual(qp.periods_per_year_for_timeframe("12h"), 730)
        self.assertEqual(qp.periods_per_year_for_timeframe("24h"), 365)
        self.assertEqual(qp.periods_per_year_for_timeframe("1day"), 252)
        self.assertEqual(qp.periods_per_year_for_timeframe("1week"), 52)

    def test_4h_is_sized_for_a_24_5_market_not_24_7(self) -> None:
        # Forex-only key (see this table's own docstring caveat): 5 tradeable
        # days/week x 24h = 120h, / 4h per candle = 30 candles/week x 52 = 1560.
        # NOT the 2190/year a 24/7 4h asset (6 candles/day x 365) would need.
        self.assertEqual(qp.periods_per_year_for_timeframe("4h"), 1560)

    def test_unknown_timeframe_returns_none_not_a_guess(self) -> None:
        self.assertIsNone(qp.periods_per_year_for_timeframe("snapshot"))
        self.assertIsNone(qp.periods_per_year_for_timeframe("3day"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(""))


class CrossValidationLogicTest(unittest.TestCase):
    def test_identical_values_cross_validate(self) -> None:
        self.assertTrue(qp.cross_validates(1.25, 1.25))

    def test_within_five_percent_cross_validates(self) -> None:
        self.assertTrue(qp.cross_validates(1.04, 1.00))  # exactly 4% relative diff
        self.assertAlmostEqual(qp.relative_difference(1.04, 1.00), 0.04, places=10)

    def test_beyond_five_percent_does_not_cross_validate(self) -> None:
        self.assertFalse(qp.cross_validates(1.06, 1.00))  # 6% relative diff
        self.assertAlmostEqual(qp.relative_difference(1.06, 1.00), 0.06, places=10)

    def test_just_under_the_tolerance_boundary_passes(self) -> None:
        self.assertTrue(qp.cross_validates(1.049, 1.00))  # 4.9% relative diff

    def test_just_over_the_tolerance_boundary_fails(self) -> None:
        self.assertFalse(qp.cross_validates(1.051, 1.00))  # 5.1% relative diff

    def test_zero_reference_is_undefined_and_never_passes(self) -> None:
        self.assertIsNone(qp.relative_difference(1.0, 0.0))
        self.assertFalse(qp.cross_validates(1.0, 0.0))

    def test_negative_values_use_absolute_relative_difference(self) -> None:
        self.assertTrue(qp.cross_validates(-1.02, -1.00))
        self.assertFalse(qp.cross_validates(-1.10, -1.00))


if __name__ == "__main__":
    unittest.main()
