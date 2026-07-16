from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as V1_PARAMETERS,
    STRATEGY_ID,
    MeanReversionState,
    evaluate_entry,
    size_entry,
)
from nero_core.strategies.mean_reversion import register_default_variant as register_v1
from nero_core.strategies.mean_reversion_target_1r import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


class Target1RParametersTest(unittest.TestCase):
    def test_only_target_mode_differs_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            t1r_value = getattr(PARAMETERS, field.name)
            if field.name == "target_mode":
                self.assertNotEqual(v1_value, t1r_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, t1r_value, f"{field.name} should be unchanged from v1")

    def test_value_matches_the_original_nero_candidate(self) -> None:
        self.assertEqual(PARAMETERS.target_mode, "FIXED_1R")


class Target1RSizingBehaviorTest(unittest.TestCase):
    """Proves the target is a fixed 1x risk-per-unit, not the floating MA20 target
    v1.0.0 uses — the entire point of this port."""

    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_target_equals_entry_plus_one_risk_unit(self) -> None:
        candle = make_candle(close=100.0, atr=2.0, bb_lower=101.0, ma200=95.0, ma20=105.0)

        trade = size_entry(candle, self.state, PARAMETERS)

        self.assertIsNotNone(trade)
        risk_per_unit = trade.entry_price - trade.stop_loss
        self.assertAlmostEqual(trade.target - trade.entry_price, risk_per_unit, places=6)

    def test_v1_uses_ma20_target_instead(self) -> None:
        candle = make_candle(close=100.0, atr=2.0, bb_lower=101.0, ma200=95.0, ma20=105.0)

        trade = size_entry(candle, self.state, V1_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.target, 105.0, places=6)

    def test_entry_does_not_require_ma20_above_close_unlike_v1(self) -> None:
        # ma20 (95) is BELOW close (100) here — v1.0.0's FROZEN_MA20 mode would reject
        # this (TARGET_NOT_ABOVE_ENTRY), but FIXED_1R mode doesn't depend on ma20 at all.
        state_v1 = MeanReversionState(equity=10000.0)
        state_t1r = MeanReversionState(equity=10000.0)
        candle = make_candle(close=100.0, ma20=95.0, bb_lower=101.0, ma200=90.0, rsi=30.0, atr=2.0)

        eval_v1 = evaluate_entry(candle, state_v1, V1_PARAMETERS)
        eval_t1r = evaluate_entry(candle, state_t1r, PARAMETERS)

        self.assertIn("TARGET_NOT_ABOVE_ENTRY", eval_v1.reasons)
        self.assertNotIn("TARGET_NOT_ABOVE_ENTRY", eval_t1r.reasons)
        self.assertTrue(eval_t1r.passed)


class Target1RRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "mean-reversion-v1.0.0-target-1r")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        t1r_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, t1r_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, t1r_variant.version)
        versions = {v.version for v in registry.list_versions("MEAN_REVERSION")}
        self.assertEqual(versions, {"mean-reversion-v1.0.0", "mean-reversion-v1.0.0-target-1r"})


if __name__ == "__main__":
    unittest.main()
