from __future__ import annotations

import unittest

from nero_core.strategies.donchian_bracket_live_configs import (
    EURUSD_N20_PARAMETERS,
    GBPUSD_N20_PARAMETERS,
    GOLD_N20_PARAMETERS,
    STRATEGY_VERSION_EURUSD_N20,
    STRATEGY_VERSION_GBPUSD_N20,
    STRATEGY_VERSION_GOLD_N20,
    STRATEGY_VERSION_USDJPY_N40,
    USDJPY_N40_PARAMETERS,
    register_eurusd_n20_variant,
    register_gbpusd_n20_variant,
    register_gold_n20_variant,
    register_usdjpy_n40_variant,
)
from nero_core.strategies.donchian_breakout_bracket import STRATEGY_ID
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


class ParametersMatchNPresetTest(unittest.TestCase):
    def test_n20_configs_carry_20_candle_channel_and_30_week_holding_cap(self) -> None:
        for params in (GOLD_N20_PARAMETERS, EURUSD_N20_PARAMETERS, GBPUSD_N20_PARAMETERS):
            self.assertEqual(params.channel_period, 20)
            self.assertEqual(params.max_holding_hours, 30 * 168)

    def test_n40_config_carries_40_candle_channel_and_52_week_holding_cap(self) -> None:
        self.assertEqual(USDJPY_N40_PARAMETERS.channel_period, 40)
        self.assertEqual(USDJPY_N40_PARAMETERS.max_holding_hours, 52 * 168)

    def test_holding_cap_is_not_a_generic_default_shared_across_n_values(self) -> None:
        # N40's cap must NOT silently equal N20's cap -- this is the exact "generic
        # default instead of a per-N cap" mistake the task asked to guard against.
        self.assertNotEqual(USDJPY_N40_PARAMETERS.max_holding_hours, GOLD_N20_PARAMETERS.max_holding_hours)

    def test_fee_bps_matches_asset_class_convention(self) -> None:
        self.assertAlmostEqual(GOLD_N20_PARAMETERS.fee_bps, 10.0)  # metals
        self.assertAlmostEqual(EURUSD_N20_PARAMETERS.fee_bps, 5.0)  # forex
        self.assertAlmostEqual(GBPUSD_N20_PARAMETERS.fee_bps, 5.0)
        self.assertAlmostEqual(USDJPY_N40_PARAMETERS.fee_bps, 5.0)


class StrategyVersionUniquenessTest(unittest.TestCase):
    def test_all_4_version_strings_are_unique(self) -> None:
        versions = [STRATEGY_VERSION_GOLD_N20, STRATEGY_VERSION_EURUSD_N20, STRATEGY_VERSION_GBPUSD_N20, STRATEGY_VERSION_USDJPY_N40]
        self.assertEqual(len(versions), len(set(versions)))

    def test_all_4_asset_keys_are_unique_too(self) -> None:
        # (strategy_id, strategy_version, asset) collision check per the RMR/
        # verification_status.py precedent -- here strategy_id is shared (DONCHIAN_TREND)
        # but both strategy_version AND asset differ per config, so no key can collide.
        keys = [
            (STRATEGY_ID, STRATEGY_VERSION_GOLD_N20, "GOLD"),
            (STRATEGY_ID, STRATEGY_VERSION_EURUSD_N20, "EUR/USD"),
            (STRATEGY_ID, STRATEGY_VERSION_GBPUSD_N20, "GBP/USD"),
            (STRATEGY_ID, STRATEGY_VERSION_USDJPY_N40, "USD/JPY"),
        ]
        self.assertEqual(len(keys), len(set(keys)))


class RegistrationTest(unittest.TestCase):
    def test_each_variant_registers_once_and_rejects_a_second_registration(self) -> None:
        registry = StrategyRegistry()
        register_gold_n20_variant(registry)
        register_eurusd_n20_variant(registry)
        register_gbpusd_n20_variant(registry)
        register_usdjpy_n40_variant(registry)
        self.assertEqual(len(registry._variants), 4)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_gold_n20_variant(registry)


if __name__ == "__main__":
    unittest.main()
