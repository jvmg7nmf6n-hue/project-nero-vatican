from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.mean_reversion import (
    MeanReversionState,
    STRATEGY_ID,
    evaluate_exit,
    size_entry,
)
from nero_core.strategies.mean_reversion_gold_calibrated import (
    GOLD_CALIBRATED_PARAMETERS,
)
from nero_core.strategies.mean_reversion_gold_calibrated import (
    register_default_variant as register_gold_calibrated,
)
from nero_core.strategies.mean_reversion_gold_calibrated_1week import (
    GOLD_CALIBRATED_1WEEK_PARAMETERS,
    STRATEGY_VERSION,
    WEEKLY_MAX_HOLDING_HOURS,
    register_default_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_mean_reversion_strategy import make_candle


class OneWeekParametersTest(unittest.TestCase):
    def test_max_holding_hours_exceeds_a_single_1week_candle(self) -> None:
        # The bug: the inherited crypto default (24h) is shorter than one 1week candle
        # (168h). The fix must make the cap comfortably larger than one candle so a
        # trade can actually be evaluated against stop/target on later candles.
        one_candle_hours = 7 * 24
        self.assertGreater(GOLD_CALIBRATED_1WEEK_PARAMETERS.max_holding_hours, one_candle_hours)
        self.assertEqual(GOLD_CALIBRATED_1WEEK_PARAMETERS.max_holding_hours, WEEKLY_MAX_HOLDING_HOURS)

    def test_only_max_holding_hours_differs_from_gold_calibrated_base(self) -> None:
        for field in fields(GOLD_CALIBRATED_PARAMETERS):
            base_value = getattr(GOLD_CALIBRATED_PARAMETERS, field.name)
            weekly_value = getattr(GOLD_CALIBRATED_1WEEK_PARAMETERS, field.name)
            if field.name == "max_holding_hours":
                self.assertNotEqual(base_value, weekly_value)
            else:
                self.assertEqual(base_value, weekly_value, f"{field.name} should be unchanged")


class OneWeekRegressionTest(unittest.TestCase):
    """Proves the actual bug: with the old (24h) cap, a trade entered on one 1week
    candle is force-closed via TIME on the very next candle regardless of price action.
    With the fixed cap, the same next candle does NOT trigger a TIME exit."""

    def test_old_cap_forces_time_exit_on_the_very_next_weekly_candle(self) -> None:
        state = MeanReversionState(equity=10000.0)
        state.open_trade = size_entry(make_candle(close_time=0), state, GOLD_CALIBRATED_PARAMETERS)

        # high/low stay strictly between the stop (~entry - 3) and the frozen MA20
        # target (105) so TIME is the only exit condition that can fire here.
        next_weekly_candle = make_candle(close_time=7 * 24 * 3600000, high=102.0, low=99.0, close=100.5)
        exit_event = evaluate_exit(next_weekly_candle, state, GOLD_CALIBRATED_PARAMETERS)

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")

    def test_fixed_cap_does_not_force_exit_on_the_next_weekly_candle(self) -> None:
        state = MeanReversionState(equity=10000.0)
        state.open_trade = size_entry(make_candle(close_time=0), state, GOLD_CALIBRATED_1WEEK_PARAMETERS)

        next_weekly_candle = make_candle(close_time=7 * 24 * 3600000, high=102.0, low=99.0, close=100.5)
        exit_event = evaluate_exit(next_weekly_candle, state, GOLD_CALIBRATED_1WEEK_PARAMETERS)

        self.assertIsNone(exit_event)


class OneWeekRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "mean-reversion-v1.2.0-gold-calibrated-1week")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_gold_calibrated_as_a_separate_version(self) -> None:
        registry = StrategyRegistry()

        gold_variant = register_gold_calibrated(registry)
        weekly_variant = register_default_variant(registry)

        self.assertEqual(gold_variant.strategy_id, weekly_variant.strategy_id)
        self.assertNotEqual(gold_variant.version, weekly_variant.version)
        versions = {v.version for v in registry.list_versions("MEAN_REVERSION")}
        self.assertIn("mean-reversion-v1.1.0-gold-calibrated", versions)
        self.assertIn("mean-reversion-v1.2.0-gold-calibrated-1week", versions)


if __name__ == "__main__":
    unittest.main()
