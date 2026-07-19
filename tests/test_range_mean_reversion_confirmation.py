from __future__ import annotations

import unittest
from dataclasses import replace

import pandas as pd

from nero_core.strategies.range_mean_reversion import STRATEGY_ID, OpenTrade, RangeMeanReversionState
from nero_core.strategies.range_mean_reversion_confirmation import (
    CONFIRMATION_PARAMETERS,
    STRATEGY_VERSION,
    evaluate_confirmation_entry,
    register_default_variant,
    run_backtest,
    size_confirmation_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _row(close_time, open_=100.0, close=100.0, bb_lower=95.0, bb_upper=105.0, adx=20.0, atr_value=2.0):
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"), "close_time": close_time,
        "open": open_, "high": max(open_, close) + 1, "low": min(open_, close) - 1, "close": close,
        "bb_lower": bb_lower, "bb_upper": bb_upper, "adx": adx, "atr": atr_value, "sma20": 100.0,
    }


def _long_confirmation_evaluable(entry_open: float = 91.0) -> pd.DataFrame:
    """3 rows: t (close below lower band), t+1 (close back above lower band, ADX
    ranging), t+2 (the entry candle — its OPEN is the actual fill price)."""
    rows = [
        _row(0, open_=94.0, close=90.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),  # t: below band
        _row(3_600_000, open_=90.0, close=96.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),  # t+1: back above, ranging
        _row(7_200_000, open_=entry_open, close=97.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),  # t+2: entry candle
    ]
    return pd.DataFrame(rows)


class EvaluateConfirmationEntryTest(unittest.TestCase):
    def test_insufficient_lookback_at_early_indices(self) -> None:
        evaluable = _long_confirmation_evaluable()
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_confirmation_entry(evaluable, 0, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("INSUFFICIENT_LOOKBACK", evaluation.reasons)

    def test_long_confirmation_pattern_passes_at_index_2(self) -> None:
        evaluable = _long_confirmation_evaluable()
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_short_confirmation_pattern_passes(self) -> None:
        rows = [
            _row(0, open_=106.0, close=110.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),  # t: above band
            _row(3_600_000, open_=110.0, close=100.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),  # t+1: back below, ranging
            _row(7_200_000, open_=99.0, close=98.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),  # t+2: entry
        ]
        evaluable = pd.DataFrame(rows)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")

    def test_no_pattern_when_t1_does_not_close_back_inside_band(self) -> None:
        rows = [
            _row(0, open_=94.0, close=90.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),  # t: below band
            _row(3_600_000, open_=90.0, close=91.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),  # t+1: still below band
            _row(7_200_000, open_=92.0, close=93.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),
        ]
        evaluable = pd.DataFrame(rows)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("NO_CONFIRMATION_PATTERN", evaluation.reasons)

    def test_no_pattern_when_adx_not_ranging_at_t1(self) -> None:
        rows = [
            _row(0, open_=94.0, close=90.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),
            _row(3_600_000, open_=90.0, close=96.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),  # t+1: trending, not ranging
            _row(7_200_000, open_=97.0, close=97.0, bb_lower=95.0, bb_upper=105.0, adx=25.0),
        ]
        evaluable = pd.DataFrame(rows)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("NO_CONFIRMATION_PATTERN", evaluation.reasons)

    def test_short_confirmation_disabled_when_allow_short_false(self) -> None:
        # RMR Variant Research Cycle, Stage 3: range_mean_reversion_long_only_
        # confirmation.py stacks allow_short=False onto this confirmation entry.
        rows = [
            _row(0, open_=106.0, close=110.0, bb_lower=95.0, bb_upper=105.0, adx=30.0),
            _row(3_600_000, open_=110.0, close=100.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),
            _row(7_200_000, open_=99.0, close=98.0, bb_lower=95.0, bb_upper=105.0, adx=20.0),
        ]
        evaluable = pd.DataFrame(rows)
        state = RangeMeanReversionState(equity=10000.0)
        params = replace(CONFIRMATION_PARAMETERS, allow_short=False)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state, params)
        self.assertFalse(evaluation.passed)
        self.assertIn("SHORT_DISABLED", evaluation.reasons)

    def test_long_confirmation_still_works_when_allow_short_false(self) -> None:
        evaluable = _long_confirmation_evaluable()
        state = RangeMeanReversionState(equity=10000.0)
        params = replace(CONFIRMATION_PARAMETERS, allow_short=False)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state, params)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_rejected_when_open_trade_exists(self) -> None:
        evaluable = _long_confirmation_evaluable()
        trade = OpenTrade(direction="LONG", entry_price=100.0, stop_loss=95.0, quantity=1.0, notional=100.0,
                           risk_dollars=5.0, entry_fee=0.0, open_close_time=0, entry_atr=2.0)
        state = RangeMeanReversionState(equity=10000.0, open_trade=trade)
        evaluation = evaluate_confirmation_entry(evaluable, 2, state)
        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)


class SizeConfirmationEntryTest(unittest.TestCase):
    def test_entry_price_derived_from_candle_open_not_close(self) -> None:
        evaluable = _long_confirmation_evaluable(entry_open=91.0)
        candle = evaluable.iloc[2]
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_confirmation_entry(candle, state, CONFIRMATION_PARAMETERS, "LONG")
        # entry_price should be derived from open=91.0 (plus slippage), not close=97.0
        self.assertLess(trade.entry_price, 95.0)
        self.assertGreater(trade.entry_price, 90.0)

    def test_long_stop_below_entry(self) -> None:
        evaluable = _long_confirmation_evaluable()
        candle = evaluable.iloc[2]
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_confirmation_entry(candle, state, CONFIRMATION_PARAMETERS, "LONG")
        self.assertLess(trade.stop_loss, trade.entry_price)

    def test_short_stop_above_entry(self) -> None:
        evaluable = _long_confirmation_evaluable()
        candle = evaluable.iloc[2]
        state = RangeMeanReversionState(equity=10000.0)
        trade = size_confirmation_entry(candle, state, CONFIRMATION_PARAMETERS, "SHORT")
        self.assertGreater(trade.stop_loss, trade.entry_price)


class RunBacktestSmokeTest(unittest.TestCase):
    def test_runs_end_to_end_without_error(self) -> None:
        evaluable = _long_confirmation_evaluable()
        trades, state = run_backtest(evaluable)
        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, 0.0)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.3.0-confirmation")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
