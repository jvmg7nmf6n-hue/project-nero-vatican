from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.forex_data import ForexDataResult, ForexDataUnavailableError
from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS
from tests.test_council_engine import _make_candle_row
from tools.rmr_variant_research_stage1 import (
    FOREX_FEE_BPS,
    FOREX_SLIPPAGE_BPS,
    calibrated_params_for,
    run_stage1,
)


class CalibratedParamsForTest(unittest.TestCase):
    def test_forex_gets_flat_fee(self) -> None:
        params = calibrated_params_for("EUR/USD", DEFAULT_PARAMETERS)
        self.assertEqual(params.fee_bps, FOREX_FEE_BPS)
        self.assertEqual(params.slippage_bps, FOREX_SLIPPAGE_BPS)

    def test_crypto_gets_unscaled_default(self) -> None:
        params = calibrated_params_for("ETH", DEFAULT_PARAMETERS)
        self.assertEqual(params.fee_bps, DEFAULT_PARAMETERS.fee_bps)
        self.assertEqual(params.slippage_bps, DEFAULT_PARAMETERS.slippage_bps)


def _history(n: int = 300, hours_per_candle: int = 4) -> pd.DataFrame:
    rows = []
    close_time = 0
    for i in range(n):
        close = 100.0 + (3.0 if i % 4 < 2 else -3.0)
        rows.append(_make_candle_row(close_time, close))
        close_time += hours_per_candle * 3_600_000
    return pd.DataFrame(rows)


class RunStage1SmokeTest(unittest.TestCase):
    def test_all_three_groups_run_without_error(self) -> None:
        history = _history()

        def _fake_forex(pair, timeframe):
            return ForexDataResult(prices=history, source="test-fixture", pair=pair, timeframe=timeframe)

        def _fake_timeframe(client, asset, timeframe):
            return history, "test-fixture"

        with patch("tools.rmr_variant_research_stage1.fetch_forex_ohlcv", side_effect=_fake_forex), patch(
            "tools.rmr_variant_research_stage1.fetch_timeframe_candles", side_effect=_fake_timeframe
        ):
            results = run_stage1()

        self.assertIn("EUR/USD_4h", results)
        self.assertIn("ETH_4h", results)
        self.assertIn("BTC_1d", results)
        self.assertEqual(len(results["EUR/USD_4h"]), 2)
        self.assertEqual(len(results["ETH_4h"]), 2)
        self.assertEqual(len(results["BTC_1d"]), 3)
        for group in results.values():
            for cfg in group:
                self.assertIn("verdict", cfg)

    def test_forex_failure_reports_skipped_not_crash(self) -> None:
        history = _history()

        def _fake_timeframe(client, asset, timeframe):
            return history, "test-fixture"

        with patch("tools.rmr_variant_research_stage1.fetch_forex_ohlcv", side_effect=ForexDataUnavailableError("no data")), patch(
            "tools.rmr_variant_research_stage1.fetch_timeframe_candles", side_effect=_fake_timeframe
        ):
            results = run_stage1()

        self.assertIn("error", results["EUR/USD_4h"][0])


if __name__ == "__main__":
    unittest.main()
