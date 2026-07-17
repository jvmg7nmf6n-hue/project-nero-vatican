from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS as V1_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import (
    register_default_variant as register_v1,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_regime_scaled_risk import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


class ParametersTest(unittest.TestCase):
    def test_only_regime_scaled_risk_differs_from_v1(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            v2_value = getattr(PARAMETERS, field.name)
            if field.name == "regime_scaled_risk":
                self.assertFalse(v1_value)
                self.assertTrue(v2_value)
            else:
                self.assertEqual(v1_value, v2_value, f"{field.name} should be unchanged from v1")

    def test_still_gold_calibrated_and_1week_holding_cap(self) -> None:
        self.assertLess(PARAMETERS.fee_bps, 10.0)  # still GOLD fee-scaled
        self.assertEqual(PARAMETERS.max_holding_hours, V1_PARAMETERS.max_holding_hours)


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "breakout-momentum-v1.3.0-gold-calibrated-1week-regime-scaled-risk")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        v2_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, v2_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, v2_variant.version)


if __name__ == "__main__":
    unittest.main()
