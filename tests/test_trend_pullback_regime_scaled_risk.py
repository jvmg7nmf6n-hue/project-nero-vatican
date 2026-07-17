from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as V1_PARAMETERS
from nero_core.strategies.trend_pullback import STRATEGY_ID
from nero_core.strategies.trend_pullback import register_default_variant as register_v1
from nero_core.strategies.trend_pullback_regime_scaled_risk import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)


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


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "trend-pullback-v1.1.0-regime-scaled-risk")

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
        versions = {v.version for v in registry.list_versions(STRATEGY_ID)}
        self.assertEqual(versions, {"trend-pullback-v1.0.0", "trend-pullback-v1.1.0-regime-scaled-risk"})


if __name__ == "__main__":
    unittest.main()
