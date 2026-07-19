from __future__ import annotations

import unittest

from nero_core.strategies.orderflow_imbalance import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    OrderflowIndicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    size_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry

ABOVE_MA = OrderflowIndicators(close=110.0, ma20=100.0, atr=2.0)
BELOW_MA = OrderflowIndicators(close=90.0, ma20=100.0, atr=2.0)


class EvaluateEntryTest(unittest.TestCase):
    def test_long_entry_when_ratio_above_threshold_and_close_above_ma20(self) -> None:
        evaluation = evaluate_entry(3.5, ABOVE_MA, has_open_position=False)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG")

    def test_short_entry_when_ratio_below_threshold_and_close_below_ma20(self) -> None:
        evaluation = evaluate_entry(0.2, BELOW_MA, has_open_position=False)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "SHORT")

    def test_no_entry_when_ratio_high_but_close_below_ma20(self) -> None:
        evaluation = evaluate_entry(3.5, BELOW_MA, has_open_position=False)
        self.assertFalse(evaluation.passed)
        self.assertIn("NO_ENTRY_CONDITION_MET", evaluation.reasons)

    def test_no_entry_when_ratio_at_exactly_threshold(self) -> None:
        evaluation = evaluate_entry(3.0, ABOVE_MA, has_open_position=False)
        self.assertFalse(evaluation.passed)

    def test_rejected_when_open_position_exists(self) -> None:
        evaluation = evaluate_entry(3.5, ABOVE_MA, has_open_position=True)
        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_POSITION_EXISTS", evaluation.reasons)

    def test_none_ratio_never_treated_as_extreme_value(self) -> None:
        evaluation = evaluate_entry(None, ABOVE_MA, has_open_position=False)
        self.assertFalse(evaluation.passed)
        self.assertIn("IMBALANCE_RATIO_UNDEFINED", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_long_stop_below_entry_short_stop_above_entry(self) -> None:
        long_trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)
        short_trade = size_entry("SHORT", close=100.0, atr=2.0, equity=10000.0)
        self.assertLess(long_trade.stop_loss, 100.0)
        self.assertGreater(short_trade.stop_loss, 100.0)

    def test_risk_dollars_matches_half_percent_of_equity(self) -> None:
        trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)
        self.assertAlmostEqual(trade.risk_dollars, 10000.0 * 0.005)

    def test_zero_atr_returns_none(self) -> None:
        self.assertIsNone(size_entry("LONG", close=100.0, atr=0.0, equity=10000.0))


class EvaluateExitTest(unittest.TestCase):
    def test_long_stop_takes_priority_over_ratio_reversal(self) -> None:
        trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)  # stop_loss = 96.0
        indicators = OrderflowIndicators(close=95.0, ma20=100.0, atr=2.0)
        decision = evaluate_exit(trade, imbalance_ratio=1.0, indicators=indicators)  # ratio also below exit_ratio_long
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.exit_reason, "STOP")

    def test_long_ratio_reversal_exit(self) -> None:
        trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)
        indicators = OrderflowIndicators(close=101.0, ma20=100.0, atr=2.0)
        decision = evaluate_exit(trade, imbalance_ratio=1.0, indicators=indicators)  # below exit_ratio_long=1.5
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.exit_reason, "RATIO_REVERSAL")

    def test_short_ratio_reversal_exit(self) -> None:
        trade = size_entry("SHORT", close=100.0, atr=2.0, equity=10000.0)
        indicators = OrderflowIndicators(close=99.0, ma20=100.0, atr=2.0)
        decision = evaluate_exit(trade, imbalance_ratio=0.8, indicators=indicators)  # above exit_ratio_short=0.67
        self.assertTrue(decision.should_exit)
        self.assertEqual(decision.exit_reason, "RATIO_REVERSAL")

    def test_no_exit_while_ratio_between_thresholds_and_no_stop_hit(self) -> None:
        trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)
        indicators = OrderflowIndicators(close=101.0, ma20=100.0, atr=2.0)
        decision = evaluate_exit(trade, imbalance_ratio=2.0, indicators=indicators)
        self.assertFalse(decision.should_exit)

    def test_none_ratio_never_triggers_ratio_exit_only_stop_can_fire(self) -> None:
        trade = size_entry("LONG", close=100.0, atr=2.0, equity=10000.0)
        indicators = OrderflowIndicators(close=101.0, ma20=100.0, atr=2.0)
        decision = evaluate_exit(trade, imbalance_ratio=None, indicators=indicators)
        self.assertFalse(decision.should_exit)


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "orderflow-imbalance-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_default_parameters_match_task_spec(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.entry_ratio_long, 3.0)
        self.assertAlmostEqual(DEFAULT_PARAMETERS.entry_ratio_short, 0.33, places=2)
        self.assertEqual(DEFAULT_PARAMETERS.exit_ratio_long, 1.5)
        self.assertAlmostEqual(DEFAULT_PARAMETERS.exit_ratio_short, 0.67, places=2)
        self.assertEqual(DEFAULT_PARAMETERS.atr_stop_multiple, 2.0)
        self.assertEqual(DEFAULT_PARAMETERS.risk_per_trade, 0.005)


if __name__ == "__main__":
    unittest.main()
