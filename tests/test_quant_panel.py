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
    """feature/timeframe-periods-asset-aware: one test per (asset_class,
    timeframe) combination identified in the branch's own investigation
    report (docs/timeframe_periods_asset_aware_investigation.md), each with
    its derivation as a comment, plus the migration-safety proofs Task 2/3
    require."""

    # --- Previously-correct entries: prove IDENTICAL output post-migration ---
    # (old bare-string value, from the table this branch replaced) vs. (new
    # (asset_class, timeframe) lookup result) -- assertEqual against the OLD
    # HARDCODED VALUE, not just re-reading the new table, so this actually
    # catches a value drifting during the migration.
    def test_crypto_12h_unchanged(self) -> None:
        # 2 candles/day (24h / 12h) x 365 days/year (24/7 market) = 730
        OLD_VALUE = 730
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.CRYPTO, "12h"), OLD_VALUE)

    def test_crypto_24h_unchanged(self) -> None:
        # 1 candle/day x 365 days/year (24/7 market) = 365
        OLD_VALUE = 365
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.CRYPTO, "24h"), OLD_VALUE)

    def test_forex_1day_corrected_from_252_to_365(self) -> None:
        # Phase 1 Fix B (docs/investigations/phase_b_forex_annualization.md):
        # 252 (conventional trading-days/year) was flagged by the
        # timeframe-periods-asset-aware branch's own backlog as likely wrong
        # and deferred as a separate, dedicated investigation. That
        # investigation confirmed it empirically: EURUSD_1day.json/
        # USDJPY_1day.json measure ~366.8 implied candles/year, weekday
        # distribution statistically uniform Mon-Sun (28-29 each day
        # including Saturday/Sunday), zero flat-OHLC candles (real, non-
        # forward-filled weekend movement) -- a continuous 7-day/week quoting
        # pattern, not a 252-trading-day calendar. 365 (not the noisier raw
        # 366.83 sample figure) is used for consistency with the CRYPTO/
        # COMMODITY_SPOT 24h convention already established in this same
        # table for continuously-quoted asset classes.
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.FOREX, "1day"), 365)
        self.assertNotEqual(
            qp.periods_per_year_for_timeframe(qp.FOREX, "1day"), 252,
            "252 is the trading-days-only convention this feed does not follow -- see the phase_b investigation.",
        )

    def test_forex_1week_unchanged(self) -> None:
        # 1 candle/week x 52 weeks/year = 52 -- asset-class-independent.
        OLD_VALUE = 52
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.FOREX, "1week"), OLD_VALUE)

    def test_stock_1day_unchanged(self) -> None:
        # 1 candle/trading-day x 252 trading days/year = 252. Empirically
        # confirmed (AAPL_1day.json: 251.7 implied candles/365 days).
        OLD_VALUE = 252
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.STOCK, "1day"), OLD_VALUE)

    def test_commodity_spot_1week_unchanged(self) -> None:
        # Same universal weekly constant as forex/anything else -- 52.
        OLD_VALUE = 52
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.COMMODITY_SPOT, "1week"), OLD_VALUE)

    def test_commodity_spot_24h_unchanged(self) -> None:
        # GOLD's "24h" export was already using the old flat "24h": 365 entry
        # (crypto/metals shared it) -- GOLD_24h.json empirically confirms 365 is
        # right for GOLD specifically too (measures 366.8 implied candles/365
        # days, near-continuous like crypto -- NOT SILVER's ~252, see the
        # commodity_futures test below for why that split matters).
        OLD_VALUE = 365
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.COMMODITY_SPOT, "24h"), OLD_VALUE)

    # --- Newly-enabled entries (the averted "4h" collision, permanently fixed) ---
    def test_crypto_4h_is_newly_enabled(self) -> None:
        # 6 candles/day (24h / 4h, 24/7 market) x 365 days/year = 2190.
        # Empirically confirmed: BTC_4h.json measures 6.03 candles/day.
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.CRYPTO, "4h"), 2190)

    def test_forex_4h_is_newly_enabled_and_deviates_from_the_conventional_formula(self) -> None:
        # NOT the conventional 24/5-trading-week formula (120h/week / 4h x 52
        # weeks = 1560). This value (2190) is MEASURED from live candle data:
        # EURUSD_4h.json/GOLD_4h.json both measure 6.03 candles/day, EVERY day
        # of the week (Sat/Sun candles present at near-weekday density, with
        # real non-flat O/H/L/C movement, not forward-filled placeholders) --
        # statistically indistinguishable from BTC_4h.json's own 6.03/day.
        # Approved 2026-08-01: use the measured continuous-quoting cadence,
        # not the textbook forex-week model, because this data provider does
        # not appear to honor a hard weekend close for this asset/timeframe.
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.FOREX, "4h"), 2190)
        self.assertNotEqual(
            qp.periods_per_year_for_timeframe(qp.FOREX, "4h"), 1560,
            "must NOT be the conventional 24/5-week textbook value -- see this test's own docstring",
        )

    def test_stock_4h_is_newly_enabled_and_is_not_the_naive_session_hours_formula(self) -> None:
        # NOT "6.5h RTH session / 4h ~= 1.6 candles/day x 252 ~= 410" -- verified
        # against nero_core.data_sources.stock_data.resample_1h_to_4h_market_
        # hours_aware (docs/stock_data_calibration_audit.md): a 6.5h RTH session
        # produces exactly 7 hourly candles -> exactly ONE complete 4h bar per
        # session (the trailing ~2.5h remainder is dropped, never fabricated).
        # So stock 4h's real cadence is 1 candle/trading-day, identical to
        # stock 1day's own 252 -- confirmed empirically too (AAPL_4h.json has
        # exactly 1 candle per trading day, weekday-only).
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.STOCK, "4h"), 252)
        self.assertEqual(
            qp.periods_per_year_for_timeframe(qp.STOCK, "4h"),
            qp.periods_per_year_for_timeframe(qp.STOCK, "1day"),
            "stock 4h and 1day must be identical -- both are exactly 1 sample/trading-day",
        )

    def test_commodity_spot_4h_is_newly_enabled(self) -> None:
        # Same measured continuous-quoting cadence as forex 4h and crypto 4h --
        # GOLD_4h.json's own weekday distribution is statistically
        # indistinguishable from EURUSD_4h.json's (both 6.03 candles/day, all 7
        # weekdays present at near-equal density).
        self.assertEqual(qp.periods_per_year_for_timeframe(qp.COMMODITY_SPOT, "4h"), 2190)

    # --- The averted-bug regression test, reconstructed directly ---
    def test_averted_bug_regression_non_forex_4h_no_longer_collides_with_forex_4h(self) -> None:
        """Reconstructs the exact scenario a prior branch almost shipped: a
        forex-specific "4h" constant silently applied to a non-forex 4h asset.
        With the old bare-string table, EVERY asset's "4h" would have shared
        ONE entry -- there was no way to ask for "BTC's 4h constant" separate
        from "EUR/USD's 4h constant". Now they're independently keyed and,
        as it happens, both resolve to the SAME measured value (2190) for a
        different, verified reason each (crypto: genuine 24/7; forex: this
        provider's empirically continuous quoting) -- proving the fix is
        structural (asset-class-keyed lookup), not a coincidence of the
        numbers landing on the same constant. Stock 4h -- a genuinely
        DIFFERENT cadence (252) -- proves the keying actually discriminates."""
        crypto_4h = qp.periods_per_year_for_timeframe(qp.CRYPTO, "4h")
        forex_4h = qp.periods_per_year_for_timeframe(qp.FOREX, "4h")
        stock_4h = qp.periods_per_year_for_timeframe(qp.STOCK, "4h")

        self.assertIsNotNone(crypto_4h)
        self.assertIsNotNone(forex_4h)
        self.assertIsNotNone(stock_4h)
        # Neither is silently borrowing the OTHER's constant by accident --
        # requesting BTC's own class must never require going through forex's
        # entry (or vice versa); each is looked up under its own explicit key.
        self.assertEqual(crypto_4h, forex_4h)  # both 2190, verified independently above
        self.assertNotEqual(stock_4h, crypto_4h)  # a genuinely different cadence, proving real discrimination
        self.assertNotEqual(stock_4h, 1560)  # not silently defaulted to the OLD forex-only value either

    # --- SILVER: commodity_futures returns None for everything, never a guess ---
    def test_commodity_futures_returns_none_for_every_timeframe(self) -> None:
        # SILVER's real trading-hours schedule (CME Globex, via yfinance SI=F)
        # has not been independently verified -- every timeframe intentionally
        # returns None rather than assuming it matches GOLD's (or anything
        # else's) calendar. See docs/timeframe_periods_asset_aware_
        # investigation.md's backlog item.
        for timeframe in ("4h", "12h", "24h", "1day", "1week"):
            with self.subTest(timeframe=timeframe):
                self.assertIsNone(qp.periods_per_year_for_timeframe(qp.COMMODITY_FUTURES, timeframe))

    # --- Undefined combinations and unknown asset classes: None, never a guess ---
    def test_unknown_timeframe_returns_none_not_a_guess(self) -> None:
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.CRYPTO, "snapshot"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.FOREX, "3day"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.STOCK, ""))

    def test_undefined_combination_of_known_class_and_known_timeframe_returns_none(self) -> None:
        # Real asset class, real timeframe string -- just never exported for
        # that combination (e.g. no crypto "1day"/"1week" export exists; no
        # forex "12h"/"24h" export exists; no commodity_spot "1day" export
        # exists -- GOLD's daily-equivalent export uses "24h", not "1day").
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.CRYPTO, "1day"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.CRYPTO, "1week"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.FOREX, "12h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.FOREX, "24h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.COMMODITY_SPOT, "1day"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.COMMODITY_SPOT, "12h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.STOCK, "12h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.STOCK, "24h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(qp.STOCK, "1week"))

    def test_none_asset_class_returns_none_regardless_of_timeframe(self) -> None:
        # An asset this project can't classify at all (e.g. not on the live
        # IN_SCOPE_PAIRS roster) -- must never fall back to guessing any other
        # class's constant.
        self.assertIsNone(qp.periods_per_year_for_timeframe(None, "4h"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(None, "1day"))
        self.assertIsNone(qp.periods_per_year_for_timeframe(None, "24h"))


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
