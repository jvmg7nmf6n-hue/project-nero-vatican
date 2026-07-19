from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from nero_core.data_sources.stock_data import StockDataResult, StockDataUnavailableError
from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_DEFAULT_PARAMETERS
from nero_core.strategies.macro_risk_on import DEFAULT_PARAMETERS as MACRO_PARAMETERS
from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS as MR_PARAMETERS
from tests.test_council_engine import _flat_then_pullback_history, _make_candle_row
from tools.backtest_stocks_task_a2_sweep import (
    STOCK_FEE_BPS,
    STOCK_SLIPPAGE_BPS,
    find_qualifying,
    run_single_asset_configs,
    stock_calibrated_params,
)


class StockCalibratedParamsTest(unittest.TestCase):
    def test_flat_fee_and_slippage_applied(self) -> None:
        params = stock_calibrated_params(MR_PARAMETERS, "1day")
        self.assertEqual(params.fee_bps, STOCK_FEE_BPS)
        self.assertEqual(params.slippage_bps, STOCK_SLIPPAGE_BPS)

    def test_max_holding_hours_preserves_24_candle_cap_per_timeframe(self) -> None:
        self.assertEqual(stock_calibrated_params(MR_PARAMETERS, "1h").max_holding_hours, 24)
        self.assertEqual(stock_calibrated_params(MR_PARAMETERS, "4h").max_holding_hours, 96)
        self.assertEqual(stock_calibrated_params(MR_PARAMETERS, "1day").max_holding_hours, 576)
        self.assertEqual(stock_calibrated_params(MR_PARAMETERS, "1week").max_holding_hours, 4032)

    def test_strategies_without_max_holding_hours_are_left_alone(self) -> None:
        # DONCHIAN_TREND and MACRO_RISK_ON deliberately have no such field.
        params = stock_calibrated_params(DONCHIAN_DEFAULT_PARAMETERS, "1week")
        self.assertFalse(hasattr(params, "max_holding_hours"))
        self.assertEqual(params.fee_bps, STOCK_FEE_BPS)

        macro_params = stock_calibrated_params(MACRO_PARAMETERS, "1day")
        self.assertFalse(hasattr(macro_params, "max_holding_hours"))
        self.assertEqual(macro_params.fee_bps, STOCK_FEE_BPS)

    def test_does_not_mutate_base_params(self) -> None:
        original_fee = MR_PARAMETERS.fee_bps
        stock_calibrated_params(MR_PARAMETERS, "1day")
        self.assertEqual(MR_PARAMETERS.fee_bps, original_fee)


class FindQualifyingTest(unittest.TestCase):
    def test_qualifies_positive_both_halves_adequate_sample(self) -> None:
        rows = [
            {"asset": "AAPL", "timeframe": "1day", "strategy": "X", "train": {"trades": 25, "expectancy_r": 0.1},
             "test": {"trades": 21, "expectancy_r": 0.05}, "verdict": "PROMISING-WATCHLIST"},
            {"asset": "MSFT", "timeframe": "1day", "strategy": "X", "train": {"trades": 25, "expectancy_r": 0.1},
             "test": {"trades": 21, "expectancy_r": -0.05}, "verdict": "DIED"},
            {"asset": "TSLA", "timeframe": "1day", "strategy": "X", "error": "no data"},
        ]
        qualifying = find_qualifying(rows)
        self.assertEqual(len(qualifying), 1)
        self.assertEqual(qualifying[0]["asset"], "AAPL")


def _stock_history(n: int = 300, hours_per_candle: int = 24) -> pd.DataFrame:
    base = _flat_then_pullback_history()  # 220 candles, hourly spacing baked in
    rows = base.to_dict("records")
    last_close_time = int(base.iloc[-1]["close_time"])
    last_close = float(base.iloc[-1]["close"])
    for i in range(1, n - len(rows) + 1):
        close_time = last_close_time + i * hours_per_candle * 3_600_000
        rows.append(_make_candle_row(close_time, last_close))
    return pd.DataFrame(rows)


class SmokeRunSingleAssetConfigsTest(unittest.TestCase):
    """End-to-end smoke test over a tiny 2-symbol, 1-timeframe subset (mocked
    fetch_stock_ohlcv, no network) — proves the wiring (roster -> params -> spec ->
    split -> half-stats -> verdict) works before any real, long-running live sweep."""

    def test_runs_without_error_over_a_small_mocked_universe(self) -> None:
        history = _stock_history()

        def _fake_fetch(symbol, timeframe):
            if symbol == "BROKEN":
                raise StockDataUnavailableError("no data")
            return StockDataResult(prices=history, source="test-fixture", symbol=symbol, timeframe=timeframe)

        with patch("tools.backtest_stocks_task_a2_sweep.STOCKS", ["AAPL", "BROKEN"]), patch(
            "tools.backtest_stocks_task_a2_sweep.SINGLE_ASSET_ROSTER",
            [{"label": "MEAN_REVERSION v1", "variant_key": "mean_reversion_v1", "timeframes": ["1day"],
              "regime_mask_fn": lambda evaluable: evaluable["close"] > evaluable["ma200"]}],
        ), patch("tools.backtest_stocks_task_a2_sweep.fetch_stock_ohlcv", side_effect=_fake_fetch):
            rows = run_single_asset_configs()

        aapl_rows = [r for r in rows if r["asset"] == "AAPL"]
        broken_rows = [r for r in rows if r["asset"] == "BROKEN"]
        # MEAN_REVERSION(1day) + DONCHIAN(1week) + FVG(1h,4h,1day) + BOS(4h,1day,1week)
        self.assertEqual(len(aapl_rows), 8)
        self.assertTrue(all("verdict" in r for r in aapl_rows))
        self.assertEqual(len(broken_rows), 8)
        self.assertTrue(all("error" in r for r in broken_rows))


if __name__ == "__main__":
    unittest.main()
