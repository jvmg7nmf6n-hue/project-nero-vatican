from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_DEFAULT_PARAMETERS
from nero_core.strategies.metals_calibration import PLATINUM_FEE_SCALE_FACTOR, SILVER_FEE_SCALE_FACTOR
from tools.backtest_metals_phase_a_sweep import (
    _donchian_params_for_asset,
    align_pair_candles_by_date,
    donchian_eligible_mask,
    find_qualifying,
    macro_risk_on_eligible_mask,
    volatility_squeeze_regime_mask,
)


def _candle(day: str, hour: int, close: float) -> dict[str, object]:
    ts = pd.Timestamp(f"{day} {hour:02d}:00:00", tz="UTC")
    close_time = int(ts.timestamp() * 1000)
    return {"close_time": close_time, "date": ts, "close": close}


class AlignPairCandlesByDateTest(unittest.TestCase):
    def test_aligns_same_calendar_day_despite_different_intraday_hour_stamps(self) -> None:
        # GOLD stamped at 00:00 UTC, SILVER at 04:00 UTC for the same trading days —
        # the exact-close_time join this replaces would find zero overlap here.
        gold = pd.DataFrame([_candle("2026-07-01", 0, 100.0), _candle("2026-07-02", 0, 101.0)])
        silver = pd.DataFrame([_candle("2026-07-01", 4, 25.0), _candle("2026-07-02", 4, 25.5)])

        aligned = align_pair_candles_by_date(gold, silver, "GOLD", "SILVER")

        self.assertEqual(len(aligned), 2)
        self.assertIn("GOLD_close", aligned.columns)
        self.assertIn("SILVER_close", aligned.columns)
        self.assertEqual(aligned["GOLD_close"].tolist(), [100.0, 101.0])
        self.assertEqual(aligned["SILVER_close"].tolist(), [25.0, 25.5])
        # canonical timestamp comes from the x (GOLD) leg
        self.assertTrue(aligned["close_time"].is_monotonic_increasing)

    def test_drops_days_present_in_only_one_leg(self) -> None:
        gold = pd.DataFrame([_candle("2026-07-01", 0, 100.0), _candle("2026-07-02", 0, 101.0)])
        silver = pd.DataFrame([_candle("2026-07-01", 4, 25.0)])  # missing 07-02

        aligned = align_pair_candles_by_date(gold, silver, "GOLD", "SILVER")

        self.assertEqual(len(aligned), 1)


class DonchianParamsForAssetTest(unittest.TestCase):
    def test_silver_uses_its_own_scale_not_golds_baked_in_default(self) -> None:
        params = _donchian_params_for_asset("SILVER")
        self.assertAlmostEqual(params.fee_bps, 10.0 * SILVER_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(params.slippage_bps, 2.0 * SILVER_FEE_SCALE_FACTOR)
        # must NOT equal the GOLD-baked default (that would be double/wrong scaling)
        self.assertNotAlmostEqual(params.fee_bps, DONCHIAN_DEFAULT_PARAMETERS.fee_bps)

    def test_platinum_uses_its_own_scale(self) -> None:
        params = _donchian_params_for_asset("PLATINUM")
        self.assertAlmostEqual(params.fee_bps, 10.0 * PLATINUM_FEE_SCALE_FACTOR)

    def test_only_fee_and_slippage_change_from_defaults(self) -> None:
        params = _donchian_params_for_asset("SILVER")
        self.assertEqual(params.entry_channel_period, DONCHIAN_DEFAULT_PARAMETERS.entry_channel_period)
        self.assertEqual(params.exit_channel_period, DONCHIAN_DEFAULT_PARAMETERS.exit_channel_period)
        self.assertEqual(params.risk_per_trade, DONCHIAN_DEFAULT_PARAMETERS.risk_per_trade)


class EligibleMaskTest(unittest.TestCase):
    def test_volatility_squeeze_regime_mask_is_close_above_trend_ma(self) -> None:
        evaluable = pd.DataFrame({"close": [10.0, 9.0, 11.0], "trend_ma": [10.5, 10.5, 10.5]})
        mask = volatility_squeeze_regime_mask(evaluable)
        self.assertEqual(mask.tolist(), [False, False, True])

    def test_donchian_eligible_mask_is_always_true(self) -> None:
        evaluable = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        mask = donchian_eligible_mask(evaluable)
        self.assertTrue(mask.all())
        self.assertEqual(len(mask), 3)

    def test_macro_risk_on_eligible_mask_matches_risk_on_column(self) -> None:
        evaluable = pd.DataFrame({"risk_on": [True, False, None]})
        mask = macro_risk_on_eligible_mask(evaluable)
        self.assertEqual(mask.tolist(), [True, False, False])


class FindQualifyingTest(unittest.TestCase):
    def _row(self, train_trades, train_exp, test_trades, test_exp, error=None) -> dict[str, object]:
        if error is not None:
            return {"asset": "X", "timeframe": "1", "strategy": "S", "error": error}
        return {
            "asset": "X", "timeframe": "1", "strategy": "S",
            "train": {"trades": train_trades, "expectancy_r": train_exp},
            "test": {"trades": test_trades, "expectancy_r": test_exp},
        }

    def test_qualifies_only_when_positive_and_adequate_both_halves(self) -> None:
        rows = [
            self._row(30, 0.1, 25, 0.2),  # qualifies
            self._row(30, 0.1, 25, -0.1),  # negative test half
            self._row(10, 0.1, 25, 0.2),  # train below min sample
            self._row(30, 0.1, 25, 0.2, error="fetch failed"),  # errored row excluded
        ]
        qualifying = find_qualifying(rows)
        self.assertEqual(len(qualifying), 1)


if __name__ == "__main__":
    unittest.main()
