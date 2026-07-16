from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as V1_PARAMETERS,
    STRATEGY_ID,
    MeanReversionState,
    evaluate_entry,
)
from nero_core.strategies.mean_reversion import register_default_variant as register_v1
from nero_core.strategies.mean_reversion_deep_value import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


class DeepValueParametersTest(unittest.TestCase):
    def test_only_rsi_threshold_differs_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            deep_value = getattr(PARAMETERS, field.name)
            if field.name == "rsi_entry_below":
                self.assertNotEqual(v1_value, deep_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, deep_value, f"{field.name} should be unchanged from v1")

    def test_value_matches_the_original_nero_candidate(self) -> None:
        self.assertEqual(PARAMETERS.rsi_entry_below, 30.0)


class DeepValueEntryBehaviorTest(unittest.TestCase):
    """Proves the stricter RSI threshold actually rejects a shallower dip that v1.0.0
    would accept — the entire point of this port."""

    def setUp(self) -> None:
        self.state_v1 = MeanReversionState(equity=10000.0)
        self.state_deep_value = MeanReversionState(equity=10000.0)

    def test_rsi_between_30_and_35_passes_v1_but_not_deep_value(self) -> None:
        candle = make_candle(rsi=32.0, close=100.0, bb_lower=101.0, ma200=95.0, ma20=105.0)

        eval_v1 = evaluate_entry(candle, self.state_v1, V1_PARAMETERS)
        eval_deep_value = evaluate_entry(candle, self.state_deep_value, PARAMETERS)

        self.assertNotIn("RSI_NOT_BELOW_35", eval_v1.reasons)
        self.assertIn("RSI_NOT_BELOW_35", eval_deep_value.reasons)


class DeepValueRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "mean-reversion-v1.0.0-deep-value")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        deep_value_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, deep_value_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, deep_value_variant.version)
        versions = {v.version for v in registry.list_versions("MEAN_REVERSION")}
        self.assertEqual(versions, {"mean-reversion-v1.0.0", "mean-reversion-v1.0.0-deep-value"})


if __name__ == "__main__":
    unittest.main()
