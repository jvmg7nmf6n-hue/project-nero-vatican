from __future__ import annotations

import unittest

from nero_core.strategies.range_mean_reversion import STRATEGY_ID, RangeMeanReversionState, evaluate_entry
from nero_core.strategies.range_mean_reversion_adx_falling import (
    ADX_FALLING_PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_range_mean_reversion import _make_candle


class AdxFallingParametersTest(unittest.TestCase):
    def test_require_adx_falling_is_true(self) -> None:
        self.assertTrue(ADX_FALLING_PARAMETERS.require_adx_falling)
        self.assertEqual(ADX_FALLING_PARAMETERS.adx_falling_lookback, 3)

    def test_directions_both_still_enabled(self) -> None:
        self.assertTrue(ADX_FALLING_PARAMETERS.allow_short)


class AdxFallingEntryBehaviorTest(unittest.TestCase):
    def test_entry_rejected_when_adx_not_falling(self) -> None:
        candle = _make_candle(close=90.0, adx=20.0, adx_falling=False)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state, ADX_FALLING_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("ADX_NOT_FALLING", evaluation.reasons)

    def test_long_entry_passes_when_adx_is_falling(self) -> None:
        candle = _make_candle(close=90.0, adx=20.0, adx_falling=True)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state, ADX_FALLING_PARAMETERS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_short_entry_passes_when_adx_is_falling(self) -> None:
        candle = _make_candle(close=110.0, adx=20.0, adx_falling=True)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state, ADX_FALLING_PARAMETERS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.2.0-adx-falling")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
