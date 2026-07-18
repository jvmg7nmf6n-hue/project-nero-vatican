from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.funding_extreme import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    FundingExtremeParameters,
    add_indicators,
    evaluate_entry,
    evaluate_exit,
    funding_data_available_mask,
    register_default_variant,
    run_backtest,
    size_entry,
)
from nero_core.strategies.mean_reversion import MeanReversionState
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry
from tests.test_council_engine import _make_candle_row

EIGHT_HOURS_MS = 8 * 3_600_000


def _settlements(rates: list[float], start_ms: int = 0) -> pd.DataFrame:
    """One synthetic settlement every 8h, at exactly 00/08/16 UTC starting from an
    8h-aligned epoch (epoch 0 = 1970-01-01 00:00 UTC, itself a settlement hour)."""
    times = [start_ms + i * EIGHT_HOURS_MS for i in range(len(rates))]
    return pd.DataFrame(
        {
            "settlement_time": times,
            "settlement_date": pd.to_datetime(times, unit="ms", utc=True),
            "funding_rate": rates,
        }
    )


def _candles_8h(n: int, start_ms: int = 0, price: float = 100.0) -> pd.DataFrame:
    rows = []
    close_time = start_ms
    for i in range(n):
        rows.append(_make_candle_row(close_time, price + 0.01 * i))
        close_time += EIGHT_HOURS_MS
    return pd.DataFrame(rows)


class AddIndicators8hTest(unittest.TestCase):
    def test_exact_settlement_time_is_attached_to_the_matching_candle(self) -> None:
        candles = _candles_8h(5)
        settlements = _settlements([0.0001, 0.0002, -0.0003, 0.0001, 0.0002])

        enriched = add_indicators(candles, settlements, "8h")

        # funding_rate (pre-lag) at row i should equal settlements[i]'s own rate.
        self.assertEqual(list(enriched["funding_rate"]), [0.0001, 0.0002, -0.0003, 0.0001, 0.0002])

    def test_real_world_binance_close_time_offset_still_matches(self) -> None:
        """Regression guard: real Binance kline close_time is period_end - 1ms (not
        exactly on the settlement boundary), while fundingTime carries its own few-ms
        jitter — an exact-equality join between the two matches ZERO rows, silently
        producing zero trades across every 8h config regardless of real signal. Caught
        by running the real sweep against live data before committing (see
        docs/funding_extreme_report.md). This fixture mirrors the real -1ms offset."""
        candles = _candles_8h(5)
        candles["close_time"] = candles["close_time"] - 1  # Binance's real convention
        candles["date"] = pd.to_datetime(candles["close_time"], unit="ms", utc=True)
        settlements = _settlements([0.0001, 0.0002, -0.0003, 0.0001, 0.0002])

        enriched = add_indicators(candles, settlements, "8h")

        self.assertEqual(list(enriched["funding_rate"]), [0.0001, 0.0002, -0.0003, 0.0001, 0.0002])

    def test_entry_funding_rate_is_shifted_forward_by_one_row(self) -> None:
        candles = _candles_8h(4)
        settlements = _settlements([0.0001, 0.0002, -0.0003, 0.0004])

        enriched = add_indicators(candles, settlements, "8h")

        self.assertTrue(pd.isna(enriched["entry_funding_rate"].iloc[0]))
        self.assertEqual(list(enriched["entry_funding_rate"].iloc[1:]), [0.0001, 0.0002, -0.0003])

    def test_trailing_percentile_excludes_the_current_settlement(self) -> None:
        # 10 settlements at a constant 0.01, then one outlier at -1.0. The outlier's OWN
        # trailing median must be computed from the 10 prior 0.01 values only (median
        # 0.01), NOT influenced by including itself.
        rates = [0.01] * 10 + [-1.0]
        candles = _candles_8h(11)
        settlements = _settlements(rates)

        enriched = add_indicators(candles, settlements, "8h", FundingExtremeParameters(trailing_window_days=90))

        outlier_row_median = enriched["funding_median"].iloc[10]
        self.assertAlmostEqual(outlier_row_median, 0.01, places=9)

    def test_unsupported_timeframe_raises(self) -> None:
        candles = _candles_8h(3)
        settlements = _settlements([0.0001, 0.0002, 0.0003])
        with self.assertRaises(ValueError):
            add_indicators(candles, settlements, "4h")


class AddIndicators24hTest(unittest.TestCase):
    def test_uses_only_the_1600_utc_settlement_for_each_day(self) -> None:
        # Day 1: settlements at 00:00 (0.001), 08:00 (0.002), 16:00 (0.003) -> day 1's
        # funding value must be 0.003, not the other two.
        day_ms = 24 * 3_600_000
        settlements = _settlements([0.001, 0.002, 0.003, 0.004, 0.005, 0.006])  # 2 full days, 3 settlements each
        daily_candles = pd.DataFrame(
            [_make_candle_row(day_ms - 1, 100.0), _make_candle_row(2 * day_ms - 1, 101.0)]
        )

        enriched = add_indicators(daily_candles, settlements, "24h")

        self.assertEqual(list(enriched["funding_rate"]), [0.003, 0.006])


class TrailingWindowRegimeMaskTest(unittest.TestCase):
    def test_mask_is_false_until_funding_data_is_available(self) -> None:
        candles = _candles_8h(3)
        settlements = _settlements([0.0001, 0.0002, 0.0003])

        enriched = add_indicators(candles, settlements, "8h")
        mask = funding_data_available_mask(enriched)

        # Row 0: no settlement data has been observed at all yet (nothing to shift in).
        # Row 1: entry_funding_rate is available (row 0's own rate, t+1-shifted), but
        # entry_funding_p10 needs row 0's trailing p10 to itself be defined first — and
        # row 0 has zero PRIOR settlements (closed="left" excludes its own), so its own
        # p10 is NaN, making row 1's (shifted) p10 NaN too.
        # Row 2: row 1's trailing p10 has exactly one prior point (row 0) to compute
        # from, so it's defined, and row 2's shifted value is therefore available.
        self.assertEqual(list(mask), [False, False, True])


class EvaluateEntryTest(unittest.TestCase):
    def _candle_with_funding(self, rate: float | None, p10: float | None) -> pd.Series:
        row = _make_candle_row(0, 100.0)
        row["entry_funding_rate"] = rate
        row["entry_funding_p10"] = p10
        return pd.Series(row)

    def test_passes_when_negative_and_at_or_below_p10(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle_with_funding(rate=-0.02, p10=-0.015)

        evaluation = evaluate_entry(candle, state)

        self.assertTrue(evaluation.passed)

    def test_rejects_when_funding_is_positive(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle_with_funding(rate=0.001, p10=-0.015)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("FUNDING_NOT_NEGATIVE", evaluation.reasons)

    def test_rejects_when_negative_but_above_p10(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle_with_funding(rate=-0.005, p10=-0.015)

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("FUNDING_NOT_AT_OR_BELOW_TRAILING_P10", evaluation.reasons)

    def test_rejects_when_funding_data_not_yet_available(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        candle = self._candle_with_funding(rate=float("nan"), p10=float("nan"))

        evaluation = evaluate_entry(candle, state)

        self.assertFalse(evaluation.passed)
        self.assertIn("FUNDING_DATA_NOT_YET_AVAILABLE", evaluation.reasons)

    def test_rejects_when_open_trade_exists(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        state.open_trade = object()
        candle = self._candle_with_funding(rate=-0.02, p10=-0.015)

        evaluation = evaluate_entry(candle, state)

        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_produces_a_stop_below_entry_no_target_field_exists(self) -> None:
        row = _make_candle_row(0, 100.0)
        row["atr"] = 2.0
        row["entry_funding_rate"] = -0.02
        candle = pd.Series(row)
        state = MeanReversionState(equity=10_000.0)

        trade = size_entry(candle, state)

        self.assertIsNotNone(trade)
        self.assertLess(trade.stop_loss, trade.entry_price)
        self.assertFalse(hasattr(trade, "target"))
        self.assertAlmostEqual(trade.entry_price - trade.stop_loss, 2.0 * 2.0, places=6)


class EvaluateExitTest(unittest.TestCase):
    def _open_trade_state(self) -> MeanReversionState:
        state = MeanReversionState(equity=10_000.0)
        row = _make_candle_row(0, 100.0)
        row["atr"] = 2.0
        row["entry_funding_rate"] = -0.02
        candle = pd.Series(row)
        trade = size_entry(candle, state)
        state.open_trade = trade
        return state

    def test_stop_loss_exit_takes_priority(self) -> None:
        state = self._open_trade_state()
        row = _make_candle_row(EIGHT_HOURS_MS, 100.0)
        row["low"] = state.open_trade.stop_loss - 1.0
        row["entry_funding_rate"] = 0.05  # would ALSO trigger FUNDING_NORMALIZED
        row["entry_funding_median"] = 0.001
        candle = pd.Series(row)

        exit_event = evaluate_exit(candle, state)

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "SL")

    def test_funding_normalized_exit_when_funding_rises_above_median(self) -> None:
        state = self._open_trade_state()
        row = _make_candle_row(EIGHT_HOURS_MS, 105.0)
        row["low"] = 104.0  # nowhere near the stop
        row["entry_funding_rate"] = 0.002
        row["entry_funding_median"] = 0.001
        candle = pd.Series(row)

        exit_event = evaluate_exit(candle, state)

        self.assertIsNotNone(exit_event)
        self.assertEqual(exit_event.exit_reason, "FUNDING_NORMALIZED")

    def test_no_exit_while_funding_still_below_median_and_stop_not_hit(self) -> None:
        state = self._open_trade_state()
        row = _make_candle_row(EIGHT_HOURS_MS, 101.0)
        row["low"] = 100.5
        row["entry_funding_rate"] = -0.01
        row["entry_funding_median"] = 0.001
        candle = pd.Series(row)

        exit_event = evaluate_exit(candle, state)

        self.assertIsNone(exit_event)

    def test_no_open_trade_returns_none(self) -> None:
        state = MeanReversionState(equity=10_000.0)
        row = _make_candle_row(0, 100.0)
        exit_event = evaluate_exit(pd.Series(row), state)
        self.assertIsNone(exit_event)


class RunBacktestTest(unittest.TestCase):
    def test_runs_end_to_end_without_error_on_a_synthetic_extreme(self) -> None:
        # 100 settlements near zero, then a deeply negative extreme, then normalization.
        rates = [0.0001] * 100 + [-0.05] * 3 + [0.01] * 10
        settlements = _settlements(rates)
        candles = _candles_8h(len(rates), price=100.0)

        enriched = add_indicators(candles, settlements, "8h")
        evaluable = enriched.dropna(subset=["atr", "entry_funding_rate", "entry_funding_p10"]).reset_index(drop=True)
        trades, state = run_backtest(evaluable)

        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, 0.0)


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "funding-extreme-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_no_max_holding_hours_or_target_field_on_parameters(self) -> None:
        params = FundingExtremeParameters()
        self.assertFalse(hasattr(params, "max_holding_hours"))
        self.assertFalse(hasattr(params, "reward_multiple"))
        self.assertFalse(hasattr(params, "target"))


if __name__ == "__main__":
    unittest.main()
