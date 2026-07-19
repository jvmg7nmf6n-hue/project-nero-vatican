from __future__ import annotations

import unittest

from nero_core.strategies.range_mean_reversion import STRATEGY_ID
from nero_core.strategies.range_mean_reversion_long_only_confirmation import (
    LONG_ONLY_CONFIRMATION_PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


class LongOnlyConfirmationParametersTest(unittest.TestCase):
    def test_allow_short_is_false(self) -> None:
        self.assertFalse(LONG_ONLY_CONFIRMATION_PARAMETERS.allow_short)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "range-mean-reversion-v1.4.0-long-only-confirmation")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
