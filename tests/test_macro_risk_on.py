from __future__ import annotations

import unittest
from dataclasses import fields

import pandas as pd

from nero_core.strategies.macro_risk_on import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    MacroRiskOnParameters,
    OpenTrade,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    run_macro_risk_on_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T00:00:00Z"),
        "open_time": close_time - 86_400_000,
        "close_time": close_time,
        "open": 100.0,
        "high": 102.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 1000.0,
        "atr": 3.0,
        "risk_on": True,
        "dollar_change_20d": -1.0,
        "dfii10_change_20d": -0.1,
    }
    data.update(overrides)
    return pd.Series(data)


def _row(close_time: int, close: float, risk_on: bool, high: float | None = None, low: float | None = None) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 86_400_000,
        "close_time": close_time,
        "open": close,
        "high": high if high is not None else close + 1.0,
        "low": low if low is not None else close - 1.0,
        "close": close,
        "volume": 100.0,
        "risk_on": risk_on,
        "dollar_change_20d": -1.0 if risk_on else 1.0,
        "dfii10_change_20d": -0.1 if risk_on else 0.1,
    }


class ParametersTest(unittest.TestCase):
    def test_no_max_holding_hours_field(self) -> None:
        field_names = {f.name for f in fields(MacroRiskOnParameters)}
        self.assertNotIn("max_holding_hours", field_names)

    def test_no_fixed_target_field(self) -> None:
        field_names = {f.name for f in fields(MacroRiskOnParameters)}
        self.assertNotIn("target", field_names)
        self.assertNotIn("reward_multiple", field_names)

    def test_default_stop_multiple_is_2x_atr(self) -> None:
        self.assertAlmostEqual(DEFAULT_PARAMETERS.atr_stop_multiple, 2.0)


class AddIndicatorsTest(unittest.TestCase):
    def test_attaches_atr_without_touching_risk_on(self) -> None:
        rows = [_row(i * 86_400_000, 100.0 + i * 0.1, True) for i in range(30)]
        frame = pd.DataFrame(rows)

        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        self.assertIn("atr", enriched.columns)
        self.assertIn("risk_on", enriched.columns)
        self.assertTrue(pd.isna(enriched.iloc[0]["atr"]))
        self.assertFalse(pd.isna(enriched.iloc[20]["atr"]))


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_passes_when_risk_on_and_atr_available(self) -> None:
        candle = make_candle(risk_on=True, atr=3.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())
        self.assertTrue(evaluation.risk_on)

    def test_blocked_when_regime_is_risk_off(self) -> None:
        candle = make_candle(risk_on=False)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("REGIME_NOT_RISK_ON", evaluation.reasons)

    def test_blocked_when_risk_on_is_nan(self) -> None:
        candle = make_candle(risk_on=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("REGIME_NOT_RISK_ON", evaluation.reasons)
        self.assertIsNone(evaluation.risk_on)

    def test_blocked_when_atr_is_nan(self) -> None:
        candle = make_candle(atr=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("ATR_NOT_AVAILABLE", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        self.state.open_trade = OpenTrade(
            entry_price=100.0, stop_loss=94.0, quantity=1.0, notional=100.0,
            risk_dollars=6.0, entry_fee=0.1, open_close_time=0, entry_atr=3.0,
        )
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_daily_loss_guard_blocks_entry(self) -> None:
        self.state.daily_r = -5.0
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_stop_loss_is_2x_atr_below_entry(self) -> None:
        candle = make_candle(close=100.0, atr=3.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        expected_stop = trade.entry_price - 2.0 * 3.0
        self.assertAlmostEqual(trade.stop_loss, expected_stop, places=6)

    def test_risk_dollars_matches_fixed_fractional_target(self) -> None:
        candle = make_candle(close=100.0, atr=3.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * DEFAULT_PARAMETERS.risk_per_trade, places=4)

    def test_returns_none_when_atr_is_zero(self) -> None:
        candle = make_candle(close=100.0, atr=0.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNone(trade)

    def test_notional_capped_by_max_notional_pct(self) -> None:
        params = MacroRiskOnParameters(max_notional_pct=0.5, risk_per_trade=0.9)
        candle = make_candle(close=100.0, atr=0.01)  # tiny stop distance -> huge uncapped quantity

        trade = size_entry(candle, self.state, params)

        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, self.state.equity * 0.5 + 1e-6)


class EvaluateExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_no_exit_while_regime_stays_on_and_stop_not_hit(self) -> None:
        entry = size_entry(make_candle(close_time=0, close=100.0, atr=3.0), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=86_400_000, close=101.0, low=99.5, risk_on=True),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNone(exit_event)
        self.assertIsNotNone(self.state.open_trade)

    def test_exits_on_regime_off(self) -> None:
        entry = size_entry(make_candle(close_time=0, close=100.0, atr=3.0), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=86_400_000, close=101.0, low=99.5, risk_on=False),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "REGIME_OFF")

    def test_exits_on_stop_even_if_regime_still_on(self) -> None:
        entry = size_entry(make_candle(close_time=0, close=100.0, atr=3.0), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry
        stop_price = entry.stop_loss

        exit_event = evaluate_exit(
            make_candle(close_time=86_400_000, close=stop_price - 1.0, low=stop_price - 1.0, risk_on=True),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "STOP")

    def test_stop_takes_priority_over_regime_off_on_same_candle(self) -> None:
        entry = size_entry(make_candle(close_time=0, close=100.0, atr=3.0), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry
        stop_price = entry.stop_loss

        exit_event = evaluate_exit(
            make_candle(close_time=86_400_000, close=stop_price - 1.0, low=stop_price - 1.0, risk_on=False),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "STOP")

    def test_returns_none_when_no_open_trade(self) -> None:
        self.assertIsNone(evaluate_exit(make_candle(), self.state, DEFAULT_PARAMETERS))


class RunMacroRiskOnBacktestTest(unittest.TestCase):
    def test_produces_internally_consistent_equity_accounting(self) -> None:
        rows: list[dict[str, object]] = []
        close_time = 0
        price = 100.0
        for i in range(80):
            price += 0.3 if (i // 10) % 2 == 0 else -0.3
            risk_on = (i // 10) % 2 == 0  # alternate regime every 10 candles
            rows.append(_row(close_time, price, risk_on))
            close_time += 86_400_000
        frame = pd.DataFrame(rows)

        trades, state = run_macro_risk_on_backtest(frame, DEFAULT_PARAMETERS)

        running = DEFAULT_PARAMETERS.initial_equity
        for trade in trades:
            running += trade.net_pnl
            self.assertAlmostEqual(running, trade.equity_after, places=6)
        self.assertAlmostEqual(state.equity, running, places=6)

    def test_no_trades_open_when_regime_never_turns_on(self) -> None:
        rows = [_row(i * 86_400_000, 100.0 + i * 0.05, False) for i in range(40)]
        frame = pd.DataFrame(rows)

        trades, _ = run_macro_risk_on_backtest(frame, DEFAULT_PARAMETERS)

        self.assertEqual(trades, [])


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "macro-risk-on-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
