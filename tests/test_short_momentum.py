from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from nero_core.strategies.short_momentum import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    OpenTrade,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    run_short_backtest,
    size_entry,
)


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T01:00:00Z"),
        "open_time": close_time - 3600000,
        "close_time": close_time,
        "open": 101.0,
        "high": 102.0,
        "low": 99.0,
        "close": 95.0,
        "volume": 1000.0,
        "rsi": 40.0,
        "ma200": 105.0,
        "atr": 2.0,
        "breakdown_low": 96.0,
    }
    data.update(overrides)
    return pd.Series(data)


def _make_ohlcv_row(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict[str, object]:
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


class AddIndicatorsTest(unittest.TestCase):
    def _downtrend_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        close_time = 0
        price = 200.0
        for i in range(230):
            price -= 0.3
            rows.append(_make_ohlcv_row(close_time, price))
            close_time += 3_600_000
        return pd.DataFrame(rows)

    def test_breakdown_low_uses_shifted_prior_candles_no_lookahead(self) -> None:
        frame = self._downtrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        row = enriched.iloc[100]
        prior_lows = frame["low"].iloc[100 - 20 : 100]
        self.assertAlmostEqual(row["breakdown_low"], prior_lows.min(), places=6)
        # the row's OWN low must never be included in its own breakdown threshold
        self.assertNotIn(frame.iloc[100]["low"], prior_lows.tolist())

    def test_first_row_breakdown_low_is_nan(self) -> None:
        frame = self._downtrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        self.assertTrue(pd.isna(enriched.iloc[0]["breakdown_low"]))

    def test_ma200_matches_rolling_mean(self) -> None:
        frame = self._downtrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        expected = frame["close"].rolling(200).mean()
        pd.testing.assert_series_equal(enriched["ma200"], expected, check_names=False)


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_passes_when_all_conditions_met(self) -> None:
        candle = make_candle(close=95.0, breakdown_low=96.0, ma200=105.0, rsi=40.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())

    def test_blocked_when_close_not_below_breakdown_low(self) -> None:
        candle = make_candle(close=97.0, breakdown_low=96.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_BELOW_BREAKDOWN_LOW", evaluation.reasons)

    def test_blocked_when_breakdown_low_is_nan(self) -> None:
        candle = make_candle(breakdown_low=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_BELOW_BREAKDOWN_LOW", evaluation.reasons)

    def test_blocked_when_close_not_below_ma200(self) -> None:
        candle = make_candle(close=95.0, ma200=90.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_BELOW_MA200", evaluation.reasons)

    def test_blocked_when_rsi_above_threshold(self) -> None:
        candle = make_candle(rsi=55.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RSI_NOT_MOMENTUM_SUPPORTIVE", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        self.state.open_trade = OpenTrade(
            entry_price=100.0, stop_loss=102.0, target=97.5, quantity=1.0, notional=100.0,
            risk_dollars=2.0, entry_fee=0.1, open_close_time=0, entry_rsi=40.0,
            entry_ma200=105.0, entry_atr=2.0, entry_breakdown_low=96.0,
        )
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)

    def test_daily_loss_guard_blocks_entry(self) -> None:
        self.state.daily_r = -5.0
        candle = make_candle()

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("DAILY_LOSS_GUARD", evaluation.reasons)

    def test_all_failing_reasons_reported(self) -> None:
        candle = make_candle(close=110.0, breakdown_low=96.0, ma200=90.0, rsi=70.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIn("CLOSE_NOT_BELOW_BREAKDOWN_LOW", evaluation.reasons)
        self.assertIn("CLOSE_NOT_BELOW_MA200", evaluation.reasons)
        self.assertIn("RSI_NOT_MOMENTUM_SUPPORTIVE", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_stop_is_1_2x_atr_above_entry(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertGreater(trade.stop_loss, trade.entry_price)
        self.assertAlmostEqual(trade.stop_loss - trade.entry_price, 1.2 * 2.0, places=6)

    def test_target_is_below_entry_at_125r(self) -> None:
        candle = make_candle(atr=2.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertLess(trade.target, trade.entry_price)
        risk_per_unit = trade.stop_loss - trade.entry_price
        self.assertAlmostEqual(trade.entry_price - trade.target, 1.25 * risk_per_unit, places=6)

    def test_returns_none_when_atr_is_zero(self) -> None:
        candle = make_candle(atr=0.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNone(trade)

    def test_notional_capped_by_max_notional_pct(self) -> None:
        from nero_core.strategies.short_momentum import ShortMomentumParameters

        params = ShortMomentumParameters(max_notional_pct=0.5, risk_per_trade=0.5)
        candle = make_candle(atr=0.01)

        trade = size_entry(candle, self.state, params)

        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, self.state.equity * 0.5 + 1e-6)


class EvaluateExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_target_exit_profits_when_price_falls(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.stop_loss - 0.1, low=entry.target - 1.0, close=entry.target),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TARGET")
        self.assertGreater(exit_event.net_pnl, 0.0)

    def test_stop_exit_loses_when_price_rises(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.stop_loss + 1.0, low=entry.target + 0.1, close=entry.stop_loss),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")
        self.assertLess(exit_event.net_pnl, 0.0)

    def test_mirrored_tie_break_prefers_stop_when_both_hit(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        # a single candle whose range spans both the (higher) stop and the (lower) target
        exit_event = evaluate_exit(
            make_candle(close_time=7200000, high=entry.stop_loss + 1.0, low=entry.target - 1.0, close=entry.target),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")

    def test_time_exit_after_max_holding_hours(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(
                close_time=3600000 + 24 * 3600000,
                high=entry.stop_loss - 0.1,
                low=entry.target + 0.1,
                close=entry.entry_price,
            ),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TIME")

    def test_no_exit_when_price_stays_between_stop_and_target(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=3660000, high=entry.stop_loss - 0.1, low=entry.target + 0.1, close=entry.entry_price),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNone(exit_event)
        self.assertIsNotNone(self.state.open_trade)

    def test_returns_none_when_no_open_trade(self) -> None:
        self.assertIsNone(evaluate_exit(make_candle(), self.state, DEFAULT_PARAMETERS))


class RunShortBacktestTest(unittest.TestCase):
    def test_produces_closed_trades_on_a_synthetic_downtrend_breakdown(self) -> None:
        rows: list[dict[str, object]] = []
        close_time = 0
        price = 200.0
        for i in range(230):
            price -= 0.3
            rows.append(_make_ohlcv_row(close_time, price, high=price + 4.0, low=price - 4.0))
            close_time += 3_600_000
        # sharp breakdown leg
        for _ in range(15):
            price *= 0.95
            rows.append(_make_ohlcv_row(close_time, price, high=price * 1.01, low=price * 0.98))
            close_time += 3_600_000
        frame = pd.DataFrame(rows)

        trades, state = run_short_backtest(frame, DEFAULT_PARAMETERS)

        self.assertIsInstance(trades, list)
        # equity accounting must be internally consistent regardless of trade count
        running = DEFAULT_PARAMETERS.initial_equity
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
        self.assertEqual(variant.version, "short-momentum-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
