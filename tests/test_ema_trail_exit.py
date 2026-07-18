from __future__ import annotations

import unittest
from dataclasses import dataclass

import pandas as pd

from nero_core.strategies.ema_trail_exit import add_ema_column, evaluate_trail_exit
from nero_core.strategies.mean_reversion import MeanReversionState
from tests.test_council_engine import _make_candle_row


@dataclass
class _FakeOpenTrade:
    entry_price: float
    stop_loss: float
    quantity: float
    entry_fee: float
    open_close_time: int
    risk_dollars: float = 100.0
    trail_armed: bool = False


def _candle(close_time: int, close: float, low: float, high: float, ema: float) -> pd.Series:
    row = _make_candle_row(close_time, close)
    row["low"] = low
    row["high"] = high
    row["trail_ema"] = ema
    return pd.Series(row)


class AddEmaColumnTest(unittest.TestCase):
    def test_matches_manual_ewm_calculation(self) -> None:
        candles = pd.DataFrame({"close": [10.0, 12.0, 11.0, 13.0, 14.0]})

        enriched = add_ema_column(candles, ema_period=3, column_name="trail_ema")

        expected = candles["close"].ewm(span=3, adjust=False).mean()
        pd.testing.assert_series_equal(enriched["trail_ema"], expected, check_names=False)

    def test_preserves_other_columns(self) -> None:
        candles = pd.DataFrame({"close": [10.0, 11.0], "volume": [1.0, 2.0]})
        enriched = add_ema_column(candles, ema_period=2)
        self.assertIn("volume", enriched.columns)
        self.assertIn("trail_ema", enriched.columns)


class EvaluateTrailExitTest(unittest.TestCase):
    def _state_with_trade(self, trail_armed: bool = False) -> MeanReversionState:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = _FakeOpenTrade(
            entry_price=100.0, stop_loss=95.0, quantity=10.0, entry_fee=1.0, open_close_time=0, trail_armed=trail_armed
        )
        return state

    def test_no_open_trade_returns_none(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = _candle(3_600_000, 101.0, 100.0, 102.0, 99.0)
        self.assertIsNone(evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0))

    def test_unarmed_and_below_stop_exits_via_sl(self) -> None:
        state = self._state_with_trade(trail_armed=False)
        candle = _candle(3_600_000, 96.0, 94.0, 97.0, 99.0)  # low breaches stop_loss=95

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "SL")
        self.assertIsNone(state.open_trade)

    def test_unarmed_close_above_ema_arms_without_exiting(self) -> None:
        state = self._state_with_trade(trail_armed=False)
        candle = _candle(3_600_000, 101.0, 100.0, 102.0, 99.0)  # close (101) > ema (99), stop not hit

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNone(event)
        self.assertTrue(state.open_trade.trail_armed)

    def test_unarmed_close_below_ema_does_not_arm_and_does_not_exit(self) -> None:
        state = self._state_with_trade(trail_armed=False)
        candle = _candle(3_600_000, 98.0, 96.0, 99.0, 99.5)  # close (98) < ema (99.5); low above stop

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNone(event)
        self.assertFalse(state.open_trade.trail_armed)

    def test_armed_trade_does_not_exit_on_the_same_candle_it_arms(self) -> None:
        # A candle whose low touches the EMA level yet still closes above it — since
        # trail_armed is False BEFORE this candle, the trail check must not fire; the
        # candle should arm for the NEXT candle instead.
        state = self._state_with_trade(trail_armed=False)
        candle = _candle(3_600_000, 101.0, 98.0, 102.0, 99.0)  # low(98) <= ema(99), but not armed yet

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNone(event)
        self.assertTrue(state.open_trade.trail_armed)

    def test_armed_trade_exits_when_low_touches_the_ema(self) -> None:
        state = self._state_with_trade(trail_armed=True)
        candle = _candle(3_600_000, 100.0, 98.0, 101.0, 99.0)  # low(98) <= ema(99)

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "TRAIL")
        self.assertIsNone(state.open_trade)

    def test_armed_trade_with_no_touch_stays_open(self) -> None:
        state = self._state_with_trade(trail_armed=True)
        candle = _candle(3_600_000, 105.0, 100.0, 106.0, 99.0)  # low(100) > ema(99), well above stop too

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertIsNone(event)
        self.assertIsNotNone(state.open_trade)
        self.assertTrue(state.open_trade.trail_armed)

    def test_sl_takes_priority_over_trail_when_both_would_fire(self) -> None:
        state = self._state_with_trade(trail_armed=True)
        # low(90) breaches BOTH stop_loss(95) and trail ema(99).
        candle = _candle(3_600_000, 96.0, 90.0, 97.0, 99.0)

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertEqual(event.exit_reason, "SL")

    def test_r_multiple_and_equity_bookkeeping_is_consistent(self) -> None:
        state = self._state_with_trade(trail_armed=True)
        state.open_trade.risk_dollars = 50.0
        candle = _candle(3_600_000, 100.0, 98.0, 101.0, 99.0)

        event = evaluate_trail_exit(candle, state, "trail_ema", fee_bps=10.0, slippage_bps=2.0)

        self.assertAlmostEqual(event.r_multiple, event.net_pnl / 50.0, places=9)
        self.assertAlmostEqual(state.equity, 10_000.0 + event.net_pnl, places=6)
        self.assertAlmostEqual(state.daily_r, event.r_multiple, places=9)


if __name__ == "__main__":
    unittest.main()
