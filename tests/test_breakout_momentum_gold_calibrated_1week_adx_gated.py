from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    register_default_variant as register_base_variant,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_adx_gated import (
    DEFAULT_PARAMETERS,
    STRATEGY_VERSION,
    add_indicators,
    evaluate_entry,
    register_default_variant,
    run_backtest,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_breakout_momentum import make_candle


class AdxGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_rejects_entry_when_adx_below_gate(self) -> None:
        candle = make_candle(adx=15.0)  # otherwise-passing candle from make_candle defaults
        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("ADX_GATE_NOT_MET", evaluation.reasons)

    def test_allows_entry_when_adx_meets_gate(self) -> None:
        candle = make_candle(adx=25.0)
        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertTrue(evaluation.passed)

    def test_missing_adx_rejects_rather_than_crashing(self) -> None:
        candle = make_candle()  # no "adx" key at all in make_candle's base dict
        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("ADX_GATE_NOT_MET", evaluation.reasons)

    def test_still_reports_base_rejection_reasons_when_adx_also_fails(self) -> None:
        candle = make_candle(adx=10.0, close=90.0)  # close below ma200 -> base rejection too
        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("ADX_GATE_NOT_MET", evaluation.reasons)
        self.assertIn("CLOSE_NOT_ABOVE_MA200", evaluation.reasons)


class AddIndicatorsTest(unittest.TestCase):
    def test_adds_adx_column_alongside_base_indicators(self) -> None:
        rows = []
        price = 100.0
        for i in range(220):
            price += 0.5
            rows.append({
                "date": pd.Timestamp(i * 604_800_000, unit="ms", tz="UTC"),
                "open_time": i * 604_800_000, "close_time": (i + 1) * 604_800_000,
                "open": price - 0.5, "high": price + 1.0, "low": price - 1.0,
                "close": price, "volume": 100.0,
            })
        frame = pd.DataFrame(rows)
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)
        for col in ("ma200", "rsi", "atr", "breakout_high", "adx"):
            self.assertIn(col, enriched.columns)


class RunBacktestSmokeTest(unittest.TestCase):
    def test_runs_end_to_end_without_error(self) -> None:
        rows = []
        price = 100.0
        for i in range(220):
            price += 0.5
            rows.append({
                "date": pd.Timestamp(i * 604_800_000, unit="ms", tz="UTC"),
                "open_time": i * 604_800_000, "close_time": (i + 1) * 604_800_000,
                "open": price - 0.5, "high": price + 1.0, "low": price - 1.0,
                "close": price, "volume": 100.0,
            })
        frame = pd.DataFrame(rows)
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)
        evaluable = enriched.dropna(subset=["ma200", "rsi", "atr", "adx"]).reset_index(drop=True)
        trades, state = run_backtest(evaluable, DEFAULT_PARAMETERS)
        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, 0.0)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "breakout-momentum-v1.6.0-gold-calibrated-1week-adx-gated")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_coexists_with_the_live_base_variant_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()
        base = register_base_variant(registry)
        gated = register_default_variant(registry)
        self.assertEqual(base.strategy_id, gated.strategy_id)
        self.assertNotEqual(base.version, gated.version)
        self.assertEqual(base.version, "breakout-momentum-v1.2.0-gold-calibrated-1week")

    def test_only_adx_fields_and_gate_differ_from_the_live_base_variant(self) -> None:
        from dataclasses import fields
        for field in fields(GOLD_CALIBRATED_1WEEK_PARAMETERS):
            base_value = getattr(GOLD_CALIBRATED_1WEEK_PARAMETERS, field.name)
            gated_value = getattr(DEFAULT_PARAMETERS, field.name)
            self.assertEqual(base_value, gated_value, f"{field.name} should be unchanged")
        self.assertEqual(DEFAULT_PARAMETERS.adx_gate_threshold, 20.0)


if __name__ == "__main__":
    unittest.main()
