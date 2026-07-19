from __future__ import annotations

import unittest

from nero_core.strategies.range_mean_reversion import STRATEGY_ID, RangeMeanReversionState, evaluate_entry
from nero_core.strategies.range_mean_reversion_long_only import (
    LONG_ONLY_PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_range_mean_reversion import _make_candle


class LongOnlyParametersTest(unittest.TestCase):
    def test_allow_short_is_false(self) -> None:
        self.assertFalse(LONG_ONLY_PARAMETERS.allow_short)

    def test_everything_else_unchanged_from_v1_0_0(self) -> None:
        from dataclasses import fields

        from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS

        for field in fields(DEFAULT_PARAMETERS):
            if field.name == "allow_short":
                continue
            self.assertEqual(
                getattr(DEFAULT_PARAMETERS, field.name), getattr(LONG_ONLY_PARAMETERS, field.name), field.name
            )


class LongOnlyEntryBehaviorTest(unittest.TestCase):
    def test_long_entry_still_works(self) -> None:
        candle = _make_candle(close=90.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state, LONG_ONLY_PARAMETERS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_short_entry_is_disabled(self) -> None:
        candle = _make_candle(close=110.0, adx=20.0)
        state = RangeMeanReversionState(equity=10000.0)
        evaluation = evaluate_entry(candle, state, LONG_ONLY_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("SHORT_DISABLED", evaluation.reasons)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.1.0-long-only")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
