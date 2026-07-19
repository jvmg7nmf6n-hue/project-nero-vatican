from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.bos_continuation import DEFAULT_PARAMETERS as BOS_PARAMETERS
from nero_core.strategies.bos_continuation import INDICATOR_COLUMNS_TO_CHECK as BOS_INDICATOR_COLUMNS
from nero_core.strategies.bos_continuation import add_indicators as bos_add_indicators
from nero_core.strategies.bos_continuation import run_backtest as bos_run_backtest
from tests.test_bos_continuation import _row
from tools.vol_clustering_harness import (
    compare_bos_continuation_multiplier_on_off,
    run_bos_continuation_with_multiplier,
)


def _bos_triggering_history() -> pd.DataFrame:
    """Same fixture as tests/test_bos_continuation.py's RunBacktestSmokeTest — a clean
    isolated swing high followed by a confirmed break — extended past the metals/
    stocks 100-candle vol-clustering lookback so a real, non-floored cluster score is
    computable at the entry candle."""
    rows: list[dict[str, object]] = []
    price = 100.0
    for i in range(230):
        price += 0.3
        rows.append(_row(i, high=price + 1, low=price - 1))
    last = price
    rows += [
        _row(230, high=last + 2, low=last - 1),
        _row(231, high=last + 3, low=last),
        _row(232, high=last + 15, low=last + 5, close=last + 8),
        _row(233, high=last + 12, low=last + 6),
        _row(234, high=last + 11, low=last + 5),
        _row(235, high=last + 10, low=last + 4),
        _row(236, high=last + 9, low=last + 3),
        _row(237, high=last + 8, low=last + 2, close=last + 20),
    ]
    for i in range(238, 260):
        level = last + 21 + (i - 238)
        rows.append(_row(i, high=level + 1, low=level - 1))
    return pd.DataFrame(rows)


class RunBosContinuationWithMultiplierEquivalenceTest(unittest.TestCase):
    def test_multiplier_off_matches_plain_bos_run_backtest(self) -> None:
        candles = _bos_triggering_history()

        enriched = bos_add_indicators(candles, BOS_PARAMETERS)
        evaluable = enriched.dropna(subset=BOS_INDICATOR_COLUMNS).reset_index(drop=True)
        baseline_trades, baseline_state = bos_run_backtest(evaluable, BOS_PARAMETERS)

        off_trades, off_state = run_bos_continuation_with_multiplier(candles, BOS_PARAMETERS, multiplier_on=False)

        self.assertEqual(len(baseline_trades), len(off_trades))
        self.assertEqual(baseline_state.equity, off_state.equity)
        for base_trade, off_trade in zip(baseline_trades, off_trades):
            self.assertEqual(base_trade.exit_price, off_trade.exit_price)
            self.assertEqual(base_trade.r_multiple, off_trade.r_multiple)

    def test_multiplier_on_produces_a_valid_run(self) -> None:
        candles = _bos_triggering_history()
        on_trades, on_state = run_bos_continuation_with_multiplier(candles, BOS_PARAMETERS, multiplier_on=True)
        self.assertIsInstance(on_trades, list)
        self.assertGreaterEqual(on_state.equity, 0.0)


class CompareBosContinuationMultiplierOnOffTest(unittest.TestCase):
    def test_returns_metrics_and_deltas(self) -> None:
        candles = _bos_triggering_history()
        comparison = compare_bos_continuation_multiplier_on_off(candles, BOS_PARAMETERS, asset="TEST")
        self.assertEqual(comparison.asset, "TEST")
        self.assertIsInstance(comparison.expectancy_r_delta, float)
        self.assertIsInstance(comparison.max_drawdown_delta, float)


if __name__ == "__main__":
    unittest.main()
