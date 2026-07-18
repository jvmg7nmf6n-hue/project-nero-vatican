from __future__ import annotations

import unittest
from dataclasses import replace

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS as MR_PARAMETERS
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR
from nero_core.strategies.metals_calibration import (
    PLATINUM_FEE_SCALE_FACTOR,
    SILVER_FEE_SCALE_FACTOR,
)
from nero_core.strategies.timeframe_calibration import (
    FEE_SCALE_FACTOR_BY_ASSET,
    build_calibrated_params,
    max_holding_hours_for_timeframe,
    scaled_fees_for_asset,
)


class ScaledFeesForAssetTest(unittest.TestCase):
    def test_gold_scales_fee_and_slippage(self) -> None:
        scaled = scaled_fees_for_asset(MR_PARAMETERS, "GOLD")
        self.assertAlmostEqual(scaled.fee_bps, MR_PARAMETERS.fee_bps * GOLD_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(scaled.slippage_bps, MR_PARAMETERS.slippage_bps * GOLD_FEE_SCALE_FACTOR)

    def test_silver_scales_by_its_own_derived_factor(self) -> None:
        scaled = scaled_fees_for_asset(MR_PARAMETERS, "SILVER")
        self.assertAlmostEqual(scaled.fee_bps, MR_PARAMETERS.fee_bps * SILVER_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(scaled.slippage_bps, MR_PARAMETERS.slippage_bps * SILVER_FEE_SCALE_FACTOR)
        self.assertNotAlmostEqual(SILVER_FEE_SCALE_FACTOR, GOLD_FEE_SCALE_FACTOR)

    def test_platinum_scales_by_its_own_derived_factor(self) -> None:
        scaled = scaled_fees_for_asset(MR_PARAMETERS, "PLATINUM")
        self.assertAlmostEqual(scaled.fee_bps, MR_PARAMETERS.fee_bps * PLATINUM_FEE_SCALE_FACTOR)
        self.assertNotAlmostEqual(PLATINUM_FEE_SCALE_FACTOR, GOLD_FEE_SCALE_FACTOR)

    def test_unlisted_asset_is_unchanged(self) -> None:
        scaled = scaled_fees_for_asset(MR_PARAMETERS, "BTC")
        self.assertEqual(scaled.fee_bps, MR_PARAMETERS.fee_bps)
        self.assertEqual(scaled.slippage_bps, MR_PARAMETERS.slippage_bps)

    def test_registry_contains_exactly_the_three_calibrated_assets(self) -> None:
        self.assertEqual(set(FEE_SCALE_FACTOR_BY_ASSET), {"GOLD", "SILVER", "PLATINUM"})


class BuildCalibratedParamsTest(unittest.TestCase):
    def test_gold_behavior_is_unchanged_by_the_dict_generalization(self) -> None:
        params = build_calibrated_params(MR_PARAMETERS, "1week", "GOLD")
        self.assertAlmostEqual(params.fee_bps, MR_PARAMETERS.fee_bps * GOLD_FEE_SCALE_FACTOR)
        self.assertEqual(params.max_holding_hours, max_holding_hours_for_timeframe("1week"))

    def test_silver_gets_timeframe_calibration_and_its_own_fee_scale(self) -> None:
        params = build_calibrated_params(MR_PARAMETERS, "12h", "SILVER")
        self.assertAlmostEqual(params.fee_bps, MR_PARAMETERS.fee_bps * SILVER_FEE_SCALE_FACTOR)
        self.assertEqual(params.max_holding_hours, max_holding_hours_for_timeframe("12h"))

    def test_crypto_asset_only_gets_timeframe_calibration_no_fee_scaling(self) -> None:
        params = build_calibrated_params(MR_PARAMETERS, "4h", "BNB")
        self.assertEqual(params.fee_bps, MR_PARAMETERS.fee_bps)
        self.assertEqual(params.max_holding_hours, max_holding_hours_for_timeframe("4h"))

    def test_does_not_mutate_or_alias_base_params(self) -> None:
        base = replace(MR_PARAMETERS)
        build_calibrated_params(base, "2h", "SILVER")
        self.assertEqual(base.fee_bps, MR_PARAMETERS.fee_bps)


if __name__ == "__main__":
    unittest.main()
