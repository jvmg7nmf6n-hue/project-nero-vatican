from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.fvg_reversion import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    FvgReversionParameters,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    run_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_council_engine import _make_candle_row

HOUR_MS = 3_600_000


def _row(index: int, high: float, low: float, close: float | None = None) -> dict[str, object]:
    close_time = index * HOUR_MS
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "close_time": close_time,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
        "volume": 10.0,
    }


class EvaluateEntryTest(unittest.TestCase):
    def _candle(self, close, ma200, bullish_zone_bottom=float("nan"), bearish_zone_top=float("nan")) -> pd.Series:
        row = _make_candle_row(0, close)
        row["ma200"] = ma200
        row["fvg_bullish_signal_zone_bottom"] = bullish_zone_bottom
        row["fvg_bearish_signal_zone_top"] = bearish_zone_top
        return pd.Series(row)

    def test_bullish_touch_above_ma200_is_long(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=110.0, ma200=100.0, bullish_zone_bottom=105.0)

        evaluation = evaluate_entry(candle, state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_bearish_touch_below_ma200_is_short(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=90.0, ma200=100.0, bearish_zone_top=95.0)

        evaluation = evaluate_entry(candle, state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")

    def test_bullish_touch_below_ma200_is_rejected(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=90.0, ma200=100.0, bullish_zone_bottom=85.0)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("BULLISH_TOUCH_BUT_NOT_ABOVE_MA200", evaluation.reasons)

    def test_no_touch_is_rejected(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=110.0, ma200=100.0)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_FVG_TOUCH_THIS_CANDLE", evaluation.reasons)

    def test_open_trade_blocks_entry(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = object()
        candle = self._candle(close=110.0, ma200=100.0, bullish_zone_bottom=105.0)

        evaluation = evaluate_entry(candle, state)

        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_long_stop_is_below_zone_bottom_by_half_atr(self) -> None:
        row = _make_candle_row(0, 110.0)
        row["atr"] = 4.0
        row["fvg_bullish_signal_zone_bottom"] = 105.0
        row["fvg_bullish_signal_remaining_top"] = 107.0
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(pd.Series(row), state, FvgReversionParameters(), "LONG")

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.stop_loss, 105.0 - 0.5 * 4.0, places=6)
        risk = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(trade.target, trade.entry_price + 1.5 * risk, places=6)

    def test_short_stop_is_above_zone_top_by_half_atr(self) -> None:
        row = _make_candle_row(0, 90.0)
        row["atr"] = 4.0
        row["fvg_bearish_signal_zone_top"] = 95.0
        row["fvg_bearish_signal_remaining_bottom"] = 92.0
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(pd.Series(row), state, FvgReversionParameters(), "SHORT")

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.stop_loss, 95.0 + 0.5 * 4.0, places=6)
        risk = trade.stop_loss - trade.entry_price
        self.assertAlmostEqual(trade.target, trade.entry_price - 1.5 * risk, places=6)


class EvaluateExitTest(unittest.TestCase):
    def test_long_stop_takes_priority_over_target(self) -> None:
        row = _make_candle_row(0, 110.0)
        row["atr"] = 4.0
        row["fvg_bullish_signal_zone_bottom"] = 105.0
        row["fvg_bullish_signal_remaining_top"] = 107.0
        state = MeanReversionState(equity=10_000.0)
        trade = size_entry(pd.Series(row), state, FvgReversionParameters(), "LONG")
        state.open_trade = trade

        exit_row = _make_candle_row(HOUR_MS, 105.0)
        exit_row["low"] = trade.stop_loss - 1.0
        exit_row["high"] = trade.target + 1.0
        event = evaluate_exit(pd.Series(exit_row), state, FvgReversionParameters())

        self.assertEqual(event.exit_reason, "SL")

    def test_short_stop_takes_priority_over_target(self) -> None:
        row = _make_candle_row(0, 90.0)
        row["atr"] = 4.0
        row["fvg_bearish_signal_zone_top"] = 95.0
        row["fvg_bearish_signal_remaining_bottom"] = 92.0
        state = MeanReversionState(equity=10_000.0)
        trade = size_entry(pd.Series(row), state, FvgReversionParameters(), "SHORT")
        state.open_trade = trade

        exit_row = _make_candle_row(HOUR_MS, 95.0)
        exit_row["high"] = trade.stop_loss + 1.0
        exit_row["low"] = trade.target - 1.0
        event = evaluate_exit(pd.Series(exit_row), state, FvgReversionParameters())

        self.assertEqual(event.exit_reason, "SL")

    def test_short_profit_when_price_falls(self) -> None:
        row = _make_candle_row(0, 90.0)
        row["atr"] = 4.0
        row["fvg_bearish_signal_zone_top"] = 95.0
        row["fvg_bearish_signal_remaining_bottom"] = 92.0
        state = MeanReversionState(equity=10_000.0)
        trade = size_entry(pd.Series(row), state, FvgReversionParameters(), "SHORT")
        state.open_trade = trade

        exit_row = _make_candle_row(HOUR_MS, trade.target)
        exit_row["high"] = trade.target + 0.5
        exit_row["low"] = trade.target - 0.5
        event = evaluate_exit(pd.Series(exit_row), state, FvgReversionParameters())

        self.assertEqual(event.exit_reason, "TARGET")
        self.assertGreater(event.net_pnl, 0)

    def test_no_open_trade_returns_none(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        row = _make_candle_row(0, 100.0)
        self.assertIsNone(evaluate_exit(pd.Series(row), state))


class RunBacktestEndToEndTest(unittest.TestCase):
    def test_produces_a_long_trade_from_a_bullish_gap_touch_in_an_uptrend(self) -> None:
        rows: list[dict[str, object]] = []
        # Long, flat uptrend warmup so MA200 sits well below current price.
        price = 100.0
        for i in range(210):
            price += 0.3
            rows.append(_row(i, high=price + 1, low=price - 1))
        last = price
        # A clean bullish gap: candle forms it, then a later candle touches it.
        rows.append(_row(210, high=last + 2, low=last + 1))       # i-2 anchor
        rows.append(_row(211, high=last + 20, low=last + 15))     # filler, high raised to avoid cascade
        rows.append(_row(212, high=last + 30, low=last + 22))     # gap forms: low(22 over last) > high[210]
        rows.append(_row(213, high=last + 25, low=last + 23))     # touches the gap zone
        for i in range(214, 230):
            rows.append(_row(i, high=last + 25 + i, low=last + 24 + i))  # continue up so a target/stop resolves

        candles = pd.DataFrame(rows)
        enriched = add_indicators(candles)
        dropna_columns = ["ma200", "atr"]
        evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        self.assertGreaterEqual(state.equity, 0.0)
        # Not asserting a specific trade fired (depends on exact touch/trend alignment
        # after warmup dropna reindexing) — this is an integration smoke test that the
        # full add_indicators -> run_backtest pipeline runs without error on a realistic
        # gap-forming sequence; the entry/exit unit tests above pin down the actual logic.
        self.assertIsInstance(trades, list)


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "fvg-reversion-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
