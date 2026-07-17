from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    TrendPullbackParameters,
    add_indicators,
    evaluate_entry,
    register_default_variant,
    size_entry,
)


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T01:00:00Z"),
        "open_time": close_time - 3600000,
        "close_time": close_time,
        "open": 109.0,
        "high": 111.0,
        "low": 108.0,
        "close": 110.0,
        "volume": 1000.0,
        "atr": 2.0,
        "rsi": 50.0,
        "ma50": 108.5,
        "ma200": 90.0,
        "prior_near_ma50": True,
    }
    data.update(overrides)
    return pd.Series(data)


def _make_ohlcv_row(close_time: int, close: float) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 100.0,
    }


class AddIndicatorsTest(unittest.TestCase):
    def _uptrend_with_pullback_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        close_time = 0
        # 210 candles of a slow uptrend so MA200/MA50 both develop with MA50 > MA200.
        for i in range(210):
            rows.append(_make_ohlcv_row(close_time, 100.0 + 0.2 * i))
            close_time += 3_600_000
        # a pullback candle: price dips back down close to MA50's current level.
        last_price = 100.0 + 0.2 * 209
        rows.append(_make_ohlcv_row(close_time, last_price - 6.0))
        close_time += 3_600_000
        # recovery candle: closes back above MA50.
        rows.append(_make_ohlcv_row(close_time, last_price + 1.0))
        close_time += 3_600_000
        return pd.DataFrame(rows)

    def test_prior_near_ma50_flag_is_shifted_no_lookahead(self) -> None:
        frame = self._uptrend_with_pullback_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        pullback_row_index = 210
        recovery_row_index = 211
        distance = abs(enriched.iloc[pullback_row_index]["close"] - enriched.iloc[pullback_row_index]["ma50"])
        atr_value = enriched.iloc[pullback_row_index]["atr"]
        expected_flag_on_pullback_row = distance <= DEFAULT_PARAMETERS.pullback_atr_buffer * atr_value

        self.assertEqual(enriched.iloc[recovery_row_index]["prior_near_ma50"], expected_flag_on_pullback_row)

    def test_first_row_prior_near_ma50_is_false_not_undefined(self) -> None:
        frame = self._uptrend_with_pullback_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        self.assertEqual(enriched.iloc[0]["prior_near_ma50"], False)

    def test_ma50_and_ma200_match_rolling_means(self) -> None:
        frame = self._uptrend_with_pullback_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        expected_ma50 = frame["close"].rolling(50).mean()
        expected_ma200 = frame["close"].rolling(200).mean()
        pd.testing.assert_series_equal(enriched["ma50"], expected_ma50, check_names=False)
        pd.testing.assert_series_equal(enriched["ma200"], expected_ma200, check_names=False)


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_passes_when_all_conditions_met(self) -> None:
        candle = make_candle(close=110.0, ma50=108.5, ma200=90.0, rsi=50.0, prior_near_ma50=True)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())

    def test_blocked_when_not_in_established_uptrend_ma50_below_ma200(self) -> None:
        candle = make_candle(ma50=85.0, ma200=90.0)  # MA50 <= MA200: no established uptrend

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_IN_ESTABLISHED_UPTREND", evaluation.reasons)

    def test_blocked_when_close_not_above_ma200(self) -> None:
        candle = make_candle(close=110.0, ma200=115.0, ma50=108.5)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_IN_ESTABLISHED_UPTREND", evaluation.reasons)

    def test_blocked_when_no_recent_pullback(self) -> None:
        candle = make_candle(prior_near_ma50=False)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_RECENT_PULLBACK_TO_MA50", evaluation.reasons)

    def test_blocked_when_close_not_back_above_ma50(self) -> None:
        candle = make_candle(close=107.0, ma50=108.5)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_BACK_ABOVE_MA50", evaluation.reasons)

    def test_blocked_when_rsi_below_neutral_band(self) -> None:
        candle = make_candle(rsi=35.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_OUTSIDE_NEUTRAL_BAND", evaluation.reasons)

    def test_blocked_when_rsi_above_neutral_band(self) -> None:
        candle = make_candle(rsi=70.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_OUTSIDE_NEUTRAL_BAND", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        from nero_core.strategies.trend_pullback import OpenTrade

        self.state.open_trade = OpenTrade(
            entry_price=100.0, stop_loss=98.0, target=104.0, quantity=1.0, notional=100.0,
            risk_dollars=2.0, entry_fee=0.1, open_close_time=0, entry_atr=2.0,
            entry_rsi=50.0, entry_ma50=99.0, entry_ma200=90.0,
        )
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_daily_loss_guard_blocks_entry(self) -> None:
        self.state.daily_r = -5.0
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)

    def test_all_failing_reasons_are_reported_not_just_the_first(self) -> None:
        candle = make_candle(close=95.0, ma50=85.0, ma200=90.0, prior_near_ma50=False, rsi=70.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIn("NOT_IN_ESTABLISHED_UPTREND", evaluation.reasons)
        self.assertIn("NO_RECENT_PULLBACK_TO_MA50", evaluation.reasons)
        self.assertIn("RSI_OUTSIDE_NEUTRAL_BAND", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_stop_is_1_5x_atr_below_entry(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.entry_price - trade.stop_loss, 1.5 * 2.0, places=6)

    def test_target_is_2_0x_atr_above_entry(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.target - trade.entry_price, 2.0 * 2.0, places=6)

    def test_returns_none_when_atr_is_zero(self) -> None:
        candle = make_candle(atr=0.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNone(trade)

    def test_notional_capped_by_max_notional_pct(self) -> None:
        params = TrendPullbackParameters(max_notional_pct=0.5, risk_per_trade=0.5)
        candle = make_candle(atr=0.01)

        trade = size_entry(candle, self.state, params)

        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, self.state.equity * 0.5 + 1e-6)


class ExitReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_target_exit(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.target + 1.0, low=entry.stop_loss + 0.1, close=entry.target),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TARGET")

    def test_stop_exit(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.target - 0.1, low=entry.stop_loss - 1.0, close=entry.stop_loss),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")

    def test_time_exit_after_max_holding_hours(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(
                close_time=3600000 + 24 * 3600000,
                high=entry.target - 0.1,
                low=entry.stop_loss + 0.1,
                close=entry.entry_price,
            ),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "trend-pullback-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


class RegimeScaledRiskSizingTest(unittest.TestCase):
    """H3 hypothesis: regime_scaled_risk defaults to False and must leave v1.0.0's
    sizing byte-for-byte unchanged; when explicitly enabled, risk_dollars must scale by
    the clamped median/current ATR% ratio."""

    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_default_is_disabled_and_matches_v1_sizing(self) -> None:
        self.assertFalse(DEFAULT_PARAMETERS.regime_scaled_risk)
        candle = make_candle(atr=2.0, atr_pct_median100=0.05)
        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * DEFAULT_PARAMETERS.risk_per_trade, places=6)

    def test_enabled_scales_risk_dollars_by_clamped_ratio(self) -> None:
        params = TrendPullbackParameters(regime_scaled_risk=True)
        current_atr_pct = 2.0 / 110.0
        candle = make_candle(close=110.0, atr=2.0, atr_pct_median100=current_atr_pct * 0.25)  # ratio -> clamp floor 0.5

        trade = size_entry(candle, self.state, params)

        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * params.risk_per_trade * 0.5, places=4)

    def test_enabled_falls_back_to_base_risk_when_median_column_missing(self) -> None:
        params = TrendPullbackParameters(regime_scaled_risk=True)
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, params)

        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * params.risk_per_trade, places=6)


if __name__ == "__main__":
    unittest.main()
