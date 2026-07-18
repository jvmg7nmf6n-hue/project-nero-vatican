from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.bos_continuation import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    BosContinuationParameters,
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
    def _candle(self, close, ma200, bos_up_pivot=float("nan"), preceding_low=float("nan"),
                bos_down_pivot=float("nan"), preceding_high=float("nan")) -> pd.Series:
        row = _make_candle_row(0, close)
        row["ma200"] = ma200
        row["bos_up_signal_pivot_value"] = bos_up_pivot
        row["bos_up_signal_preceding_low"] = preceding_low
        row["bos_down_signal_pivot_value"] = bos_down_pivot
        row["bos_down_signal_preceding_high"] = preceding_high
        return pd.Series(row)

    def test_bos_up_above_ma200_with_preceding_low_is_long(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=110.0, ma200=100.0, bos_up_pivot=105.0, preceding_low=95.0)

        evaluation = evaluate_entry(candle, state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_bos_down_below_ma200_with_preceding_high_is_short(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=90.0, ma200=100.0, bos_down_pivot=95.0, preceding_high=105.0)

        evaluation = evaluate_entry(candle, state)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")

    def test_bos_up_without_preceding_low_is_rejected(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=110.0, ma200=100.0, bos_up_pivot=105.0)  # no preceding_low

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_PRECEDING_SWING_LOW_FOR_STOP", evaluation.reasons)

    def test_bos_up_below_ma200_is_rejected(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=90.0, ma200=100.0, bos_up_pivot=85.0, preceding_low=80.0)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("BOS_UP_BUT_NOT_ABOVE_MA200", evaluation.reasons)

    def test_no_bos_is_rejected(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle(close=110.0, ma200=100.0)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("NO_BOS_THIS_CANDLE", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def _long_candle(self, close, atr_value, preceding_low) -> pd.Series:
        row = _make_candle_row(0, close)
        row["atr"] = atr_value
        row["bos_up_signal_preceding_low"] = preceding_low
        return pd.Series(row)

    def test_uses_structural_stop_when_within_the_cap(self) -> None:
        # preceding_low=95, buffer 0.25*atr(2)=0.5 -> structural_stop=94.5, distance from
        # entry(~100)=5.5, well within cap 3*2=6.
        candle = self._long_candle(close=100.0, atr_value=2.0, preceding_low=95.0)
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(candle, state, BosContinuationParameters(), "LONG")

        self.assertIsNotNone(trade)
        self.assertEqual(trade.stop_type, "structural")
        risk = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(trade.target, trade.entry_price + 2.0 * risk, places=6)

    def test_uses_capped_stop_when_structural_distance_exceeds_the_cap(self) -> None:
        # preceding_low far away -> structural distance >> 3*ATR -> capped stop used.
        candle = self._long_candle(close=100.0, atr_value=2.0, preceding_low=50.0)
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(candle, state, BosContinuationParameters(), "LONG")

        self.assertIsNotNone(trade)
        self.assertEqual(trade.stop_type, "capped")
        risk = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(risk, 3.0 * 2.0, places=6)
        self.assertAlmostEqual(trade.target, trade.entry_price + 2.0 * risk, places=6)

    def test_short_mirrors_the_long_stop_logic(self) -> None:
        row = _make_candle_row(0, 100.0)
        row["atr"] = 2.0
        row["bos_down_signal_preceding_high"] = 105.0
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(pd.Series(row), state, BosContinuationParameters(), "SHORT")

        self.assertIsNotNone(trade)
        self.assertGreater(trade.stop_loss, trade.entry_price)
        self.assertLess(trade.target, trade.entry_price)


class EvaluateExitTest(unittest.TestCase):
    def test_long_stop_priority_and_stop_type_carried_over(self) -> None:
        candle = pd.Series(
            {**_make_candle_row(0, 100.0), "atr": 2.0, "bos_up_signal_preceding_low": 95.0}
        )
        state = MeanReversionState(equity=10_000.0)
        trade = size_entry(candle, state, BosContinuationParameters(), "LONG")
        state.open_trade = trade

        exit_row = _make_candle_row(HOUR_MS, 95.0)
        exit_row["low"] = trade.stop_loss - 1.0
        exit_row["high"] = trade.target + 1.0
        event = evaluate_exit(pd.Series(exit_row), state, BosContinuationParameters())

        self.assertEqual(event.exit_reason, "SL")
        self.assertEqual(event.stop_type, trade.stop_type)

    def test_no_open_trade_returns_none(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        row = _make_candle_row(0, 100.0)
        self.assertIsNone(evaluate_exit(pd.Series(row), state))


class RunBacktestSmokeTest(unittest.TestCase):
    def test_runs_end_to_end_without_error(self) -> None:
        rows: list[dict[str, object]] = []
        price = 100.0
        for i in range(230):
            price += 0.3
            rows.append(_row(i, high=price + 1, low=price - 1))
        # A clean isolated swing high, then a break.
        last = price
        rows += [
            _row(230, high=last + 2, low=last - 1),
            _row(231, high=last + 3, low=last),
            _row(232, high=last + 15, low=last + 5, close=last + 8),  # swing high candidate
            _row(233, high=last + 12, low=last + 6),
            _row(234, high=last + 11, low=last + 5),
            _row(235, high=last + 10, low=last + 4),
            _row(236, high=last + 9, low=last + 3),
            _row(237, high=last + 8, low=last + 2, close=last + 20),  # confirms + breaks
        ]
        for i in range(238, 260):
            level = last + 21 + (i - 238)
            rows.append(_row(i, high=level + 1, low=level - 1))

        candles = pd.DataFrame(rows)
        enriched = add_indicators(candles)
        evaluable = enriched.dropna(subset=["ma200", "atr"]).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, 0.0)
        for trade in trades:
            self.assertIn(trade.stop_type, {"structural", "capped"})


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "bos-continuation-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
