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
from nero_core.strategies.mean_reversion_relaxed_pullback import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


class RelaxedPullbackParametersTest(unittest.TestCase):
    def test_only_rsi_and_bb_buffer_differ_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            relaxed_value = getattr(PARAMETERS, field.name)
            if field.name in {"rsi_entry_below", "lower_bb_buffer_atr"}:
                self.assertNotEqual(v1_value, relaxed_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, relaxed_value, f"{field.name} should be unchanged from v1")

    def test_values_match_the_original_nero_candidate(self) -> None:
        self.assertEqual(PARAMETERS.rsi_entry_below, 40.0)
        self.assertEqual(PARAMETERS.lower_bb_buffer_atr, 0.25)


class RelaxedPullbackEntryBehaviorTest(unittest.TestCase):
    """Proves the relaxed buffer actually catches a pullback that the strict v1.0.0
    band rejects — the entire point of this port."""

    def setUp(self) -> None:
        self.state_v1 = MeanReversionState(equity=10000.0)
        self.state_relaxed = MeanReversionState(equity=10000.0)

    def test_close_within_buffer_of_lower_band_passes_relaxed_but_not_v1(self) -> None:
        # bb_lower=101, atr=2.0 -> relaxed threshold = 101 + 0.25*2 = 101.5.
        # close=101.4 is ABOVE the strict band (fails v1) but within the relaxed buffer.
        candle = make_candle(close=101.4, bb_lower=101.0, atr=2.0, rsi=35.0, ma200=95.0, ma20=105.0)

        eval_v1 = evaluate_entry(candle, self.state_v1, V1_PARAMETERS)
        eval_relaxed = evaluate_entry(candle, self.state_relaxed, PARAMETERS)

        self.assertIn("CLOSE_NOT_BELOW_LOWER_BB", eval_v1.reasons)
        self.assertNotIn("CLOSE_NOT_BELOW_LOWER_BB", eval_relaxed.reasons)


class RelaxedPullbackRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "mean-reversion-v1.0.0-relaxed-pullback")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        relaxed_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, relaxed_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, relaxed_variant.version)
        versions = {v.version for v in registry.list_versions("MEAN_REVERSION")}
        self.assertEqual(versions, {"mean-reversion-v1.0.0", "mean-reversion-v1.0.0-relaxed-pullback"})


if __name__ == "__main__":
    unittest.main()
