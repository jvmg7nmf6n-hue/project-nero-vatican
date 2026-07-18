from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import STRATEGY_ID as BASE_STRATEGY_ID
from nero_core.strategies.trend_pullback import STRATEGY_VERSION as BASE_STRATEGY_VERSION
from nero_core.strategies.trend_pullback_trail import (
    STRATEGY_VERSION,
    DEFAULT_PARAMETERS,
    add_indicators,
    register_default_variant,
    run_backtest,
    size_entry,
)
from tests.test_council_engine import _make_candle_row


def _uptrend_pullback_rally_history() -> pd.DataFrame:
    """Long uptrend warmup (MA200 valid, MA50 > MA200), a pullback toward MA50, a
    re-entry above MA50, then an EXTENDED rally (so a trail-exit variant has real room
    to differ from a fixed-target variant) followed by a reversal (so the trail
    eventually exits)."""
    rows: list[dict[str, float]] = []
    close_time = 0
    price = 100.0
    for i in range(220):
        price = 100.0 + 0.5 * i
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000  # 12h
    # Pullback toward MA50 then back above it.
    for delta in (-8, -12, -6, 2, 5):
        price += delta
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    # Extended rally.
    for _ in range(15):
        price *= 1.03
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    # Reversal, sustained, to eventually trip the trail.
    for _ in range(10):
        price *= 0.94
        rows.append(_make_candle_row(close_time, price))
        close_time += 43_200_000
    return pd.DataFrame(rows)


class RegistrationTest(unittest.TestCase):
    def test_version_string_is_new_and_distinct(self) -> None:
        self.assertEqual(STRATEGY_VERSION, "trend-pullback-v1.2.0-trail")
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

    def test_trail_ema_period_is_a_registered_parameter(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.trail_ema_period, 21)

    def test_max_holding_hours_is_inherited_but_present(self) -> None:
        # Present (inherited from the base dataclass) but never read by this module's
        # own evaluate_exit — see the module docstring for why that's intentional.
        self.assertTrue(hasattr(DEFAULT_PARAMETERS, "max_holding_hours"))


class SizeEntryTest(unittest.TestCase):
    def test_no_target_field_exists_on_the_open_trade(self) -> None:
        history = _uptrend_pullback_rally_history()
        enriched = add_indicators(history)
        row = enriched.dropna(subset=["ma50", "ma200", "rsi", "atr", "trail_ema"]).iloc[0]
        from nero_core.strategies.mean_reversion import MeanReversionState

        state = MeanReversionState(equity=10_000.0)
        trade = size_entry(row, state)

        self.assertIsNotNone(trade)
        self.assertFalse(hasattr(trade, "target"))
        self.assertFalse(trade.trail_armed)


class RunBacktestTest(unittest.TestCase):
    def test_every_exit_reason_is_sl_or_trail_never_target_or_time(self) -> None:
        history = _uptrend_pullback_rally_history()
        enriched = add_indicators(history)
        evaluable = enriched.dropna(subset=["ma50", "ma200", "rsi", "atr", "trail_ema"]).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        self.assertGreater(len(trades), 0)
        for trade in trades:
            self.assertIn(trade.exit_reason, {"SL", "TRAIL"})

    def test_equity_bookkeeping_is_internally_consistent(self) -> None:
        history = _uptrend_pullback_rally_history()
        enriched = add_indicators(history)
        evaluable = enriched.dropna(subset=["ma50", "ma200", "rsi", "atr", "trail_ema"]).reset_index(drop=True)

        trades, state = run_backtest(evaluable)

        running = DEFAULT_PARAMETERS.initial_equity
        for trade in trades:
            running += trade.net_pnl
            self.assertAlmostEqual(running, trade.equity_after, places=6)
        self.assertAlmostEqual(state.equity, running, places=6)


if __name__ == "__main__":
    unittest.main()
