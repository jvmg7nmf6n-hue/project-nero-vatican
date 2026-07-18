from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.breakout_momentum import STRATEGY_ID as BASE_STRATEGY_ID
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    STRATEGY_VERSION as BASE_STRATEGY_VERSION,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_trail import (
    STRATEGY_VERSION,
    DEFAULT_PARAMETERS,
    add_indicators,
    register_default_variant,
    run_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_council_engine import _make_candle_row


def _weekly_breakout_and_extended_rally() -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    close_time = 0
    for i in range(220):
        close = 100.0 + 0.05 * i
        rows.append(_make_candle_row(close_time, close))
        close_time += 7 * 86_400_000
    price = rows[-1]["close"]
    # Breakout + extended rally leg.
    for _ in range(20):
        price *= 1.04
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    # Sustained reversal to eventually trip the trail.
    for _ in range(10):
        price *= 0.90
        rows.append(_make_candle_row(close_time, price))
        close_time += 7 * 86_400_000
    return pd.DataFrame(rows)


class RegistrationTest(unittest.TestCase):
    def test_version_string_is_new_and_distinct(self) -> None:
        self.assertEqual(STRATEGY_VERSION, "breakout-momentum-v1.5.0-gold-calibrated-1week-trail")
        self.assertNotEqual(STRATEGY_VERSION, BASE_STRATEGY_VERSION)

    def test_register_default_variant_uses_base_strategy_id(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, BASE_STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_trail_ema_period_is_8_not_21(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.trail_ema_period, 8)

    def test_gold_fee_calibration_is_carried_over_unchanged(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.fee_bps, GOLD_CALIBRATED_1WEEK_PARAMETERS.fee_bps)
        self.assertEqual(DEFAULT_PARAMETERS.slippage_bps, GOLD_CALIBRATED_1WEEK_PARAMETERS.slippage_bps)
        self.assertEqual(DEFAULT_PARAMETERS.atr_stop_multiple, GOLD_CALIBRATED_1WEEK_PARAMETERS.atr_stop_multiple)


class SizeEntryTest(unittest.TestCase):
    def test_no_target_field_exists_on_the_open_trade(self) -> None:
        history = _weekly_breakout_and_extended_rally()
        enriched = add_indicators(history)
        row = enriched.dropna(subset=["ma200", "rsi", "atr", "breakout_high", "trail_ema"]).iloc[0]
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(row, state)

        self.assertIsNotNone(trade)
        self.assertFalse(hasattr(trade, "target"))
        self.assertFalse(trade.trail_armed)


class RunBacktestTest(unittest.TestCase):
    def test_every_exit_reason_is_sl_or_trail_never_target_or_time(self) -> None:
        history = _weekly_breakout_and_extended_rally()
        enriched = add_indicators(history)
        evaluable = enriched.dropna(subset=["ma200", "rsi", "atr", "breakout_high", "trail_ema"]).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        self.assertGreater(len(trades), 0)
        for trade in trades:
            self.assertIn(trade.exit_reason, {"SL", "TRAIL"})

    def test_equity_bookkeeping_is_internally_consistent(self) -> None:
        history = _weekly_breakout_and_extended_rally()
        enriched = add_indicators(history)
        evaluable = enriched.dropna(subset=["ma200", "rsi", "atr", "breakout_high", "trail_ema"]).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        running = DEFAULT_PARAMETERS.initial_equity
        for trade in trades:
            running += trade.net_pnl
            self.assertAlmostEqual(running, trade.equity_after, places=6)
        self.assertAlmostEqual(state.equity, running, places=6)


if __name__ == "__main__":
    unittest.main()
