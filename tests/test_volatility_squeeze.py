from __future__ import annotations

import math
import unittest
from dataclasses import fields

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.volatility_squeeze import (
    DEFAULT_PARAMETERS_MA100,
    DEFAULT_PARAMETERS_MA150,
    DEFAULT_PARAMETERS_MA200,
    HOURS_PER_TIMEFRAME,
    STRATEGY_ID,
    STRATEGY_VERSION_MA100,
    STRATEGY_VERSION_MA150,
    STRATEGY_VERSION_MA200,
    VolatilitySqueezeParameters,
    add_indicators,
    build_params_for_run,
    evaluate_entry,
    gold_calibrated_fees,
    max_holding_hours_for_timeframe,
    register_all_variants,
    register_ma100_variant,
    register_ma150_variant,
    register_ma200_variant,
    size_entry,
)


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    """Directly constructs a candle with indicator columns already populated — bypasses
    add_indicators so evaluate_entry/size_entry can be unit-tested in isolation, mirroring
    the make_candle helpers in test_mean_reversion_strategy.py / test_breakout_momentum.py."""
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
        "bb_width": 0.05,
        "squeeze_streak": 0,
        "prior_squeeze_streak": 6,
        "prior_squeeze_run_high": 109.5,
        "trend_ma": 95.0,
    }
    data.update(overrides)
    return pd.Series(data)


def _make_ohlcv_row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "volume": 100.0,
    }


WARMUP_CANDLES = 220
SQUEEZE_CANDLES = 25
# Index of the last squeeze-block candle and the breakout candle that follows it, given
# the fixture layout below (warmup, then a squeeze block, then one breakout candle).
LAST_SQUEEZE_ROW = WARMUP_CANDLES + SQUEEZE_CANDLES - 1
BREAKOUT_ROW = WARMUP_CANDLES + SQUEEZE_CANDLES


class AddIndicatorsTest(unittest.TestCase):
    def _squeeze_then_breakout_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        close_time = 0
        # Long, continuously-varying-amplitude warmup (never two identical widths in a
        # row, unlike a flat alternation, which would tie with the rolling 20th
        # percentile and falsely count as "squeeze") so BB width has real variation and
        # MA200 develops before the deliberate squeeze block below.
        for i in range(WARMUP_CANDLES):
            amplitude = 3.0 + 2.0 * math.sin(i * 0.15)
            wobble = amplitude if i % 2 == 0 else -amplitude
            price = 100.0 + wobble
            high = price + 4.0 + abs(math.sin(i * 0.07))
            low = price - 4.0 - abs(math.cos(i * 0.09))
            rows.append(_make_ohlcv_row(close_time, price, high=high, low=low))
            close_time += 3_600_000
        # Squeeze block: enough tight-range candles (SQUEEZE_CANDLES) that the rolling
        # 20-period BB window is EVENTUALLY built entirely from tight closes (a shorter
        # block would still have residual warmup volatility inside its own 20-period
        # window and never actually register as squeezed).
        for i in range(SQUEEZE_CANDLES):
            rows.append(_make_ohlcv_row(close_time, 100.0 + 0.01 * i, high=100.05, low=99.95))
            close_time += 3_600_000
        # Breakout candle: closes well above the squeeze run's highest high (100.05).
        rows.append(_make_ohlcv_row(close_time, 106.0, high=106.5, low=100.0))
        close_time += 3_600_000
        return pd.DataFrame(rows)

    def test_squeeze_streak_counts_consecutive_narrow_width_candles_ending_at_row(self) -> None:
        frame = self._squeeze_then_breakout_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS_MA200)

        last_squeeze_row = enriched.iloc[LAST_SQUEEZE_ROW]
        self.assertGreaterEqual(last_squeeze_row["squeeze_streak"], 5)

    def test_prior_squeeze_columns_are_shifted_no_lookahead(self) -> None:
        frame = self._squeeze_then_breakout_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS_MA200)

        breakout_row = enriched.iloc[BREAKOUT_ROW]
        last_squeeze_row = enriched.iloc[LAST_SQUEEZE_ROW]
        # the breakout row's "prior" columns must equal the PRECEDING row's own (current)
        # values — proving they only reflect information available before this candle.
        self.assertEqual(breakout_row["prior_squeeze_streak"], last_squeeze_row["squeeze_streak"])
        self.assertAlmostEqual(breakout_row["prior_squeeze_run_high"], 100.05, places=2)

    def test_first_row_prior_columns_have_no_undefined_lookback(self) -> None:
        frame = self._squeeze_then_breakout_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS_MA200)

        self.assertEqual(enriched.iloc[0]["prior_squeeze_streak"], 0)
        self.assertTrue(pd.isna(enriched.iloc[0]["prior_squeeze_run_high"]))

    def test_trend_ma_matches_rolling_mean_of_close_for_its_own_period(self) -> None:
        frame = self._squeeze_then_breakout_frame()
        enriched_200 = add_indicators(frame, DEFAULT_PARAMETERS_MA200)
        enriched_100 = add_indicators(frame, DEFAULT_PARAMETERS_MA100)

        expected_200 = frame["close"].rolling(200).mean()
        expected_100 = frame["close"].rolling(100).mean()
        pd.testing.assert_series_equal(enriched_200["trend_ma"], expected_200, check_names=False)
        pd.testing.assert_series_equal(enriched_100["trend_ma"], expected_100, check_names=False)

    def test_bb_width_formula(self) -> None:
        frame = self._squeeze_then_breakout_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS_MA200)
        row = enriched.iloc[LAST_SQUEEZE_ROW]
        expected_width = (row["bb_upper"] - row["bb_lower"]) / row["bb_middle"]
        self.assertAlmostEqual(row["bb_width"], expected_width, places=10)


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_passes_when_all_conditions_met(self) -> None:
        candle = make_candle(close=110.0, prior_squeeze_streak=6, prior_squeeze_run_high=109.5, trend_ma=95.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())

    def test_blocked_when_squeeze_streak_too_short(self) -> None:
        candle = make_candle(prior_squeeze_streak=3)  # min_squeeze_candles default is 5

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertFalse(evaluation.passed)
        self.assertIn("SQUEEZE_STREAK_TOO_SHORT", evaluation.reasons)

    def test_blocked_when_close_does_not_break_above_squeeze_high(self) -> None:
        candle = make_candle(close=109.0, prior_squeeze_streak=6, prior_squeeze_run_high=109.5)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_SQUEEZE_HIGH", evaluation.reasons)
        self.assertNotIn("SQUEEZE_STREAK_TOO_SHORT", evaluation.reasons)

    def test_blocked_by_trend_filter(self) -> None:
        candle = make_candle(close=110.0, trend_ma=120.0)  # close below trend MA

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_TREND_MA", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        from nero_core.strategies.volatility_squeeze import OpenTrade

        self.state.open_trade = OpenTrade(
            entry_price=100.0, stop_loss=98.0, target=104.0, quantity=1.0, notional=100.0,
            risk_dollars=2.0, entry_fee=0.1, open_close_time=0, entry_atr=2.0,
            entry_trend_ma=90.0, entry_bb_width=0.02, entry_squeeze_streak=6,
            entry_squeeze_run_high=99.0,
        )
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_daily_loss_guard_blocks_entry(self) -> None:
        self.state.daily_r = -5.0
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)

    def test_all_failing_reasons_are_reported_not_just_the_first(self) -> None:
        candle = make_candle(close=100.0, prior_squeeze_streak=1, prior_squeeze_run_high=109.5, trend_ma=120.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertIn("SQUEEZE_STREAK_TOO_SHORT", evaluation.reasons)
        self.assertIn("CLOSE_NOT_ABOVE_SQUEEZE_HIGH", evaluation.reasons)
        self.assertIn("CLOSE_NOT_ABOVE_TREND_MA", evaluation.reasons)

    def test_trend_filter_period_is_the_only_thing_that_differs_across_variants(self) -> None:
        # Same candle, same trend_ma value (as if pre-computed for a specific variant) —
        # evaluate_entry itself doesn't know which MA period produced "trend_ma"; the
        # period only matters at add_indicators time. This proves a candle sitting
        # between two different trend MAs is blocked by the stricter one and passed by
        # the looser one, i.e. the three variants CAN diverge on the same market data.
        candle_blocked_by_ma200_only = make_candle(close=110.0, trend_ma=112.0)  # close < 112
        evaluation = evaluate_entry(candle_blocked_by_ma200_only, self.state, DEFAULT_PARAMETERS_MA200)
        self.assertIn("CLOSE_NOT_ABOVE_TREND_MA", evaluation.reasons)

        candle_passed_by_ma100 = make_candle(close=110.0, trend_ma=108.0)  # close > 108
        evaluation = evaluate_entry(candle_passed_by_ma100, self.state, DEFAULT_PARAMETERS_MA100)
        self.assertNotIn("CLOSE_NOT_ABOVE_TREND_MA", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_stop_is_1_5x_atr_below_entry(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.entry_price - trade.stop_loss, 1.5 * 2.0, places=6)

    def test_target_is_2_0x_atr_above_entry(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.target - trade.entry_price, 2.0 * 2.0, places=6)

    def test_returns_none_when_atr_is_zero(self) -> None:
        candle = make_candle(atr=0.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS_MA200)

        self.assertIsNone(trade)

    def test_notional_capped_by_max_notional_pct(self) -> None:
        params = VolatilitySqueezeParameters(max_notional_pct=0.5, risk_per_trade=0.5)
        candle = make_candle(atr=0.01)  # tiny stop distance -> huge uncapped quantity

        trade = size_entry(candle, self.state, params)

        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, self.state.equity * 0.5 + 1e-6)


class ExitReuseTest(unittest.TestCase):
    """Proves VOLATILITY_SQUEEZE's OpenTrade duck-types correctly against the shared
    evaluate_exit from mean_reversion.py (same pattern as BREAKOUT_MOMENTUM)."""

    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_target_exit(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS_MA200)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.target + 1.0, low=entry.stop_loss + 0.1, close=entry.target),
            self.state,
            DEFAULT_PARAMETERS_MA200,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TARGET")

    def test_stop_exit(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS_MA200)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.target - 0.1, low=entry.stop_loss - 1.0, close=entry.stop_loss),
            self.state,
            DEFAULT_PARAMETERS_MA200,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")

    def test_time_exit_after_max_holding_hours(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS_MA200)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(
                close_time=3600000 + 24 * 3600000,
                high=entry.target - 0.1,
                low=entry.stop_loss + 0.1,
                close=entry.entry_price,
            ),
            self.state,
            DEFAULT_PARAMETERS_MA200,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")


class TimeframeHelperTest(unittest.TestCase):
    def test_hours_per_timeframe_covers_the_standard_set(self) -> None:
        self.assertEqual(HOURS_PER_TIMEFRAME, {"2h": 2, "4h": 4, "12h": 12, "24h": 24, "1week": 168})

    def test_max_holding_hours_preserves_24_candle_cap_across_timeframes(self) -> None:
        self.assertEqual(max_holding_hours_for_timeframe("2h"), 48)
        self.assertEqual(max_holding_hours_for_timeframe("4h"), 96)
        self.assertEqual(max_holding_hours_for_timeframe("12h"), 288)
        self.assertEqual(max_holding_hours_for_timeframe("24h"), 576)
        self.assertEqual(max_holding_hours_for_timeframe("1week"), 4032)

    def test_unknown_timeframe_raises_keyerror_not_silent_default(self) -> None:
        with self.assertRaises(KeyError):
            max_holding_hours_for_timeframe("30min")


class GoldFeeConventionTest(unittest.TestCase):
    def test_gold_calibrated_fees_scales_both_fee_and_slippage(self) -> None:
        scaled = gold_calibrated_fees(DEFAULT_PARAMETERS_MA200)

        self.assertLess(scaled.fee_bps, DEFAULT_PARAMETERS_MA200.fee_bps)
        self.assertLess(scaled.slippage_bps, DEFAULT_PARAMETERS_MA200.slippage_bps)

    def test_gold_calibrated_fees_only_changes_fee_and_slippage(self) -> None:
        scaled = gold_calibrated_fees(DEFAULT_PARAMETERS_MA200)
        for field in fields(DEFAULT_PARAMETERS_MA200):
            if field.name in {"fee_bps", "slippage_bps"}:
                continue
            self.assertEqual(getattr(scaled, field.name), getattr(DEFAULT_PARAMETERS_MA200, field.name))

    def test_build_params_for_run_applies_gold_fees_only_for_gold(self) -> None:
        crypto_params = build_params_for_run(DEFAULT_PARAMETERS_MA200, "4h", "BTC")
        gold_params = build_params_for_run(DEFAULT_PARAMETERS_MA200, "4h", "GOLD")

        self.assertEqual(crypto_params.fee_bps, DEFAULT_PARAMETERS_MA200.fee_bps)
        self.assertLess(gold_params.fee_bps, DEFAULT_PARAMETERS_MA200.fee_bps)

    def test_build_params_for_run_always_applies_timeframe_holding_cap(self) -> None:
        crypto_params = build_params_for_run(DEFAULT_PARAMETERS_MA200, "1week", "BTC")
        gold_params = build_params_for_run(DEFAULT_PARAMETERS_MA200, "1week", "GOLD")

        self.assertEqual(crypto_params.max_holding_hours, 4032)
        self.assertEqual(gold_params.max_holding_hours, 4032)


class RegistrationTest(unittest.TestCase):
    def test_register_all_variants_registers_three_distinct_versions_simultaneously(self) -> None:
        registry = StrategyRegistry()

        ma200, ma150, ma100 = register_all_variants(registry)

        self.assertEqual({ma200.version, ma150.version, ma100.version}, {
            "volatility-squeeze-v1.0.0-ma200",
            "volatility-squeeze-v1.0.0-ma150",
            "volatility-squeeze-v1.0.0-ma100",
        })
        for variant in (ma200, ma150, ma100):
            self.assertEqual(variant.strategy_id, STRATEGY_ID)
        versions = {v.version for v in registry.list_versions(STRATEGY_ID)}
        self.assertEqual(len(versions), 3)

    def test_registering_the_same_variant_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_ma200_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_ma200_variant(registry)

    def test_registering_all_three_individually_matches_register_all_variants(self) -> None:
        registry_a = StrategyRegistry()
        register_ma200_variant(registry_a)
        register_ma150_variant(registry_a)
        register_ma100_variant(registry_a)

        registry_b = StrategyRegistry()
        register_all_variants(registry_b)

        self.assertEqual(
            {v.version for v in registry_a.list_versions(STRATEGY_ID)},
            {v.version for v in registry_b.list_versions(STRATEGY_ID)},
        )

    def test_only_trend_ma_period_differs_between_the_three_variants(self) -> None:
        for field in fields(DEFAULT_PARAMETERS_MA200):
            v200 = getattr(DEFAULT_PARAMETERS_MA200, field.name)
            v150 = getattr(DEFAULT_PARAMETERS_MA150, field.name)
            v100 = getattr(DEFAULT_PARAMETERS_MA100, field.name)
            if field.name == "trend_ma_period":
                self.assertEqual((v200, v150, v100), (200, 150, 100))
            else:
                self.assertEqual(v200, v150, f"{field.name} should match between ma200/ma150")
                self.assertEqual(v150, v100, f"{field.name} should match between ma150/ma100")


if __name__ == "__main__":
    unittest.main()
