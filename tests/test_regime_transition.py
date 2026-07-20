from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.regime_transition import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    OpenTrade,
    PendingSignal,
    RegimeTransitionParameters,
    RegimeTransitionState,
    _update_streak_and_detect_transition,
    add_indicators,
    evaluate_exit,
    register_default_variant,
    run_backtest,
    size_transition_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _row(close_time: int, close: float, high: float | None = None, low: float | None = None,
         open_: float | None = None, adx: float = 20.0, atr_value: float = 2.0) -> dict:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "adx": adx,
        "atr": atr_value,
    }


def _candle(**kwargs) -> pd.Series:
    return pd.Series(_row(**kwargs))


class StreakAndTransitionDetectionTest(unittest.TestCase):
    def test_streak_starts_and_grows_while_ranging(self) -> None:
        frame = pd.DataFrame([_row(i * 3_600_000, 100.0, adx=20.0) for i in range(5)])
        state = RegimeTransitionState(equity=10000.0)
        for i in range(5):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertEqual(state.streak_start_index, 0)
        self.assertIsNone(state.pending_signal)

    def test_streak_resets_on_high_adx_without_mature_range(self) -> None:
        # Only 3 low-ADX candles precede the ADX spike -- far short of the 10 required.
        rows = [_row(i * 3_600_000, 100.0, adx=20.0) for i in range(3)]
        rows.append(_row(3 * 3_600_000, 120.0, high=121.0, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0)
        for i in range(4):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNone(state.pending_signal)
        self.assertIsNone(state.streak_start_index)

    def test_mature_range_transition_fires_long_when_close_breaks_above_frozen_high(self) -> None:
        # 10 ranging candles (indices 0-9) between 99 and 101, then a transition
        # candle (index 10) with ADX >= 25 closing above the frozen range_high.
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 105.0, high=105.5, low=104.0, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0)
        for i in range(11):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(state.pending_signal)
        self.assertEqual(state.pending_signal.direction, "LONG")
        # Frozen boundary excludes the transition candle (index 10) itself.
        window_high = frame.iloc[0:10]["high"].max()
        self.assertAlmostEqual(state.pending_signal.range_high, window_high)
        self.assertAlmostEqual(state.pending_signal.breakout_close, 105.0)
        self.assertIsNone(state.streak_start_index)  # streak broken after the transition

    def test_mature_range_transition_fires_short_when_close_breaks_below_frozen_low(self) -> None:
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 95.0, high=96.0, low=94.5, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0)
        for i in range(11):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(state.pending_signal)
        self.assertEqual(state.pending_signal.direction, "SHORT")

    def test_no_transition_when_close_stays_inside_frozen_range(self) -> None:
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 100.2, high=100.5, low=99.8, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0)
        for i in range(11):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNone(state.pending_signal)

    def test_no_transition_while_a_trade_is_already_open(self) -> None:
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 105.0, high=105.5, low=104.0, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0, open_trade=OpenTrade(
            direction="LONG", entry_price=100.0, stop_loss=98.0, target=110.0, quantity=1.0,
            notional=100.0, risk_dollars=2.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0,
            stop_type="midpoint",
        ))
        for i in range(11):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNone(state.pending_signal)

    def test_no_transition_when_daily_guard_is_active(self) -> None:
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 105.0, high=105.5, low=104.0, adx=30.0))
        frame = pd.DataFrame(rows)
        state = RegimeTransitionState(equity=10000.0, daily_r=-3.5)
        for i in range(11):
            _update_streak_and_detect_transition(frame, i, state, DEFAULT_PARAMETERS)
        self.assertIsNone(state.pending_signal)


class SizeTransitionEntryTest(unittest.TestCase):
    def test_long_entry_uses_next_candle_open_and_stop_below_entry(self) -> None:
        pending = PendingSignal(direction="LONG", range_high=105.0, range_low=99.0, breakout_close=105.0)
        candle = _candle(close_time=0, close=106.0, open_=105.8, atr_value=2.0)
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.entry_price, 105.8 * 1.0002)
        self.assertLess(trade.stop_loss, trade.entry_price)

    def test_short_entry_stop_above_entry(self) -> None:
        pending = PendingSignal(direction="SHORT", range_high=105.0, range_low=99.0, breakout_close=99.0)
        candle = _candle(close_time=0, close=98.0, open_=98.2, atr_value=2.0)
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(trade)
        self.assertGreater(trade.stop_loss, trade.entry_price)

    def test_midpoint_stop_used_when_nearer_than_ceiling_and_above_floor(self) -> None:
        # range midpoint = 102; entry near midpoint -> tiny midpoint distance, but ATR
        # floor (0.75*10=7.5) will dominate since the midpoint distance is far smaller.
        pending = PendingSignal(direction="LONG", range_high=104.0, range_low=100.0, breakout_close=105.0)
        candle = _candle(close_time=0, close=105.0, open_=105.0, atr_value=1.0)
        # midpoint = 102; distance_to_midpoint = |105-102| = 3; ceiling = 2.5*1=2.5;
        # since 3 > 2.5, ceiling binds (2.5) as raw distance; floor = 0.75*1=0.75 < 2.5
        # -> stop_type should be atr_ceiling.
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertEqual(trade.stop_type, "atr_ceiling")

    def test_midpoint_binds_when_closer_than_ceiling_and_above_floor(self) -> None:
        pending = PendingSignal(direction="LONG", range_high=104.0, range_low=100.0, breakout_close=104.5)
        # midpoint = 102; entry at 103 (close) -> distance_to_midpoint = 1
        candle = _candle(close_time=0, close=104.5, open_=103.0, atr_value=10.0)
        # ceiling = 2.5*10=25 (much larger than 1) -> midpoint (1) binds as raw
        # distance; floor = 0.75*10=7.5, which is LARGER than 1 -> floor should win.
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertEqual(trade.stop_type, "atr_floor")

    def test_floor_enforced_when_midpoint_distance_is_smaller(self) -> None:
        pending = PendingSignal(direction="LONG", range_high=100.4, range_low=100.0, breakout_close=100.4)
        candle = _candle(close_time=0, close=100.4, open_=100.2, atr_value=4.0)
        # midpoint = 100.2; entry ~ 100.22 -> distance_to_midpoint tiny; floor = 3.0
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertEqual(trade.stop_type, "atr_floor")
        distance = abs(trade.entry_price - trade.stop_loss)
        self.assertAlmostEqual(distance, 3.0, places=3)

    def test_target_is_two_times_range_height_from_breakout_close(self) -> None:
        pending = PendingSignal(direction="LONG", range_high=105.0, range_low=99.0, breakout_close=106.0)
        candle = _candle(close_time=0, close=106.5, open_=106.2, atr_value=2.0)
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        range_height = 105.0 - 99.0
        self.assertAlmostEqual(trade.target, 106.0 + 2.0 * range_height)

    def test_risk_dollars_matches_one_percent_of_equity(self) -> None:
        pending = PendingSignal(direction="LONG", range_high=105.0, range_low=99.0, breakout_close=106.0)
        candle = _candle(close_time=0, close=106.5, open_=106.2, atr_value=2.0)
        state = RegimeTransitionState(equity=10000.0)
        trade = size_transition_entry(candle, pending, state, DEFAULT_PARAMETERS)
        self.assertAlmostEqual(trade.risk_dollars, 100.0, places=1)


class EvaluateExitTest(unittest.TestCase):
    def _open_long(self, entry_price=100.0, stop_loss=96.0, target=112.0) -> RegimeTransitionState:
        trade = OpenTrade(direction="LONG", entry_price=entry_price, stop_loss=stop_loss, target=target,
                           quantity=1.0, notional=entry_price, risk_dollars=4.0, entry_fee=0.0,
                           open_close_time=0, entry_atr=2.0, stop_type="midpoint")
        return RegimeTransitionState(equity=10000.0, open_trade=trade)

    def _open_short(self, entry_price=100.0, stop_loss=104.0, target=88.0) -> RegimeTransitionState:
        trade = OpenTrade(direction="SHORT", entry_price=entry_price, stop_loss=stop_loss, target=target,
                           quantity=1.0, notional=entry_price, risk_dollars=4.0, entry_fee=0.0,
                           open_close_time=0, entry_atr=2.0, stop_type="midpoint")
        return RegimeTransitionState(equity=10000.0, open_trade=trade)

    def test_no_open_trade_returns_none(self) -> None:
        state = RegimeTransitionState(equity=10000.0)
        candle = _candle(close_time=3_600_000, close=100.0, adx=20.0)
        self.assertIsNone(evaluate_exit(candle, state))

    def test_long_stop_exit(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=96.0)
        candle = _candle(close_time=3_600_000, close=95.0, low=94.0, adx=25.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "STOP")
        self.assertEqual(event.stop_type, "midpoint")

    def test_short_stop_exit(self) -> None:
        state = self._open_short(entry_price=100.0, stop_loss=104.0)
        candle = _candle(close_time=3_600_000, close=105.0, high=106.0, adx=25.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "STOP")

    def test_long_target_exit(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=96.0, target=110.0)
        candle = _candle(close_time=3_600_000, close=110.5, high=111.0, adx=30.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TARGET")

    def test_short_target_exit(self) -> None:
        state = self._open_short(entry_price=100.0, stop_loss=104.0, target=90.0)
        candle = _candle(close_time=3_600_000, close=89.5, low=89.0, adx=30.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TARGET")

    def test_stop_takes_priority_over_target_on_same_candle(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=96.0, target=104.0)
        candle = _candle(close_time=3_600_000, close=100.0, high=105.0, low=95.0, adx=30.0)
        event = evaluate_exit(candle, state)
        self.assertEqual(event.exit_reason, "STOP")

    def test_failed_transition_exit_when_adx_falls_below_20(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=90.0, target=130.0)
        candle = _candle(close_time=3_600_000, close=101.0, high=101.5, low=100.5, adx=19.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "FAILED_TRANSITION")

    def test_no_failed_transition_exactly_at_threshold(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=90.0, target=130.0)
        candle = _candle(close_time=3_600_000, close=101.0, high=101.5, low=100.5, adx=20.0)
        event = evaluate_exit(candle, state)
        self.assertIsNone(event)

    def test_time_exit_after_holding_cap(self) -> None:
        state = self._open_long(entry_price=100.0, stop_loss=90.0, target=130.0)
        far_future = DEFAULT_PARAMETERS.max_holding_hours * 3_600_000 + 1
        candle = _candle(close_time=far_future, close=101.0, high=101.5, low=100.5, adx=22.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TIME")

    def test_short_accounting_matches_convention(self) -> None:
        state = self._open_short(entry_price=100.0, stop_loss=104.0, target=88.0)
        state.open_trade.quantity = 2.0
        candle = _candle(close_time=3_600_000, close=99.0, high=99.5, low=98.5, adx=19.0)
        event = evaluate_exit(candle, state)
        self.assertIsNotNone(event)
        self.assertGreater(event.gross_pnl, 0.0)
        self.assertAlmostEqual(event.gross_pnl, (100.0 - event.exit_price) * 2.0)


class RunBacktestSmokeTest(unittest.TestCase):
    def test_end_to_end_transition_produces_a_trade(self) -> None:
        rows = []
        for i in range(10):
            price = 100.0 + (1.0 if i % 2 == 0 else -1.0)
            rows.append(_row(i * 3_600_000, price, high=price + 0.5, low=price - 0.5, adx=20.0))
        rows.append(_row(10 * 3_600_000, 106.0, high=106.5, low=105.0, open_=101.5, adx=30.0))
        rows.append(_row(11 * 3_600_000, 108.0, high=112.0, low=107.5, open_=106.2, adx=32.0))
        for i in range(12, 30):
            rows.append(_row(i * 3_600_000, 108.0 + i * 0.05, high=108.5 + i * 0.05, low=107.5 + i * 0.05, adx=32.0))
        frame = pd.DataFrame(rows)
        trades, state = run_backtest(frame, DEFAULT_PARAMETERS)
        self.assertGreaterEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason in ("TARGET", "STOP", "FAILED_TRANSITION", "TIME"), True)

    def test_runs_without_error_on_flat_data(self) -> None:
        rows = [_row(i * 3_600_000, 100.0, adx=15.0) for i in range(50)]
        frame = pd.DataFrame(rows)
        trades, state = run_backtest(frame, DEFAULT_PARAMETERS)
        self.assertEqual(trades, [])
        self.assertAlmostEqual(state.equity, DEFAULT_PARAMETERS.initial_equity)


class AddIndicatorsTest(unittest.TestCase):
    def test_produces_adx_and_atr_columns(self) -> None:
        rows = [_row(i * 3_600_000, 100.0 + (i % 3), adx=20.0) for i in range(40)]
        raw = pd.DataFrame(rows).drop(columns=["adx", "atr"])
        raw["volume"] = 100.0
        enriched = add_indicators(raw)
        self.assertIn("adx", enriched.columns)
        self.assertIn("atr", enriched.columns)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "regime-transition-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_default_parameters_match_task_spec(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.adx_entry_threshold, 25.0)
        self.assertEqual(DEFAULT_PARAMETERS.adx_failed_transition_threshold, 20.0)
        self.assertEqual(DEFAULT_PARAMETERS.mature_range_min_candles, 10)
        self.assertEqual(DEFAULT_PARAMETERS.atr_stop_ceiling_multiple, 2.5)
        self.assertEqual(DEFAULT_PARAMETERS.atr_stop_floor_multiple, 0.75)
        self.assertEqual(DEFAULT_PARAMETERS.target_range_height_multiple, 2.0)
        self.assertEqual(DEFAULT_PARAMETERS.risk_per_trade, 0.01)


if __name__ == "__main__":
    unittest.main()
