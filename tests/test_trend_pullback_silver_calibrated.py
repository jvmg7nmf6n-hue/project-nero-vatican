from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.metals_calibration import SILVER_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as V1_PARAMETERS
from nero_core.strategies.trend_pullback import register_default_variant as register_v1
from nero_core.strategies.trend_pullback_silver_calibrated import (
    SILVER_CALIBRATED_PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)


class SilverCalibratedParametersTest(unittest.TestCase):
    def test_only_fee_slippage_and_max_holding_hours_differ_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            silver_value = getattr(SILVER_CALIBRATED_PARAMETERS, field.name)
            if field.name in {"fee_bps", "slippage_bps", "max_holding_hours"}:
                self.assertNotEqual(v1_value, silver_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, silver_value, f"{field.name} should be unchanged from v1")

    def test_fee_bps_and_slippage_bps_scaled_by_silvers_own_factor(self) -> None:
        self.assertAlmostEqual(SILVER_CALIBRATED_PARAMETERS.fee_bps, 10.0 * SILVER_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(SILVER_CALIBRATED_PARAMETERS.slippage_bps, 2.0 * SILVER_FEE_SCALE_FACTOR)

    def test_max_holding_hours_matches_24h_timeframe_not_1h_reference(self) -> None:
        self.assertEqual(SILVER_CALIBRATED_PARAMETERS.max_holding_hours, 576)


class SilverCalibratedRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "trend-pullback-v1.5.0-silver-calibrated-24h")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        silver_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, silver_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, silver_variant.version)


if __name__ == "__main__":
    unittest.main()
