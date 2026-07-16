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
from nero_core.strategies.mean_reversion_regime_filter import (
    PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


class RegimeFilterParametersTest(unittest.TestCase):
    def test_only_bb_buffer_differs_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            regime_value = getattr(PARAMETERS, field.name)
            if field.name == "lower_bb_buffer_atr":
                self.assertNotEqual(v1_value, regime_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, regime_value, f"{field.name} should be unchanged from v1")

    def test_value_matches_the_original_nero_candidate(self) -> None:
        self.assertEqual(PARAMETERS.lower_bb_buffer_atr, 0.1)

    def test_rsi_threshold_is_unchanged_from_v1_despite_the_candidates_name(self) -> None:
        # MR_REGIME_FILTER_V1's rsi_entry_below in the original source is 35.0 — same as
        # v1.0.0's default, not a stricter/looser threshold.
        self.assertEqual(PARAMETERS.rsi_entry_below, V1_PARAMETERS.rsi_entry_below)


class RegimeFilterEntryBehaviorTest(unittest.TestCase):
    """Proves the 0.1x ATR buffer actually catches a pullback that the strict v1.0.0
    band rejects, and is narrower than the already-ported 0.25x relaxed-pullback buffer."""

    def setUp(self) -> None:
        self.state_v1 = MeanReversionState(equity=10000.0)
        self.state_regime = MeanReversionState(equity=10000.0)

    def test_close_within_narrow_buffer_passes_regime_filter_but_not_v1(self) -> None:
        # bb_lower=101, atr=2.0 -> regime-filter threshold = 101 + 0.1*2 = 101.2.
        candle = make_candle(close=101.1, bb_lower=101.0, atr=2.0, rsi=30.0, ma200=95.0, ma20=105.0)

        eval_v1 = evaluate_entry(candle, self.state_v1, V1_PARAMETERS)
        eval_regime = evaluate_entry(candle, self.state_regime, PARAMETERS)

        self.assertIn("CLOSE_NOT_BELOW_LOWER_BB", eval_v1.reasons)
        self.assertNotIn("CLOSE_NOT_BELOW_LOWER_BB", eval_regime.reasons)

    def test_buffer_is_narrower_than_the_relaxed_pullback_port(self) -> None:
        from nero_core.strategies.mean_reversion_relaxed_pullback import PARAMETERS as RELAXED_PARAMETERS

        self.assertLess(PARAMETERS.lower_bb_buffer_atr, RELAXED_PARAMETERS.lower_bb_buffer_atr)

    def test_does_not_gate_on_any_quant_regime_signal(self) -> None:
        # There is no regime-related field on MeanReversionParameters at all (unlike
        # MeanReversionV2Parameters) — passing evaluate_entry only ever depends on the
        # candle's own indicators, confirming no hidden regime gate exists for this port.
        candle = make_candle(close=101.1, bb_lower=101.0, atr=2.0, rsi=30.0, ma200=95.0, ma20=105.0)

        evaluation = evaluate_entry(candle, self.state_regime, PARAMETERS)

        self.assertTrue(evaluation.passed)


class RegimeFilterRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "mean-reversion-v1.0.0-regime-filter")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        regime_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, regime_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, regime_variant.version)
        versions = {v.version for v in registry.list_versions("MEAN_REVERSION")}
        self.assertEqual(versions, {"mean-reversion-v1.0.0", "mean-reversion-v1.0.0-regime-filter"})


if __name__ == "__main__":
    unittest.main()
