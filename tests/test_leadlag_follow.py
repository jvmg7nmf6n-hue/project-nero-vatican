from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.leadlag_follow import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    LeadLagFollowParameters,
    OpenTrade,
    add_indicators,
    align_leadlag_candles,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    run_leadlag_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict[str, object]:
    return {
        "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "open_time": close_time - 3_600_000,
        "close_time": close_time,
        "open": close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "volume": 100.0,
    }


class AlignLeadlagCandlesTest(unittest.TestCase):
    def test_inner_joins_and_prefixes_full_ohlcv(self) -> None:
        x = pd.DataFrame([_row(0, 100.0), _row(3_600_000, 101.0)])
        y = pd.DataFrame([_row(3_600_000, 50.0), _row(7_200_000, 51.0)])

        aligned = align_leadlag_candles(x, y, "BTC", "ETH")

        self.assertEqual(list(aligned["close_time"]), [3_600_000])
        self.assertIn("BTC_close", aligned.columns)
        self.assertIn("ETH_high", aligned.columns)
        self.assertEqual(aligned.iloc[0]["BTC_close"], 101.0)
        self.assertEqual(aligned.iloc[0]["ETH_close"], 50.0)


class AddIndicatorsTest(unittest.TestCase):
    def _frame(self, n: int = 60) -> pd.DataFrame:
        rows_x, rows_y = [], []
        close_time = 0
        for i in range(n):
            btc_close = 100.0 + i * 0.1
            alt_close = 50.0 + i * 0.05
            rows_x.append(_row(close_time, btc_close, high=btc_close + 0.3, low=btc_close - 0.3))
            rows_y.append(_row(close_time, alt_close, high=alt_close + 0.2, low=alt_close - 0.2))
            close_time += 3_600_000
        return align_leadlag_candles(pd.DataFrame(rows_x), pd.DataFrame(rows_y), "BTC", "ALT")

    def test_btc_lagged_up_move_is_shifted_no_lookahead(self) -> None:
        aligned = self._frame()
        params = LeadLagFollowParameters(lag=3, atr_period=14)

        enriched = add_indicators(aligned, params, "BTC", "ALT")

        row_index = 40
        # row_index's lagged flag must equal the RAW (unshifted) flag computed at
        # row_index - lag, not at row_index itself.
        x_ohlc = pd.DataFrame({"high": aligned["BTC_high"], "low": aligned["BTC_low"], "close": aligned["BTC_close"]})
        from nero_core.strategies.mean_reversion import atr as atr_fn

        raw_atr = atr_fn(x_ohlc, params.atr_period)
        raw_move = x_ohlc["close"].diff()
        raw_flag_at_lagged_row = bool((raw_move > raw_atr).iloc[row_index - params.lag])
        self.assertEqual(bool(enriched.iloc[row_index]["btc_lagged_up_move"]), raw_flag_at_lagged_row)

    def test_close_high_low_are_aliased_to_the_alt(self) -> None:
        aligned = self._frame()
        enriched = add_indicators(aligned, DEFAULT_PARAMETERS, "BTC", "ALT")

        pd.testing.assert_series_equal(enriched["close"], enriched["ALT_close"], check_names=False)
        pd.testing.assert_series_equal(enriched["high"], enriched["ALT_high"], check_names=False)


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def _candle(self, **overrides: object) -> pd.Series:
        data = {
            "date": pd.Timestamp("2026-07-10T01:00:00Z"),
            "close_time": 3600000,
            "close": 50.0,
            "atr": 1.0,
            "btc_lagged_up_move": True,
        }
        data.update(overrides)
        return pd.Series(data)

    def test_entry_passes_when_btc_lagged_up_move_detected(self) -> None:
        candle = self._candle(btc_lagged_up_move=True)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)

    def test_blocked_when_no_lagged_up_move(self) -> None:
        candle = self._candle(btc_lagged_up_move=False)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("BTC_LAGGED_UP_MOVE_NOT_DETECTED", evaluation.reasons)

    def test_blocked_when_flag_is_nan(self) -> None:
        candle = self._candle(btc_lagged_up_move=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("BTC_LAGGED_UP_MOVE_NOT_DETECTED", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        self.state.open_trade = OpenTrade(
            entry_price=50.0, stop_loss=48.5, target=52.0, quantity=1.0, notional=50.0,
            risk_dollars=1.5, entry_fee=0.1, open_close_time=0, entry_atr=1.0, entry_btc_move=2.0,
        )
        candle = self._candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_daily_loss_guard_blocks_entry(self) -> None:
        self.state.daily_r = -5.0
        candle = self._candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)


class SizeEntryAndExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def _candle(self, **overrides: object) -> pd.Series:
        data = {
            "date": pd.Timestamp("2026-07-10T01:00:00Z"),
            "close_time": 3600000,
            "open": 50.0, "high": 50.5, "low": 49.5, "close": 50.0,
            "atr": 1.0,
            "btc_move": 1.5,
        }
        data.update(overrides)
        return pd.Series(data)

    def test_stop_and_target_use_1_5x_and_2_0x_atr(self) -> None:
        candle = self._candle(atr=1.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.entry_price - trade.stop_loss, 1.5, places=4)
        self.assertAlmostEqual(trade.target - trade.entry_price, 2.0, places=4)

    def test_returns_none_when_atr_is_zero(self) -> None:
        candle = self._candle(atr=0.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNone(trade)

    def test_evaluate_exit_reuses_shared_long_only_exit(self) -> None:
        entry = size_entry(self._candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_candle = self._candle(close_time=7200000, high=entry.target + 1.0, low=entry.stop_loss + 0.1, close=entry.target)
        exit_event = evaluate_exit(exit_candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TARGET")


class RunLeadlagBacktestTest(unittest.TestCase):
    def test_produces_internally_consistent_equity_accounting(self) -> None:
        rows_x, rows_y = [], []
        close_time = 0
        btc_price, alt_price = 100.0, 50.0
        for i in range(250):
            btc_price += 3.0 if i % 4 == 0 else -0.2
            alt_price *= 1.01 if i % 4 == 1 else 0.999
            rows_x.append(_row(close_time, btc_price, high=btc_price + 0.5, low=btc_price - 0.5))
            rows_y.append(_row(close_time, alt_price, high=alt_price * 1.02, low=alt_price * 0.97))
            close_time += 3_600_000
        aligned = align_leadlag_candles(pd.DataFrame(rows_x), pd.DataFrame(rows_y), "BTC", "ALT")
        params = LeadLagFollowParameters(lag=1)

        trades, state = run_leadlag_backtest(aligned, params, "BTC", "ALT")

        running = params.initial_equity
        for trade in trades:
            running += trade.net_pnl
            self.assertAlmostEqual(running, trade.equity_after, places=6)
        self.assertAlmostEqual(state.equity, running, places=6)


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "leadlag-follow-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
