from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult, ForexDataUnavailableError
from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS
from tests.test_council_engine import _make_candle_row
from tools.backtest_range_mean_reversion_sweep import (
    FOREX_FEE_BPS,
    FOREX_SLIPPAGE_BPS,
    calibrated_params_for,
    find_qualifying,
    range_random_baseline,
    run_sweep,
)


class CalibratedParamsForTest(unittest.TestCase):
    def test_forex_gets_flat_fee(self) -> None:
        params = calibrated_params_for("EUR/USD")
        self.assertEqual(params.fee_bps, FOREX_FEE_BPS)
        self.assertEqual(params.slippage_bps, FOREX_SLIPPAGE_BPS)

    def test_gold_gets_its_own_scale_factor_not_forex_flat_fee(self) -> None:
        params = calibrated_params_for("GOLD")
        self.assertNotEqual(params.fee_bps, FOREX_FEE_BPS)
        self.assertNotEqual(params.fee_bps, DEFAULT_PARAMETERS.fee_bps)  # scaled, not default crypto

    def test_silver_gets_its_own_scale_factor_different_from_gold(self) -> None:
        gold_params = calibrated_params_for("GOLD")
        silver_params = calibrated_params_for("SILVER")
        self.assertNotEqual(gold_params.fee_bps, silver_params.fee_bps)

    def test_crypto_gets_unscaled_default(self) -> None:
        params = calibrated_params_for("BTC")
        self.assertEqual(params.fee_bps, DEFAULT_PARAMETERS.fee_bps)
        self.assertEqual(params.slippage_bps, DEFAULT_PARAMETERS.slippage_bps)


def _oscillating_history(n: int = 300, hours_per_candle: int = 4) -> pd.DataFrame:
    """A ranging-ish series (small oscillation) with enough length for ADX/Bollinger
    warmup — used purely to smoke-test the sweep's wiring, not to assert on specific
    trade outcomes."""
    rows = []
    close_time = 0
    for i in range(n):
        close = 100.0 + (3.0 if i % 4 < 2 else -3.0)
        rows.append(_make_candle_row(close_time, close))
        close_time += hours_per_candle * 3_600_000
    return pd.DataFrame(rows)


class RangeRandomBaselineTest(unittest.TestCase):
    def test_returns_none_when_no_eligible_candles(self) -> None:
        evaluable = pd.DataFrame({"adx": [30.0, 40.0]})
        result = range_random_baseline(evaluable, pd.Series([False, False]), DEFAULT_PARAMETERS, 0.1, 5)
        self.assertIsNone(result)

    def test_returns_none_when_target_trade_count_is_zero(self) -> None:
        evaluable = pd.DataFrame({"adx": [10.0, 10.0]})
        result = range_random_baseline(evaluable, pd.Series([True, True]), DEFAULT_PARAMETERS, 0.1, 0)
        self.assertIsNone(result)


class RunSweepSmokeTest(unittest.TestCase):
    def test_forex_leg_runs_without_error_over_a_small_mocked_universe(self) -> None:
        history = _oscillating_history()

        def _fake_forex_fetch(pair, timeframe):
            if pair == "BROKEN/USD":
                raise ForexDataUnavailableError("no data")
            return ForexDataResult(prices=history, source="test-fixture", pair=pair, timeframe=timeframe)

        with patch("tools.backtest_range_mean_reversion_sweep.FOREX_PAIRS", ["EUR/USD", "BROKEN/USD"]), patch(
            "tools.backtest_range_mean_reversion_sweep.FOREX_TIMEFRAMES", ["4h"]
        ), patch("tools.backtest_range_mean_reversion_sweep.METALS", []), patch(
            "tools.backtest_range_mean_reversion_sweep.TIER2_CRYPTO", []
        ), patch("tools.backtest_range_mean_reversion_sweep.TIER3_CRYPTO", []), patch(
            "tools.backtest_range_mean_reversion_sweep.fetch_forex_ohlcv", side_effect=_fake_forex_fetch
        ):
            rows = run_sweep()

        eur_rows = [r for r in rows if r["asset"] == "EUR/USD"]
        broken_rows = [r for r in rows if r["asset"] == "BROKEN/USD"]
        self.assertEqual(len(eur_rows), 1)
        self.assertIn("verdict", eur_rows[0])
        self.assertEqual(len(broken_rows), 1)
        self.assertIn("error", broken_rows[0])


class FindQualifyingTest(unittest.TestCase):
    def test_qualifies_positive_both_halves_adequate_sample(self) -> None:
        rows = [
            {"tier": "TIER 1 (forex)", "asset": "EUR/USD", "timeframe": "4h",
             "train": {"trades": 25, "expectancy_r": 0.1}, "test": {"trades": 21, "expectancy_r": 0.05}, "verdict": "PROMISING-WATCHLIST"},
            {"tier": "TIER 1 (forex)", "asset": "GBP/USD", "timeframe": "4h",
             "train": {"trades": 25, "expectancy_r": 0.1}, "test": {"trades": 21, "expectancy_r": -0.05}, "verdict": "DIED"},
        ]
        qualifying = find_qualifying(rows)
        self.assertEqual(len(qualifying), 1)
        self.assertEqual(qualifying[0]["asset"], "EUR/USD")


if __name__ == "__main__":
    unittest.main()
