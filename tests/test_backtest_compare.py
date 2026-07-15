from __future__ import annotations

import math
import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS as V1_PARAMETERS, ExitEvent
from nero_core.strategies.mean_reversion_v2 import DEFAULT_V2_PARAMETERS
from tests.test_council_engine import _flat_then_pullback_history, _make_candle_row
from tools.backtest_compare import MIN_SAMPLE_SIZE, compute_metrics, run_backtest, _max_drawdown
from nero_core.strategies.mean_reversion import MeanReversionState


def _extended_history_with_room_to_exit() -> pd.DataFrame:
    """The Council Engine's 220-candle uptrend+pullback fixture, extended with 30 more
    flat candles past the dip so any trade opened at the pullback has enough bars to
    reach an exit (target, stop, or the 24h time-based exit) within the test window."""
    base = _flat_then_pullback_history()
    rows = base.to_dict("records")
    last_close_time = int(base.iloc[-1]["close_time"])
    last_close = float(base.iloc[-1]["close"])
    for i in range(1, 31):
        close_time = last_close_time + i * 3_600_000
        rows.append(_make_candle_row(close_time, last_close))
    return pd.DataFrame(rows)


def _win_loss_trades() -> list[ExitEvent]:
    def make(net_pnl: float, r_multiple: float, equity_after: float) -> ExitEvent:
        return ExitEvent(
            exit_reason="TARGET" if net_pnl > 0 else "SL",
            exit_price=100.0,
            gross_pnl=net_pnl,
            fees=1.0,
            net_pnl=net_pnl,
            r_multiple=r_multiple,
            holding_hours=5.0,
            equity_after=equity_after,
        )

    return [
        make(150.0, 1.5, 10150.0),
        make(-100.0, -1.0, 10050.0),
        make(200.0, 2.0, 10250.0),
        make(-80.0, -0.8, 10170.0),
    ]


class MaxDrawdownTest(unittest.TestCase):
    def test_no_drawdown_for_monotonically_rising_equity(self) -> None:
        self.assertEqual(_max_drawdown([100.0, 110.0, 120.0]), 0.0)

    def test_drawdown_measures_worst_peak_to_trough_drop(self) -> None:
        drawdown = _max_drawdown([100.0, 150.0, 90.0, 120.0])

        self.assertAlmostEqual(drawdown, (90.0 - 150.0) / 150.0)

    def test_empty_curve_has_zero_drawdown(self) -> None:
        self.assertEqual(_max_drawdown([]), 0.0)


class ComputeMetricsTest(unittest.TestCase):
    def test_zero_trades_reports_insufficient_sample(self) -> None:
        state = MeanReversionState(equity=10000.0)

        metrics = compute_metrics("BTC", "v1", 10000.0, state, [])

        self.assertEqual(metrics.sample_size, 0)
        self.assertTrue(metrics.insufficient_sample)
        self.assertEqual(metrics.win_rate, 0.0)

    def test_metrics_computed_correctly_from_trade_list(self) -> None:
        trades = _win_loss_trades()
        state = MeanReversionState(equity=trades[-1].equity_after)

        metrics = compute_metrics("BTC", "v1", 10000.0, state, trades)

        self.assertEqual(metrics.sample_size, 4)
        self.assertAlmostEqual(metrics.win_rate, 0.5)
        self.assertAlmostEqual(metrics.expectancy_r, (1.5 - 1.0 + 2.0 - 0.8) / 4)
        self.assertAlmostEqual(metrics.profit_factor, (150.0 + 200.0) / (100.0 + 80.0))
        self.assertAlmostEqual(metrics.net_pnl, 150.0 - 100.0 + 200.0 - 80.0)

    def test_flags_insufficient_sample_below_threshold(self) -> None:
        trades = _win_loss_trades()  # 4 trades, well under MIN_SAMPLE_SIZE
        state = MeanReversionState(equity=trades[-1].equity_after)

        metrics = compute_metrics("BTC", "v1", 10000.0, state, trades)

        self.assertLess(metrics.sample_size, MIN_SAMPLE_SIZE)
        self.assertTrue(metrics.insufficient_sample)
        self.assertTrue(any("below the" in note for note in metrics.notes))

    def test_all_wins_gives_zero_gross_loss_profit_factor_equals_gross_win(self) -> None:
        trades = [
            ExitEvent("TARGET", 100.0, 50.0, 1.0, 50.0, 1.0, 5.0, 10050.0),
            ExitEvent("TARGET", 100.0, 60.0, 1.0, 60.0, 1.2, 5.0, 10110.0),
        ]
        state = MeanReversionState(equity=10110.0)

        metrics = compute_metrics("BTC", "v1", 10000.0, state, trades)

        self.assertEqual(metrics.profit_factor, 110.0)


class RunBacktestOfflineTest(unittest.TestCase):
    """Exercises the actual candle-by-candle backtest loop against fully offline,
    hand-constructed data (no network) — this is the same kind of uptrend+pullback
    fixture already proven (in test_council_engine.py) to trigger a real Mean
    Reversion entry signal."""

    def test_v1_backtest_runs_and_closes_the_triggered_trade(self) -> None:
        history = _extended_history_with_room_to_exit()

        trades, state = run_backtest(history, V1_PARAMETERS)

        self.assertGreaterEqual(len(trades), 1)
        self.assertIsInstance(trades[0], ExitEvent)
        self.assertNotEqual(state.equity, V1_PARAMETERS.initial_equity)

    def test_v2_backtest_runs_offline_with_daily_context_and_no_network(self) -> None:
        history = _extended_history_with_room_to_exit()
        daily = pd.DataFrame(
            {
                "close_time": [int(history.iloc[-1]["close_time"]) - (90 - i) * 86_400_000 for i in range(90)],
                "close": [100.0 + i for i in range(90)],  # bullish daily trend
            }
        )

        trades, state = run_backtest(history, DEFAULT_V2_PARAMETERS, daily=daily, asset="BTC")

        # Must not raise, must return the right shapes regardless of whether the
        # volatility/higher-timeframe filters happened to allow this particular trade.
        self.assertIsInstance(trades, list)
        self.assertIsInstance(state, MeanReversionState)

    def test_v2_never_opens_more_trades_than_v1_when_regime_is_hostile(self) -> None:
        """A regime filter that only ever blocks (never adds new entries) can never
        produce MORE trades than the unfiltered baseline over the same candles."""
        history = _extended_history_with_room_to_exit()
        # Daily history with a clearly bearish trend: HIGHER_TIMEFRAME_TREND_CONTRADICTS
        # should block every v2 entry regardless of the volatility regime.
        bearish_daily = pd.DataFrame(
            {
                "close_time": [int(history.iloc[-1]["close_time"]) - (90 - i) * 86_400_000 for i in range(90)],
                "close": [200.0 - 1.2 * i for i in range(90)],
            }
        )

        v1_trades, _ = run_backtest(history, V1_PARAMETERS)
        v2_trades, _ = run_backtest(history, DEFAULT_V2_PARAMETERS, daily=bearish_daily, asset="BTC")

        self.assertLessEqual(len(v2_trades), len(v1_trades))


if __name__ == "__main__":
    unittest.main()
