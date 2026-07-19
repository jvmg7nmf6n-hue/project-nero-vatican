from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.range_mean_reversion import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    OpenTrade,
    RangeMeanReversionState,
    add_indicators,
    adx,
    evaluate_entry,
    evaluate_exit,
    range_eligible_mask,
    register_default_variant,
    run_backtest,
    size_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _make_candle(close_time=0, close=100.0, high=None, low=None, sma20=100.0,
                  bb_lower=95.0, bb_upper=105.0, adx=20.0, atr_value=2.0) -> pd.Series:
    high = high if high is not None else close + 1
    low = low if low is not None else close - 1
    return pd.Series({
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "close": close,
        "high": high,
        "low": low,
        "sma20": sma20,
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "adx": adx,
        "atr": atr_value,
    })


def _ohlc_row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "volume": 100.0,
    }


def _ranging_series(n: int = 120) -> pd.DataFrame:
    """Oscillates in a tight, bounded range — should produce LOW ADX."""
    rows = []
    close_time = 0
    for i in range(n):
        close = 100.0 + (2.0 if i % 2 == 0 else -2.0)
        rows.append(_ohlc_row(close_time, close, high=close + 0.5, low=close - 0.5))
        close_time += 3_600_000
    return pd.DataFrame(rows)


def _trending_series(n: int = 120) -> pd.DataFrame:
    """A sustained, strong directional move with expanding true range — should
    produce HIGH ADX."""
    rows = []
    close_time = 0
    price = 100.0
    for i in range(n):
        price += 2.0
        rows.append(_ohlc_row(close_time, price, high=price + 1.5, low=price - 0.2))
        close_time += 3_600_000
    return pd.DataFrame(rows)


class AdxRegimeGateTest(unittest.TestCase):
    def test_ranging_series_scores_low_adx(self) -> None:
        candles = _ranging_series()
        values = adx(candles, period=14).dropna()
        self.assertGreater(len(values), 0)
        self.assertLess(values.iloc[-1], 25.0)

    def test_trending_series_scores_high_adx(self) -> None:
        candles = _trending_series()
        values = adx(candles, period=14).dropna()
        self.assertGreater(len(values), 0)
        self.assertGreaterEqual(values.iloc[-1], 25.0)

    def test_insufficient_history_returns_nan(self) -> None:
        candles = _ranging_series(n=5)
        values = adx(candles, period=14)
        self.assertTrue(values.isna().all())


class AddIndicatorsTest(unittest.TestCase):
    def test_produces_all_required_columns(self) -> None:
        enriched = add_indicators(_ranging_series())
        for col in ("sma20", "bb_lower", "bb_upper", "bb_width_pct", "adx", "atr"):
            self.assertIn(col, enriched.columns)

    def test_bb_width_pct_is_secondary_only_not_used_by_entry(self) -> None:
        # Sanity: bb_width_pct exists and is non-negative wherever bands are defined,
        # but evaluate_entry (tested below) never reads it — only adx and the bands.
        enriched = add_indicators(_ranging_series()).dropna(subset=["bb_width_pct"])
        self.assertTrue((enriched["bb_width_pct"] >= 0).all())


class EvaluateEntryTest(unittest.TestCase):
    def test_long_entry_when_close_below_lower_band_and_ranging(self) -> None:
        candle = _make_candle(close=90.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_short_entry_when_close_above_upper_band_and_ranging(self) -> None:
        candle = _make_candle(close=110.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")

    def test_no_entry_when_trending_even_with_band_breach(self) -> None:
        candle = _make_candle(close=90.0, adx=30.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_RANGING", evaluation.reasons)

    def test_no_entry_at_exactly_the_adx_entry_threshold(self) -> None:
        candle = _make_candle(close=90.0, adx=25.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("NOT_RANGING", evaluation.reasons)

    def test_no_entry_without_a_band_breach(self) -> None:
        candle = _make_candle(close=100.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("NO_BAND_BREACH", evaluation.reasons)

    def test_rejected_when_open_trade_exists(self) -> None:
        candle = _make_candle(close=90.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0, open_trade=OpenTrade(
            direction="LONG", entry_price=100.0, stop_loss=95.0, quantity=1.0, notional=100.0,
            risk_dollars=5.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0,
        ))
        evaluation = evaluate_entry(candle, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_adx_unavailable_rejects_without_crashing(self) -> None:
        candle = _make_candle(close=90.0, adx=float("nan"))
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("ADX_NOT_AVAILABLE", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_long_stop_below_entry(self) -> None:
        candle = _make_candle(close=90.0)
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_entry(candle, state, direction="LONG")
        self.assertLess(trade.stop_loss, trade.entry_price)

    def test_short_stop_above_entry(self) -> None:
        candle = _make_candle(close=110.0)
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_entry(candle, state, direction="SHORT")
        self.assertGreater(trade.stop_loss, trade.entry_price)

    def test_risk_dollars_matches_one_percent_of_equity(self) -> None:
        candle = _make_candle(close=90.0)
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_entry(candle, state, direction="LONG")
        self.assertAlmostEqual(trade.risk_dollars, 100.0)

    def test_zero_atr_returns_none(self) -> None:
        candle = _make_candle(close=90.0, atr_value=0.0)
        state = RangeMeanReversionState(equity=10000.0)
        self.assertIsNone(size_entry(candle, state, direction="LONG"))


class EvaluateExitTest(unittest.TestCase):
    def _open_long(self, entry_price=100.0, stop_loss=96.0) -> RangeMeanReversionState:
        trade = OpenTrade(direction="LONG", entry_price=entry_price, stop_loss=stop_loss, quantity=1.0,
                           notional=entry_price, risk_dollars=4.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0)
        return RangeMeanReversionState(equity=10000.0, open_trade=trade)

    def _open_short(self, entry_price=100.0, stop_loss=104.0) -> RangeMeanReversionState:
        trade = OpenTrade(direction="SHORT", entry_price=entry_price, stop_loss=stop_loss, quantity=1.0,
                           notional=entry_price, risk_dollars=4.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0)
        return RangeMeanReversionState(equity=10000.0, open_trade=trade)

    def test_no_open_trade_returns_none_and_still_updates_the_raw_adx_counter(self) -> None:
        # The counter tracks the raw ADX>=threshold condition unconditionally, whether
        # or not a trade is open — this is safe (not a source of premature
        # regime-break firing right after a new entry) because entry only ever
        # happens when ADX < 25 < 28, which always resets this same counter to 0 on
        # the very candle entry fires, before size_entry runs.
        state = RangeMeanReversionState(equity=10000.0)
        candle = _make_candle(close_time=3_600_000, close=100.0, adx=30.0)
        self.assertIsNone(evaluate_exit(candle, state))
        self.assertEqual(state.consecutive_high_adx_bars, 1)

    def test_counter_resets_to_zero_on_the_entry_candle_because_entry_requires_low_adx(self) -> None:
        state = RangeMeanReversionState(equity=10000.0)
        state.consecutive_high_adx_bars = 1  # leftover from a prior trending stretch while flat
        candle = _make_candle(close_time=3_600_000, close=100.0, adx=20.0)  # ranging -> entry-eligible
        self.assertIsNone(evaluate_exit(candle, state))
        self.assertEqual(state.consecutive_high_adx_bars, 0)

    def test_long_stop_loss_exit(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=96.0)
        candle = _make_candle(close_time=3_600_000, close=95.0, low=94.0, sma20=100.0, adx=20.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "STOP")

    def test_short_stop_loss_exit(self) -> None:
        state = self._open_short(entry_price=100.0, stop_loss=104.0)
        candle = _make_candle(close_time=3_600_000, close=105.0, high=106.0, sma20=100.0, adx=20.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "STOP")

    def test_long_reversion_target_exit_on_sma_cross(self) -> None:
        state = self._open_long(entry_price=90.0, stop_loss=86.0)
        candle = _make_candle(close_time=3_600_000, close=100.5, high=101.0, low=100.0, sma20=100.0, adx=15.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REVERSION_TARGET")

    def test_short_reversion_target_exit_on_sma_cross(self) -> None:
        state = self._open_short(entry_price=110.0, stop_loss=114.0)
        candle = _make_candle(close_time=3_600_000, close=99.5, high=100.5, low=99.0, sma20=100.0, adx=15.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REVERSION_TARGET")

    def test_stop_takes_priority_over_regime_break_and_target(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=96.0)
        state.consecutive_high_adx_bars = 1  # one bar away from regime-break
        candle = _make_candle(close_time=3_600_000, close=101.0, low=94.0, sma20=100.0, adx=30.0)
        event = evaluate_exit(candle, state)
        self.assertEqual(event.exit_reason, "STOP")

    def test_regime_break_does_not_fire_on_a_single_high_adx_touch(self) -> None:
        state = self._open_long(entry_price=90.0, stop_loss=86.0)
        candle = _make_candle(close_time=3_600_000, close=91.0, low=90.5, sma20=100.0, adx=28.0)
        event = evaluate_exit(candle, state)
        self.assertIsNone(event)
        self.assertEqual(state.consecutive_high_adx_bars, 1)

    def test_regime_break_fires_on_two_consecutive_high_adx_bars(self) -> None:
        state = self._open_long(entry_price=90.0, stop_loss=86.0)
        candle1 = _make_candle(close_time=3_600_000, close=91.0, low=90.5, sma20=100.0, adx=28.0)
        self.assertIsNone(evaluate_exit(candle1, state))
        self.assertEqual(state.consecutive_high_adx_bars, 1)

        candle2 = _make_candle(close_time=7_200_000, close=92.0, low=91.5, sma20=100.0, adx=29.0)
        event = evaluate_exit(candle2, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REGIME_BREAK")

    def test_high_adx_counter_resets_if_it_drops_back_below_threshold(self) -> None:
        state = self._open_long(entry_price=90.0, stop_loss=86.0)
        candle1 = _make_candle(close_time=3_600_000, close=91.0, low=90.5, sma20=100.0, adx=28.0)
        evaluate_exit(candle1, state)
        self.assertEqual(state.consecutive_high_adx_bars, 1)

        candle_dip = _make_candle(close_time=7_200_000, close=91.5, low=91.0, sma20=100.0, adx=20.0)
        evaluate_exit(candle_dip, state)
        self.assertEqual(state.consecutive_high_adx_bars, 0)

        candle3 = _make_candle(close_time=10_800_000, close=92.0, low=91.5, sma20=100.0, adx=28.0)
        event = evaluate_exit(candle3, state)
        self.assertIsNone(event)  # only 1 consecutive bar again, not 2
        self.assertEqual(state.consecutive_high_adx_bars, 1)

    def test_short_accounting_matches_short_momentum_convention(self) -> None:
        # entry 100 short, exit 90 -> profit for a short: gross_pnl = (entry - exit) * qty
        state = self._open_short(entry_price=100.0, stop_loss=104.0)
        state.open_trade.quantity = 2.0
        candle = _make_candle(close_time=3_600_000, close=99.0, high=99.5, low=98.5, sma20=100.0, adx=15.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertGreater(event.gross_pnl, 0.0)  # short profits when price falls
        self.assertAlmostEqual(event.gross_pnl, (100.0 - event.exit_price) * 2.0)


class RunBacktestSmokeTest(unittest.TestCase):
    def test_runs_end_to_end_without_error_on_ranging_data(self) -> None:
        candles = _ranging_series(n=300)
        from nero_core.strategies.range_mean_reversion import add_indicators as _add
        enriched = _add(candles)
        evaluable = enriched.dropna(subset=["sma20", "bb_lower", "bb_upper", "adx", "atr"]).reset_index(drop=True)
        trades, state = run_backtest(evaluable)
        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, 0.0)


class RangeEligibleMaskTest(unittest.TestCase):
    def test_mask_matches_adx_below_entry_threshold(self) -> None:
        evaluable = pd.DataFrame({"adx": [10.0, 24.9, 25.0, 30.0]})
        mask = range_eligible_mask(evaluable)
        self.assertEqual(mask.tolist(), [True, True, False, False])


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_default_parameters_match_task_spec(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.adx_entry_threshold, 25.0)
        self.assertEqual(DEFAULT_PARAMETERS.adx_exit_threshold, 28.0)
        self.assertEqual(DEFAULT_PARAMETERS.adx_exit_consecutive_bars, 2)
        self.assertEqual(DEFAULT_PARAMETERS.atr_stop_multiple, 2.0)
        self.assertEqual(DEFAULT_PARAMETERS.risk_per_trade, 0.01)
        self.assertFalse(hasattr(DEFAULT_PARAMETERS, "max_holding_hours"))


if __name__ == "__main__":
    unittest.main()
