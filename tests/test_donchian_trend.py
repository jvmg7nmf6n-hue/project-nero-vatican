from __future__ import annotations

import unittest
from dataclasses import fields

import pandas as pd

from nero_core.strategies.donchian_trend import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    STRATEGY_VERSION,
    DonchianTrendParameters,
    OpenTrade,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    register_default_variant,
    run_donchian_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_FEE_SCALE_FACTOR
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def make_candle(close_time: int = 3600000, **overrides: object) -> pd.Series:
    data = {
        "date": pd.Timestamp("2026-07-10T01:00:00Z"),
        "open_time": close_time - 3600000,
        "close_time": close_time,
        "open": 109.0,
        "high": 111.0,
        "low": 108.0,
        "close": 112.0,
        "volume": 1000.0,
        "entry_channel_high": 110.0,
        "exit_channel_low": 105.0,
    }
    data.update(overrides)
    return pd.Series(data)


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


class ParametersTest(unittest.TestCase):
    def test_no_max_holding_hours_field(self) -> None:
        field_names = {f.name for f in fields(DonchianTrendParameters)}
        self.assertNotIn("max_holding_hours", field_names)

    def test_fees_are_gold_calibrated_by_default(self) -> None:
        self.assertAlmostEqual(DEFAULT_PARAMETERS.fee_bps, 10.0 * GOLD_FEE_SCALE_FACTOR)
        self.assertAlmostEqual(DEFAULT_PARAMETERS.slippage_bps, 2.0 * GOLD_FEE_SCALE_FACTOR)
        self.assertLess(DEFAULT_PARAMETERS.fee_bps, 10.0)  # scaled down from the crypto default


class AddIndicatorsTest(unittest.TestCase):
    def _uptrend_frame(self) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        close_time = 0
        price = 100.0
        for i in range(40):
            price += 0.5
            rows.append(_row(close_time, price, high=price + 1.0, low=price - 1.0))
            close_time += 3_600_000
        return pd.DataFrame(rows)

    def test_entry_channel_excludes_current_candle(self) -> None:
        frame = self._uptrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        row_index = 25
        expected = frame["high"].iloc[row_index - 20 : row_index].max()
        self.assertAlmostEqual(enriched.iloc[row_index]["entry_channel_high"], expected, places=6)
        # the row's own high (row_index's high, not in the row_index-20:row_index slice)
        # must never be included in its own channel value.
        self.assertNotEqual(enriched.iloc[row_index]["entry_channel_high"], frame.iloc[row_index]["high"])

    def test_exit_channel_excludes_current_candle(self) -> None:
        frame = self._uptrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        row_index = 25
        expected = frame["low"].iloc[row_index - 10 : row_index].min()
        self.assertAlmostEqual(enriched.iloc[row_index]["exit_channel_low"], expected, places=6)

    def test_first_row_channels_are_nan(self) -> None:
        frame = self._uptrend_frame()
        enriched = add_indicators(frame, DEFAULT_PARAMETERS)

        self.assertTrue(pd.isna(enriched.iloc[0]["entry_channel_high"]))
        self.assertTrue(pd.isna(enriched.iloc[0]["exit_channel_low"]))


class EvaluateEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_entry_passes_when_all_conditions_met(self) -> None:
        candle = make_candle(close=112.0, entry_channel_high=110.0, exit_channel_low=105.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.reasons, ())
        self.assertAlmostEqual(evaluation.risk_distance, 112.0 - 105.0, places=6)

    def test_blocked_when_close_not_above_entry_channel(self) -> None:
        candle = make_candle(close=109.0, entry_channel_high=110.0)

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_ENTRY_CHANNEL", evaluation.reasons)

    def test_blocked_when_entry_channel_is_nan(self) -> None:
        candle = make_candle(entry_channel_high=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("CLOSE_NOT_ABOVE_ENTRY_CHANNEL", evaluation.reasons)

    def test_blocked_when_risk_distance_is_zero_or_negative(self) -> None:
        candle = make_candle(close=112.0, exit_channel_low=112.0)  # distance == 0

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RISK_DISTANCE_NOT_POSITIVE", evaluation.reasons)

    def test_blocked_when_exit_channel_is_nan(self) -> None:
        candle = make_candle(exit_channel_low=float("nan"))

        evaluation = evaluate_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertFalse(evaluation.passed)
        self.assertIn("RISK_DISTANCE_NOT_POSITIVE", evaluation.reasons)

    def test_open_trade_exists_blocks_entry(self) -> None:
        self.state.open_trade = OpenTrade(
            entry_price=100.0, quantity=1.0, notional=100.0, risk_dollars=2.0,
            entry_fee=0.1, open_close_time=0, entry_channel_high=99.0, entry_exit_low=95.0,
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


class SizeEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_risk_dollars_matches_fixed_fractional_target(self) -> None:
        candle = make_candle(close=112.0, exit_channel_low=105.0)

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNotNone(trade)
        self.assertAlmostEqual(trade.risk_dollars, self.state.equity * DEFAULT_PARAMETERS.risk_per_trade, places=4)

    def test_returns_none_when_risk_distance_not_positive(self) -> None:
        candle = make_candle(close=112.0, exit_channel_low=113.0)  # exit channel ABOVE close -> negative distance

        trade = size_entry(candle, self.state, DEFAULT_PARAMETERS)

        self.assertIsNone(trade)

    def test_notional_capped_by_max_notional_pct(self) -> None:
        params = DonchianTrendParameters(max_notional_pct=0.5, risk_per_trade=0.9)
        candle = make_candle(close=112.0, exit_channel_low=111.9)  # tiny risk distance -> huge uncapped quantity

        trade = size_entry(candle, self.state, params)

        self.assertIsNotNone(trade)
        self.assertLessEqual(trade.notional, self.state.equity * 0.5 + 1e-6)


class EvaluateExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MeanReversionState(equity=10000.0)

    def test_no_exit_while_close_stays_above_trailing_channel(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, close=113.0, exit_channel_low=106.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNone(exit_event)
        self.assertIsNotNone(self.state.open_trade)

    def test_exits_when_close_drops_below_current_trailing_channel(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, close=104.0, exit_channel_low=105.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "TRAIL_EXIT")

    def test_r_multiple_uses_initial_risk_distance_not_updated_trailing_level(self) -> None:
        # Entry risk distance = 112 - 105 = 7. Even though the trailing channel has since
        # risen to 110 by exit time, r_multiple must still be computed against the
        # ORIGINAL 7-point distance, per the hypothesis's explicit sizing rule.
        entry = size_entry(make_candle(close_time=3600000, close=112.0, exit_channel_low=105.0), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry
        original_risk_dollars = entry.risk_dollars

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, close=109.0, exit_channel_low=110.0),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNotNone(exit_event)
        expected_r = exit_event.net_pnl / original_risk_dollars
        self.assertAlmostEqual(exit_event.r_multiple, expected_r, places=6)

    def test_returns_none_when_no_open_trade(self) -> None:
        self.assertIsNone(evaluate_exit(make_candle(), self.state, DEFAULT_PARAMETERS))

    def test_returns_none_when_exit_channel_is_nan(self) -> None:
        entry = size_entry(make_candle(close_time=3600000), self.state, DEFAULT_PARAMETERS)
        self.state.open_trade = entry

        exit_event = evaluate_exit(
            make_candle(close_time=7200000, exit_channel_low=float("nan")),
            self.state,
            DEFAULT_PARAMETERS,
        )

        self.assertIsNone(exit_event)


class RunDonchianBacktestTest(unittest.TestCase):
    def test_produces_internally_consistent_equity_accounting(self) -> None:
        rows: list[dict[str, object]] = []
        close_time = 0
        price = 100.0
        for i in range(60):
            price += 0.5 if i % 3 != 0 else -0.2
            rows.append(_row(close_time, price, high=price + 1.0, low=price - 1.0))
            close_time += 3_600_000
        frame = pd.DataFrame(rows)

        trades, state = run_donchian_backtest(frame, DEFAULT_PARAMETERS)

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
        self.assertEqual(variant.version, "donchian-trend-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
