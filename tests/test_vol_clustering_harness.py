from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from nero_core.quant.vol_regime import position_multiplier, volatility_cluster_score
from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS as MR_PARAMETERS
from nero_core.strategies.mean_reversion import OpenTrade
from tests.test_backtest_compare import _extended_history_with_room_to_exit
from tools.backtest_compare import VARIANT_SPECS, VariantSpec, run_backtest
from tools.vol_clustering_harness import (
    DEFAULT_CLUSTER_LOOKBACK,
    compare_multiplier_on_off,
    run_variant_with_multiplier,
)

LOOKBACK = DEFAULT_CLUSTER_LOOKBACK  # 100
OLDER_DIFF_COUNT = LOOKBACK - 20 - 1  # matches test_vol_regime's fixture construction


def _clustered_closes(older_magnitude: float, recent_magnitude: float, start: float = 100.0) -> list[float]:
    diffs = [((-1) ** i) * older_magnitude for i in range(OLDER_DIFF_COUNT)]
    diffs += [((-1) ** i) * recent_magnitude for i in range(20)]
    closes = [start]
    for diff in diffs:
        closes.append(closes[-1] * (1 + diff))
    assert len(closes) == LOOKBACK
    return closes


def _fixture_with_single_entry_at_last_candle(older_magnitude: float, recent_magnitude: float) -> pd.DataFrame:
    """Exactly LOOKBACK (100) candles built from the same deterministic alternating-diff
    pattern test_vol_regime.py uses, so the cluster score at the final (entry) candle is
    exactly computable by hand — see the ratio math in each test below."""
    closes = _clustered_closes(older_magnitude, recent_magnitude)
    close_time = 0
    rows = []
    for close in closes:
        rows.append(
            {
                "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
                "close_time": close_time,
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 10.0,
            }
        )
        close_time += 3_600_000
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class _CapturingFakeSpec:
    """Not a real VariantSpec (VariantSpec is frozen with fixed field names) — but
    duck-types every attribute run_variant_with_multiplier actually reads off `spec`.
    evaluate_entry_fn passes on exactly the LAST candle (index LOOKBACK-1); size_entry_fn
    records the risk_per_trade it was actually called with rather than doing any real
    sizing math, isolating "did the harness scale risk_per_trade correctly" from any
    particular strategy's own entry/sizing logic."""

    params: object
    captured_risk_per_trade: list

    key: str = "fake"
    label: str = "FAKE"
    needs_daily: bool = False

    def add_indicators_fn(self, candles, params):
        return candles

    def evaluate_entry_fn(self, candle, as_of_intraday, as_of_daily, state, params, asset):
        return SimpleNamespace(passed=(int(candle.name) == LOOKBACK - 1))

    def size_entry_fn(self, candle, state, params):
        self.captured_risk_per_trade.append(params.risk_per_trade)
        return OpenTrade(
            entry_price=float(candle["close"]),
            stop_loss=float(candle["close"]) * 0.9,
            target=float(candle["close"]) * 1.1,
            quantity=1.0,
            notional=100.0,
            risk_dollars=10.0,
            entry_fee=0.0,
            open_close_time=int(candle["close_time"]),
            entry_rsi=0.0,
            entry_ma20=0.0,
            entry_bb_lower=0.0,
            entry_ma200=0.0,
            entry_atr=1.0,
        )


class RunVariantWithMultiplierEquivalenceTest(unittest.TestCase):
    """multiplier_on=False must reproduce backtest_compare.run_backtest exactly — the
    refactor into a shared multiplier-aware loop must not change baseline behavior."""

    def test_multiplier_off_matches_plain_run_backtest(self) -> None:
        history = _extended_history_with_room_to_exit()
        spec = VARIANT_SPECS["mean_reversion_v1"]

        baseline_trades, baseline_state = run_backtest(history, spec)
        off_trades, off_state = run_variant_with_multiplier(history, spec, multiplier_on=False)

        self.assertEqual(len(baseline_trades), len(off_trades))
        self.assertEqual(baseline_state.equity, off_state.equity)
        for base_trade, off_trade in zip(baseline_trades, off_trades):
            self.assertEqual(base_trade.exit_price, off_trade.exit_price)
            self.assertEqual(base_trade.r_multiple, off_trade.r_multiple)


class MultiplierScalesRiskPerTradeTest(unittest.TestCase):
    def test_multiplier_off_uses_unscaled_risk_per_trade(self) -> None:
        history = _fixture_with_single_entry_at_last_candle(older_magnitude=0.001, recent_magnitude=0.01)
        captured: list = []
        spec = _CapturingFakeSpec(params=MR_PARAMETERS, captured_risk_per_trade=captured)

        run_variant_with_multiplier(history, spec, multiplier_on=False)

        self.assertEqual(captured, [MR_PARAMETERS.risk_per_trade])

    def test_multiplier_on_scales_risk_per_trade_by_the_computed_cluster_score(self) -> None:
        history = _fixture_with_single_entry_at_last_candle(older_magnitude=0.001, recent_magnitude=0.01)
        closes = history["close"]
        expected_score = volatility_cluster_score(closes, lookback=LOOKBACK)
        expected_multiplier = position_multiplier(expected_score)
        captured: list = []
        spec = _CapturingFakeSpec(params=MR_PARAMETERS, captured_risk_per_trade=captured)

        run_variant_with_multiplier(history, spec, multiplier_on=True, cluster_lookback=LOOKBACK)

        self.assertEqual(len(captured), 1)
        self.assertAlmostEqual(captured[0], MR_PARAMETERS.risk_per_trade * expected_multiplier)
        # Sanity: this fixture is a genuine 10x recent-vs-older spike, so the multiplier
        # must be meaningfully above baseline, not a no-op.
        self.assertGreater(expected_multiplier, 1.5)

    def test_stop_distance_is_unaffected_by_the_multiplier(self) -> None:
        # The fake size_entry_fn derives stop_loss purely from candle close (0.9x), never
        # from params.risk_per_trade — this test documents that invariant at the harness
        # level: multiplier_on never changes what gets passed to evaluate_exit's inputs
        # for the stop/target fields, only the scaled risk_per_trade used for sizing.
        history = _fixture_with_single_entry_at_last_candle(older_magnitude=0.001, recent_magnitude=0.01)
        captured_off: list = []
        captured_on: list = []
        spec_off = _CapturingFakeSpec(params=MR_PARAMETERS, captured_risk_per_trade=captured_off)
        spec_on = _CapturingFakeSpec(params=MR_PARAMETERS, captured_risk_per_trade=captured_on)

        _, state_off = run_variant_with_multiplier(history, spec_off, multiplier_on=False)
        _, state_on = run_variant_with_multiplier(history, spec_on, multiplier_on=True, cluster_lookback=LOOKBACK)

        self.assertEqual(state_off.open_trade.stop_loss, state_on.open_trade.stop_loss)
        self.assertEqual(state_off.open_trade.entry_price, state_on.open_trade.entry_price)
        self.assertNotEqual(captured_off[0], captured_on[0])


class CompareMultiplierOnOffTest(unittest.TestCase):
    def test_returns_metrics_and_deltas_for_both_runs(self) -> None:
        history = _extended_history_with_room_to_exit()
        spec = VARIANT_SPECS["mean_reversion_v1"]

        comparison = compare_multiplier_on_off(history, spec, asset="TEST")

        self.assertEqual(comparison.asset, "TEST")
        self.assertIsInstance(comparison.expectancy_r_delta, float)
        self.assertIsInstance(comparison.win_rate_delta, float)
        self.assertIsInstance(comparison.max_drawdown_delta, float)
        self.assertAlmostEqual(comparison.expectancy_r_delta, comparison.on.expectancy_r - comparison.off.expectancy_r)


if __name__ == "__main__":
    unittest.main()
