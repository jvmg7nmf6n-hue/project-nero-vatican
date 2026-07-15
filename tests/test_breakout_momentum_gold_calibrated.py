from __future__ import annotations

import unittest
from dataclasses import fields

from nero_core.strategies.breakout_momentum import (
    DEFAULT_PARAMETERS as V1_PARAMETERS,
    STRATEGY_ID,
    evaluate_entry,
    size_entry,
)
from nero_core.strategies.breakout_momentum import register_default_variant as register_v1
from nero_core.strategies.breakout_momentum_gold_calibrated import (
    GOLD_CALIBRATED_PARAMETERS,
    STRATEGY_VERSION,
    register_default_variant,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_breakout_momentum import make_candle


class GoldCalibratedParametersTest(unittest.TestCase):
    def test_fee_bps_and_slippage_bps_scaled_by_the_shared_measured_factor(self) -> None:
        self.assertAlmostEqual(GOLD_CALIBRATED_PARAMETERS.fee_bps, 10.0 * GOLD_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(GOLD_CALIBRATED_PARAMETERS.slippage_bps, 2.0 * GOLD_FEE_SCALE_FACTOR)
        self.assertLess(GOLD_CALIBRATED_PARAMETERS.fee_bps, V1_PARAMETERS.fee_bps)
        self.assertLess(GOLD_CALIBRATED_PARAMETERS.slippage_bps, V1_PARAMETERS.slippage_bps)

    def test_only_fee_and_slippage_fields_differ_from_v1_defaults(self) -> None:
        for field in fields(V1_PARAMETERS):
            v1_value = getattr(V1_PARAMETERS, field.name)
            gold_value = getattr(GOLD_CALIBRATED_PARAMETERS, field.name)
            if field.name in {"fee_bps", "slippage_bps"}:
                self.assertNotEqual(v1_value, gold_value, f"{field.name} should differ")
            else:
                self.assertEqual(v1_value, gold_value, f"{field.name} should be unchanged from v1")


class GoldCalibratedEntryExitLogicUnchangedTest(unittest.TestCase):
    def test_entry_evaluation_is_identical_to_v1_for_the_same_candle(self) -> None:
        candle = make_candle()
        state_v1 = MeanReversionState(equity=10000.0)
        state_gold = MeanReversionState(equity=10000.0)

        eval_v1 = evaluate_entry(candle, state_v1, V1_PARAMETERS)
        eval_gold = evaluate_entry(candle, state_gold, GOLD_CALIBRATED_PARAMETERS)

        self.assertEqual(eval_v1.passed, eval_gold.passed)
        self.assertEqual(eval_v1.reasons, eval_gold.reasons)

    def test_entry_evaluation_rejection_reasons_identical_for_a_failing_candle(self) -> None:
        candle = make_candle(rsi=30.0, ma200=150.0)
        state_v1 = MeanReversionState(equity=10000.0)
        state_gold = MeanReversionState(equity=10000.0)

        eval_v1 = evaluate_entry(candle, state_v1, V1_PARAMETERS)
        eval_gold = evaluate_entry(candle, state_gold, GOLD_CALIBRATED_PARAMETERS)

        self.assertEqual(eval_v1.reasons, eval_gold.reasons)

    def test_stop_distance_identical_lower_fees_only(self) -> None:
        # slippage_bps differs (that's part of the recalibration too), so the absolute
        # entry price — and therefore the absolute stop price — shifts slightly. What
        # must stay IDENTICAL is the risk distance itself: atr_stop_multiple * ATR.
        candle = make_candle()
        state_v1 = MeanReversionState(equity=10000.0)
        state_gold = MeanReversionState(equity=10000.0)

        trade_v1 = size_entry(candle, state_v1, V1_PARAMETERS)
        trade_gold = size_entry(candle, state_gold, GOLD_CALIBRATED_PARAMETERS)

        risk_distance_v1 = trade_v1.entry_price - trade_v1.stop_loss
        risk_distance_gold = trade_gold.entry_price - trade_gold.stop_loss
        self.assertAlmostEqual(risk_distance_v1, risk_distance_gold, places=6)
        self.assertAlmostEqual(V1_PARAMETERS.atr_stop_multiple * candle["atr"], risk_distance_gold, places=6)
        self.assertLess(trade_gold.entry_fee, trade_v1.entry_fee)


class GoldCalibratedRegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "breakout-momentum-v1.1.0-gold-calibrated")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_registers_alongside_v1_as_a_separate_version_of_the_same_strategy(self) -> None:
        registry = StrategyRegistry()

        v1_variant = register_v1(registry)
        gold_variant = register_default_variant(registry)

        self.assertEqual(v1_variant.strategy_id, gold_variant.strategy_id)
        self.assertNotEqual(v1_variant.version, gold_variant.version)
        versions = {v.version for v in registry.list_versions("BREAKOUT_MOMENTUM")}
        self.assertEqual(versions, {"breakout-momentum-v1.0.0", "breakout-momentum-v1.1.0-gold-calibrated"})


if __name__ == "__main__":
    unittest.main()
