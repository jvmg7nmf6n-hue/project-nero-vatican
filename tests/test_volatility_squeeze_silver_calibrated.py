from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.metals_calibration import SILVER_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.volatility_squeeze import (
    DEFAULT_PARAMETERS_MA100,
    DEFAULT_PARAMETERS_MA150,
    DEFAULT_PARAMETERS_MA200,
)
from nero_core.strategies.volatility_squeeze import register_ma200_variant as register_v1_ma200
from nero_core.strategies.volatility_squeeze_silver_calibrated import (
    SILVER_CALIBRATED_PARAMETERS_MA100,
    SILVER_CALIBRATED_PARAMETERS_MA150,
    SILVER_CALIBRATED_PARAMETERS_MA200,
    STRATEGY_VERSION_MA100,
    STRATEGY_VERSION_MA150,
    STRATEGY_VERSION_MA200,
    register_ma100_variant,
    register_ma150_variant,
    register_ma200_variant,
)

CASES = [
    (DEFAULT_PARAMETERS_MA200, SILVER_CALIBRATED_PARAMETERS_MA200, 200),
    (DEFAULT_PARAMETERS_MA150, SILVER_CALIBRATED_PARAMETERS_MA150, 150),
    (DEFAULT_PARAMETERS_MA100, SILVER_CALIBRATED_PARAMETERS_MA100, 100),
]


class SilverCalibratedParametersTest(unittest.TestCase):
    def test_only_fee_slippage_and_max_holding_hours_differ_from_base_defaults(self) -> None:
        for base_params, silver_params, _ma_period in CASES:
            for field in fields(base_params):
                base_value = getattr(base_params, field.name)
                silver_value = getattr(silver_params, field.name)
                if field.name in {"fee_bps", "slippage_bps", "max_holding_hours"}:
                    self.assertNotEqual(base_value, silver_value, f"{field.name} should differ")
                else:
                    self.assertEqual(base_value, silver_value, f"{field.name} should be unchanged")

    def test_fee_bps_and_slippage_bps_scaled_by_silvers_own_factor(self) -> None:
        for _base_params, silver_params, _ma_period in CASES:
            self.assertAlmostEqual(silver_params.fee_bps, 10.0 * SILVER_FEE_SCALE_FACTOR)
            self.assertAlmostEqual(silver_params.slippage_bps, 2.0 * SILVER_FEE_SCALE_FACTOR)

    def test_max_holding_hours_matches_24h_timeframe(self) -> None:
        for _base_params, silver_params, _ma_period in CASES:
            self.assertEqual(silver_params.max_holding_hours, 576)

    def test_trend_ma_period_preserved_per_variant(self) -> None:
        for _base_params, silver_params, ma_period in CASES:
            self.assertEqual(silver_params.trend_ma_period, ma_period)


class SilverCalibratedRegistrationTest(unittest.TestCase):
    def test_register_default_variants_use_correct_versions(self) -> None:
        registry = StrategyRegistry()

        ma200 = register_ma200_variant(registry)
        ma150 = register_ma150_variant(registry)
        ma100 = register_ma100_variant(registry)

        self.assertEqual(ma200.version, STRATEGY_VERSION_MA200)
        self.assertEqual(ma150.version, STRATEGY_VERSION_MA150)
        self.assertEqual(ma100.version, STRATEGY_VERSION_MA100)
        self.assertEqual(ma200.version, "volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_ma200_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_ma200_variant(registry)

    def test_registers_alongside_base_ma200_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        base_variant = register_v1_ma200(registry)
        silver_variant = register_ma200_variant(registry)

        self.assertEqual(base_variant.strategy_id, silver_variant.strategy_id)
        self.assertNotEqual(base_variant.version, silver_variant.version)


if __name__ == "__main__":
    unittest.main()
