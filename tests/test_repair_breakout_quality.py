from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies import repair_breakout_quality as rbq
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _candles(rows: list[tuple[float, float, float, float]], start: str = "2024-01-01", hours: int = 4) -> pd.DataFrame:
    """rows: list of (open, high, low, close), one candle every `hours` hours."""
    out = []
    ts = pd.Timestamp(start, tz="UTC")
    for i, (o, h, l, c) in enumerate(rows):
        moment = ts + pd.Timedelta(hours=hours * i)
        close_time = int(moment.timestamp() * 1000)
        out.append({
            "date": moment, "open_time": close_time - hours * 3_600_000, "close_time": close_time,
            "open": o, "high": h, "low": l, "close": c, "volume": 1000.0,
        })
    return pd.DataFrame(out)


def _entry_candle(close_time, close, low=None, breakout_high=100.0, ma20=104.0, ma200=100.0, atr=2.0, atr_pct=0.02):
    return pd.Series({
        "close_time": close_time, "close": close, "low": low if low is not None else close,
        "breakout_high": breakout_high, "ma20": ma20, "ma200": ma200, "atr": atr, "atr_pct": atr_pct,
    })


class AddIndicatorsNoLookaheadTest(unittest.TestCase):
    def test_breakout_high_excludes_current_candle(self) -> None:
        rows = [(10, 10, 9, 10), (11, 11, 10, 11), (12, 12, 11, 12), (13, 13, 12, 13), (14, 14, 13, 14)]
        params = rbq.RepairBreakoutParameters(breakout_lookback=3)
        enriched = rbq.add_indicators(_candles(rows), params)
        self.assertEqual(enriched.iloc[4]["breakout_high"], 13.0)


class EvaluateEntryStateMachineTest(unittest.TestCase):
    def _params(self) -> rbq.RepairBreakoutParameters:
        return rbq.RepairBreakoutParameters(retest_window=10)

    def test_breakout_with_regime_support_arms_a_pending_setup(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        params = self._params()
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0)
        result = rbq.evaluate_entry(candle, state, params)

        self.assertFalse(result.passed)
        self.assertEqual(result.action, "ARMED")
        self.assertIsNotNone(state.pending)
        self.assertEqual(state.pending.breakout_level, 102.8)
        self.assertEqual(state.pending.candles_remaining, params.retest_window)
        self.assertFalse(state.pending.confirmed)

    def test_no_breakout_does_not_arm(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = _entry_candle(1000, close=100.0, breakout_high=102.8)  # close below the breakout threshold
        result = rbq.evaluate_entry(candle, state, self._params())
        self.assertFalse(result.passed)
        self.assertIn("NO_BREAKOUT", result.reasons)
        self.assertIsNone(state.pending)

    def test_breakout_blocked_by_ma200_filter(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=110.0)  # close < ma200
        result = rbq.evaluate_entry(candle, state, self._params())
        self.assertFalse(result.passed)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", result.reasons)
        self.assertIsNone(state.pending)

    def test_breakout_blocked_by_ma20_not_above_ma200(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=99.0, ma200=100.0)
        result = rbq.evaluate_entry(candle, state, self._params())
        self.assertFalse(result.passed)
        self.assertIn("MA20_NOT_ABOVE_MA200", result.reasons)
        self.assertIsNone(state.pending)

    def test_breakout_blocked_by_atr_pct_cap(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0, atr_pct=0.06)
        result = rbq.evaluate_entry(candle, state, rbq.RepairBreakoutParameters(atr_pct_max=0.04))
        self.assertFalse(result.passed)
        self.assertIn("ATR_PCT_TOO_HIGH", result.reasons)
        self.assertIsNone(state.pending)

    def test_open_trade_exists_blocks_new_arming(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        state.open_trade = rbq.OpenTrade(
            entry_price=100.0, stop_loss=98.0, target=103.0, quantity=1.0, notional=100.0,
            risk_dollars=2.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0, entry_breakout_level=99.0,
        )
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8)
        result = rbq.evaluate_entry(candle, state, self._params())
        self.assertFalse(result.passed)
        self.assertIn("OPEN_TRADE_EXISTS", result.reasons)
        self.assertIsNone(state.pending)

    def test_daily_loss_guard_blocks_arming(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0, daily_r=-5.0)
        candle = _entry_candle(1000, close=105.0, breakout_high=102.8)
        result = rbq.evaluate_entry(candle, state, self._params())
        self.assertFalse(result.passed)
        self.assertIn("DAILY_LOSS_GUARD", result.reasons)

    def test_full_arm_confirm_enter_sequence(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        params = self._params()

        breakout = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0)
        armed = rbq.evaluate_entry(breakout, state, params)
        self.assertEqual(armed.action, "ARMED")

        # Low never touches the breakout level -- still awaiting, no entry.
        no_retest = _entry_candle(2000, close=106.0, low=105.5)
        awaiting = rbq.evaluate_entry(no_retest, state, params)
        self.assertFalse(awaiting.passed)
        self.assertEqual(awaiting.action, "NONE")
        self.assertIn("AWAITING_RETEST", awaiting.reasons)
        self.assertEqual(state.pending.candles_remaining, params.retest_window - 1)

        # Low touches the breakout level, close finishes back above it -- confirmed.
        retest = _entry_candle(3000, close=103.5, low=102.0)
        confirmed = rbq.evaluate_entry(retest, state, params)
        self.assertFalse(confirmed.passed)
        self.assertEqual(confirmed.action, "CONFIRMED")
        self.assertTrue(state.pending.confirmed)

        # Entry happens on the candle AFTER confirmation, never on the confirmation
        # candle itself.
        entry_candle = _entry_candle(4000, close=104.5, ma20=104.0, ma200=103.0)
        entered = rbq.evaluate_entry(entry_candle, state, params)
        self.assertTrue(entered.passed)
        self.assertEqual(entered.action, "ENTER")
        self.assertEqual(entered.breakout_level, 102.8)
        self.assertIsNone(state.pending)

    def test_confirmation_candle_itself_never_enters(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        params = self._params()
        breakout = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0)
        rbq.evaluate_entry(breakout, state, params)
        retest = _entry_candle(3000, close=103.5, low=102.0)
        confirmed = rbq.evaluate_entry(retest, state, params)
        self.assertFalse(confirmed.passed)

    def test_pending_setup_expires_after_retest_window(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        params = rbq.RepairBreakoutParameters(retest_window=2)
        breakout = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0)
        rbq.evaluate_entry(breakout, state, params)
        self.assertEqual(state.pending.candles_remaining, 2)

        no_retest = _entry_candle(2000, close=106.0, low=105.5)
        rbq.evaluate_entry(no_retest, state, params)
        self.assertIsNotNone(state.pending)

        expired = rbq.evaluate_entry(no_retest, state, params)
        self.assertEqual(expired.action, "NONE")
        self.assertIn("PENDING_BREAKOUT_EXPIRED", expired.reasons)
        self.assertIsNone(state.pending)

    def test_regime_flip_between_confirmation_and_entry_candle_blocks_entry(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        params = self._params()
        breakout = _entry_candle(1000, close=105.0, breakout_high=102.8, ma20=104.0, ma200=100.0)
        rbq.evaluate_entry(breakout, state, params)
        retest = _entry_candle(3000, close=103.5, low=102.0)
        rbq.evaluate_entry(retest, state, params)

        # Trend reversed by the time the entry candle arrives.
        flipped = _entry_candle(4000, close=95.0, ma20=96.0, ma200=100.0)
        result = rbq.evaluate_entry(flipped, state, params)
        self.assertFalse(result.passed)
        self.assertIn("REGIME_FLIPPED_SINCE_CONFIRMATION", result.reasons)
        self.assertIsNone(state.pending)  # consumed, not left dangling


class SizeEntryTest(unittest.TestCase):
    def test_stop_is_one_atr_target_is_fixed_1_5r(self) -> None:
        params = rbq.RepairBreakoutParameters(atr_stop_multiple=1.0, target_r_multiple=1.5, slippage_bps=0.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = pd.Series({"close_time": 4000, "close": 104.5, "atr": 2.0})
        trade = rbq.size_entry(candle, state, params, breakout_level=102.8)

        self.assertEqual(trade.entry_price, 104.5)
        self.assertAlmostEqual(trade.stop_loss, 102.5, places=6)
        risk_distance = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(risk_distance, 2.0, places=6)
        self.assertAlmostEqual(trade.target - trade.entry_price, 1.5 * risk_distance, places=6)
        self.assertEqual(trade.entry_breakout_level, 102.8)


class EvaluateExitNoGapToleranceTest(unittest.TestCase):
    def _open_trade(self) -> rbq.OpenTrade:
        return rbq.OpenTrade(
            entry_price=100.0, stop_loss=95.0, target=107.5, quantity=1.0, notional=100.0,
            risk_dollars=5.0, entry_fee=0.0, open_close_time=0, entry_atr=5.0, entry_breakout_level=90.0,
        )

    def test_same_bar_wick_reclaim_fills_at_exact_stop_price(self) -> None:
        params = rbq.RepairBreakoutParameters(slippage_bps=0.0, fee_bps=0.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        state.open_trade = self._open_trade()
        # Low touches the stop, but the candle recovers and closes back above it.
        candle = pd.Series({"close_time": 3_600_000, "open": 99.0, "low": 94.0, "high": 99.5, "close": 98.0})
        event = rbq.evaluate_exit(candle, state, params)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")
        self.assertEqual(event.exit_price, 95.0)

    def test_candle_closing_through_stop_defers_to_next_candles_open(self) -> None:
        params = rbq.RepairBreakoutParameters(slippage_bps=0.0, fee_bps=0.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        trade = self._open_trade()
        state.open_trade = trade
        # The whole candle breaks through the stop and STAYS through it at close.
        gap_candle = pd.Series({"close_time": 3_600_000, "open": 96.0, "low": 88.0, "high": 96.5, "close": 89.0})
        event = rbq.evaluate_exit(gap_candle, state, params)

        self.assertIsNone(event)  # no fill realized yet this candle
        self.assertTrue(trade.gap_pending)
        self.assertIsNotNone(state.open_trade)  # still open, not yet closed

        next_candle = pd.Series({"close_time": 7_200_000, "open": 85.0, "low": 83.0, "high": 90.0, "close": 87.0})
        event2 = rbq.evaluate_exit(next_candle, state, params)
        self.assertIsNotNone(event2)
        self.assertEqual(event2.exit_reason, "SL_GAP")
        self.assertEqual(event2.exit_price, 85.0)  # next candle's OPEN, never clipped to the stop price
        r_multiple = (85.0 - 100.0) * 1.0 / 5.0  # -3.0R, deliberately worse than -1.0R
        self.assertAlmostEqual(event2.r_multiple, r_multiple, places=6)
        self.assertLess(event2.r_multiple, -1.0)

    def test_stop_takes_priority_over_target_in_the_same_candle(self) -> None:
        params = rbq.RepairBreakoutParameters(slippage_bps=0.0, fee_bps=0.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        state.open_trade = self._open_trade()
        candle = pd.Series({"close_time": 3_600_000, "open": 100.0, "low": 90.0, "high": 110.0, "close": 105.0})
        event = rbq.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "SL")

    def test_target_hit_fills_at_target_price(self) -> None:
        params = rbq.RepairBreakoutParameters(slippage_bps=0.0, fee_bps=0.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        state.open_trade = self._open_trade()
        candle = pd.Series({"close_time": 3_600_000, "open": 101.0, "low": 100.0, "high": 108.0, "close": 107.0})
        event = rbq.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "TARGET")
        self.assertEqual(event.exit_price, 107.5)

    def test_time_exit_fires_past_holding_cap(self) -> None:
        params = rbq.RepairBreakoutParameters(slippage_bps=0.0, fee_bps=0.0, max_holding_hours=1.0)
        state = rbq.RepairBreakoutState(equity=10000.0)
        state.open_trade = self._open_trade()
        candle = pd.Series({"close_time": 2 * 3_600_000, "open": 100.0, "low": 99.0, "high": 101.0, "close": 100.5})
        event = rbq.evaluate_exit(candle, state, params)
        self.assertEqual(event.exit_reason, "TIME")

    def test_no_open_trade_returns_none(self) -> None:
        state = rbq.RepairBreakoutState(equity=10000.0)
        candle = pd.Series({"close_time": 0, "open": 100.0, "low": 99.0, "high": 101.0, "close": 100.0})
        self.assertIsNone(rbq.evaluate_exit(candle, state, rbq.RepairBreakoutParameters()))


class RunRepairBreakoutBacktestTest(unittest.TestCase):
    def test_end_to_end_arm_retest_enter_and_hit_target(self) -> None:
        # Compact periods purely to keep this test's warmup short -- see
        # test_donchian_breakout_bracket.py's identical convention. Gentle uptrend
        # warmup (rows 0-5) keeps close > MA200 and MA20 > MA200 throughout.
        rows = [
            (100.0, 104.0, 99.7, 100.0),    # warmup: wide upper wicks keep breakout_high
            (100.5, 104.5, 100.2, 100.5),   # elevated above the gently-rising closes, so
            (101.0, 105.0, 100.7, 101.0),   # none of these candles falsely self-trigger a
            (101.5, 105.5, 101.2, 101.5),   # breakout before the intended one below.
            (102.0, 106.0, 101.7, 102.0),
            (102.5, 106.5, 102.2, 102.5),
            (103.0, 112.0, 102.0, 110.0),   # breakout candle (close > prior-3 high of 106.5)
            (109.0, 110.0, 104.0, 108.0),   # retest: low touches 106.5, closes back above -- confirmed
            (108.5, 109.5, 107.5, 109.0),   # entry candle (the one AFTER confirmation)
            (109.0, 140.0, 108.0, 138.0),   # big follow-through -- should clear the 1.5R target
        ]
        params = rbq.RepairBreakoutParameters(
            breakout_lookback=3, ma20_period=2, ma200_period=5, atr_period=2,
            retest_window=3, atr_pct_max=1.0, slippage_bps=0.0, fee_bps=0.0,
        )
        trades, _state = rbq.run_repair_breakout_backtest(_candles(rows), params)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "TARGET")
        self.assertGreater(trades[0].r_multiple, 0)


class RegistryTest(unittest.TestCase):
    def test_register_default_variant_works(self) -> None:
        registry = StrategyRegistry()
        variant = rbq.register_default_variant(registry)
        self.assertEqual(variant.strategy_id, rbq.STRATEGY_ID)
        self.assertEqual(variant.version, rbq.STRATEGY_VERSION)

    def test_reregistering_same_version_raises(self) -> None:
        registry = StrategyRegistry()
        rbq.register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            rbq.register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
