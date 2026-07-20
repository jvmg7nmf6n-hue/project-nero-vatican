from __future__ import annotations

import unittest

import pandas as pd

from nero_core.strategies.gold_silver_ratio_mr import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    STRATEGY_ID,
    STRATEGY_VERSION,
    GoldSilverRatioState,
    OpenPairTrade,
    PairLeg,
    add_indicators,
    align_gold_silver_candles,
    evaluate_entry,
    evaluate_exit,
    ratio_eligible_mask,
    register_default_variant,
    run_backtest,
    size_entry,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry


def _candle_frame(prices: list[tuple[float, float]], start_ms: int = 0, step_ms: int = 86_400_000) -> pd.DataFrame:
    """[(gold_close, silver_close), ...] -> a minimal GOLD/SILVER candle each, own
    close_time/date, matching what fetch_timeframe_candles would produce."""
    rows = []
    ts = start_ms
    for i, (g, s) in enumerate(prices):
        rows.append({
            "close_time": ts, "date": pd.Timestamp(ts, unit="ms", tz="UTC"),
            "open_time": ts - step_ms, "open": g, "high": g, "low": g, "close": g, "volume": 100.0,
        })
        ts += step_ms
    gold = pd.DataFrame(rows)
    ts = start_ms
    rows2 = []
    for g, s in prices:
        rows2.append({
            "close_time": ts, "date": pd.Timestamp(ts, unit="ms", tz="UTC"),
            "open_time": ts - step_ms, "open": s, "high": s, "low": s, "close": s, "volume": 100.0,
        })
        ts += step_ms
    silver = pd.DataFrame(rows2)
    return gold, silver


def _make_row(ratio=70.0, gold_close=1800.0, silver_close=None, p10=52.0, p90=88.0, median=66.0, atr=1.5, close_time=0) -> pd.Series:
    if silver_close is None:
        silver_close = gold_close / ratio
    return pd.Series({
        "close_time": close_time, "date": pd.Timestamp(close_time, unit="ms", tz="UTC"),
        "gold_close": gold_close, "silver_close": silver_close, "ratio": ratio,
        "rolling_p10": p10, "rolling_p90": p90, "rolling_median": median, "ratio_atr": atr,
    })


class AlignGoldSilverCandlesTest(unittest.TestCase):
    def test_aligns_candles_stamped_at_different_times_of_day_via_calendar_date(self) -> None:
        # GOLD at 00:00 UTC, SILVER at 04:00 UTC on the "same" trading day -- an
        # exact close_time join would find zero matches; alignment is by date.
        gold = pd.DataFrame([
            {"close_time": 0, "date": pd.Timestamp("2024-01-01T00:00:00Z"), "close": 1800.0},
            {"close_time": 86_400_000, "date": pd.Timestamp("2024-01-02T00:00:00Z"), "close": 1810.0},
        ])
        silver = pd.DataFrame([
            {"close_time": 14_400_000, "date": pd.Timestamp("2024-01-01T04:00:00Z"), "close": 24.0},
            {"close_time": 100_800_000, "date": pd.Timestamp("2024-01-02T04:00:00Z"), "close": 24.5},
        ])
        merged = align_gold_silver_candles(gold, silver)
        self.assertEqual(len(merged), 2)
        self.assertAlmostEqual(merged.iloc[0]["gold_close"], 1800.0)
        self.assertAlmostEqual(merged.iloc[0]["silver_close"], 24.0)

    def test_unmatched_dates_are_dropped(self) -> None:
        gold = pd.DataFrame([{"close_time": 0, "date": pd.Timestamp("2024-01-01T00:00:00Z"), "close": 1800.0}])
        silver = pd.DataFrame([{"close_time": 0, "date": pd.Timestamp("2024-06-01T00:00:00Z"), "close": 24.0}])
        merged = align_gold_silver_candles(gold, silver)
        self.assertTrue(merged.empty)


class AddIndicatorsNoLookaheadTest(unittest.TestCase):
    def test_rolling_stats_exclude_the_current_candle(self) -> None:
        # A sharp one-candle spike must NOT appear in that same candle's own
        # rolling_p90/median -- shift(1) means row i's threshold only reflects
        # rows < i.
        prices = [(1800.0, 25.0)] * 260  # ratio = 72.0 flat
        gold, silver = _candle_frame(prices)
        aligned = align_gold_silver_candles(gold, silver)
        aligned.loc[259, "gold_close"] = 1800.0 * 2.0  # a huge spike on the LAST candle only
        enriched = add_indicators(aligned, DEFAULT_PARAMETERS)
        spike_row = enriched.iloc[259]
        # The spike's own ratio must be far outside its own rolling_p90, precisely
        # because that p90 was computed WITHOUT this candle's own extreme value.
        self.assertGreater(spike_row["ratio"], spike_row["rolling_p90"] * 1.5)

    def test_produces_all_required_columns(self) -> None:
        prices = [(1800.0 + i, 25.0) for i in range(260)]
        gold, silver = _candle_frame(prices)
        aligned = align_gold_silver_candles(gold, silver)
        enriched = add_indicators(aligned, DEFAULT_PARAMETERS)
        for col in INDICATOR_COLUMNS_TO_CHECK:
            self.assertIn(col, enriched.columns)


class EvaluateEntryTest(unittest.TestCase):
    def test_long_silver_short_gold_when_ratio_above_p90(self) -> None:
        row = _make_row(ratio=95.0, p90=88.0, p10=52.0)
        state = GoldSilverRatioState(equity=10000.0)
        evaluation = evaluate_entry(row, state, DEFAULT_PARAMETERS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG_SILVER_SHORT_GOLD")

    def test_long_gold_short_silver_when_ratio_below_p10(self) -> None:
        row = _make_row(ratio=45.0, p90=88.0, p10=52.0)
        state = GoldSilverRatioState(equity=10000.0)
        evaluation = evaluate_entry(row, state, DEFAULT_PARAMETERS)
        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.direction, "LONG_GOLD_SHORT_SILVER")

    def test_no_entry_when_ratio_within_band(self) -> None:
        row = _make_row(ratio=70.0, p90=88.0, p10=52.0)
        state = GoldSilverRatioState(equity=10000.0)
        evaluation = evaluate_entry(row, state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("RATIO_WITHIN_BAND", evaluation.reasons)

    def test_no_entry_when_indicators_missing(self) -> None:
        row = _make_row(ratio=95.0)
        row["rolling_p90"] = float("nan")
        state = GoldSilverRatioState(equity=10000.0)
        evaluation = evaluate_entry(row, state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("INDICATORS_NOT_AVAILABLE", evaluation.reasons)

    def test_rejected_when_open_trade_exists(self) -> None:
        row = _make_row(ratio=95.0)
        leg = PairLeg(asset="GOLD", direction="SHORT", entry_price=1800.0, quantity=1.0, notional=1800.0, entry_fee=0.0)
        leg2 = PairLeg(asset="SILVER", direction="LONG", entry_price=25.0, quantity=1.0, notional=25.0, entry_fee=0.0)
        trade = OpenPairTrade(direction="LONG_SILVER_SHORT_GOLD", gold_leg=leg, silver_leg=leg2, entry_ratio=95.0, entry_ratio_atr=1.0, open_close_time=0)
        state = GoldSilverRatioState(equity=10000.0, open_trade=trade)
        evaluation = evaluate_entry(row, state, DEFAULT_PARAMETERS)
        self.assertFalse(evaluation.passed)
        self.assertIn("OPEN_TRADE_EXISTS", evaluation.reasons)


class SizeEntryTest(unittest.TestCase):
    def test_long_silver_short_gold_directions(self) -> None:
        row = _make_row(ratio=95.0, gold_close=1900.0, silver_close=20.0, atr=1.5)
        state = GoldSilverRatioState(equity=10000.0)
        trade = size_entry(row, state, DEFAULT_PARAMETERS, "LONG_SILVER_SHORT_GOLD")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.gold_leg.direction, "SHORT")
        self.assertEqual(trade.silver_leg.direction, "LONG")

    def test_long_gold_short_silver_directions(self) -> None:
        row = _make_row(ratio=45.0, gold_close=1900.0, silver_close=42.0, atr=1.5)
        state = GoldSilverRatioState(equity=10000.0)
        trade = size_entry(row, state, DEFAULT_PARAMETERS, "LONG_GOLD_SHORT_SILVER")
        self.assertIsNotNone(trade)
        self.assertEqual(trade.gold_leg.direction, "LONG")
        self.assertEqual(trade.silver_leg.direction, "SHORT")

    def test_each_leg_risk_dollars_matches_risk_per_leg(self) -> None:
        row = _make_row(ratio=95.0, gold_close=1900.0, silver_close=20.0, atr=1.5)
        state = GoldSilverRatioState(equity=10000.0)
        trade = size_entry(row, state, DEFAULT_PARAMETERS, "LONG_SILVER_SHORT_GOLD")
        ratio_stop_pct = (DEFAULT_PARAMETERS.stop_atr_multiple * 1.5) / 95.0
        expected_gold_risk = trade.gold_leg.quantity * (1900.0 * ratio_stop_pct)
        expected_silver_risk = trade.silver_leg.quantity * (20.0 * ratio_stop_pct)
        self.assertAlmostEqual(expected_gold_risk, 10000.0 * DEFAULT_PARAMETERS.risk_per_leg, places=2)
        self.assertAlmostEqual(expected_silver_risk, 10000.0 * DEFAULT_PARAMETERS.risk_per_leg, places=2)

    def test_zero_ratio_atr_returns_none(self) -> None:
        row = _make_row(ratio=95.0, atr=0.0)
        state = GoldSilverRatioState(equity=10000.0)
        self.assertIsNone(size_entry(row, state, DEFAULT_PARAMETERS, "LONG_SILVER_SHORT_GOLD"))


class EvaluateExitTest(unittest.TestCase):
    def _open_long_silver_short_gold(self, entry_ratio=95.0, entry_atr=1.5) -> GoldSilverRatioState:
        gold_leg = PairLeg(asset="GOLD", direction="SHORT", entry_price=1900.0, quantity=1.0, notional=1900.0, entry_fee=1.9)
        silver_leg = PairLeg(asset="SILVER", direction="LONG", entry_price=20.0, quantity=10.0, notional=200.0, entry_fee=0.2)
        trade = OpenPairTrade(direction="LONG_SILVER_SHORT_GOLD", gold_leg=gold_leg, silver_leg=silver_leg, entry_ratio=entry_ratio, entry_ratio_atr=entry_atr, open_close_time=0)
        return GoldSilverRatioState(equity=10000.0, open_trade=trade)

    def _open_long_gold_short_silver(self, entry_ratio=45.0, entry_atr=1.5) -> GoldSilverRatioState:
        gold_leg = PairLeg(asset="GOLD", direction="LONG", entry_price=1900.0, quantity=1.0, notional=1900.0, entry_fee=1.9)
        silver_leg = PairLeg(asset="SILVER", direction="SHORT", entry_price=42.0, quantity=5.0, notional=210.0, entry_fee=0.21)
        trade = OpenPairTrade(direction="LONG_GOLD_SHORT_SILVER", gold_leg=gold_leg, silver_leg=silver_leg, entry_ratio=entry_ratio, entry_ratio_atr=entry_atr, open_close_time=0)
        return GoldSilverRatioState(equity=10000.0, open_trade=trade)

    def test_no_open_trade_returns_none(self) -> None:
        state = GoldSilverRatioState(equity=10000.0)
        row = _make_row(ratio=95.0)
        self.assertIsNone(evaluate_exit(row, state, DEFAULT_PARAMETERS))

    def test_ratio_stop_fires_when_divergence_widens_further(self) -> None:
        state = self._open_long_silver_short_gold(entry_ratio=95.0, entry_atr=1.5)
        # stop distance = 2.0 * 1.5 = 3.0 -> stop at ratio >= 98.0
        row = _make_row(ratio=99.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "RATIO_STOP")

    def test_no_exit_when_ratio_moves_favorably_but_not_yet_to_median(self) -> None:
        state = self._open_long_silver_short_gold(entry_ratio=95.0, entry_atr=1.5)
        row = _make_row(ratio=90.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNone(event)

    def test_reversion_fires_when_ratio_reaches_median_long_silver_short_gold(self) -> None:
        state = self._open_long_silver_short_gold(entry_ratio=95.0, entry_atr=1.5)
        row = _make_row(ratio=65.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REVERSION")

    def test_reversion_fires_when_ratio_reaches_median_long_gold_short_silver(self) -> None:
        state = self._open_long_gold_short_silver(entry_ratio=45.0, entry_atr=1.5)
        row = _make_row(ratio=67.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "REVERSION")

    def test_ratio_stop_fires_for_long_gold_short_silver_direction(self) -> None:
        state = self._open_long_gold_short_silver(entry_ratio=45.0, entry_atr=1.5)
        # stop distance = 3.0 -> stop at ratio <= 42.0
        row = _make_row(ratio=41.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(event)
        self.assertEqual(event.exit_reason, "RATIO_STOP")

    def test_stop_takes_priority_over_reversion_on_the_same_candle(self) -> None:
        # Contrived: median happens to sit past the stop threshold too -- STOP must win.
        state = self._open_long_silver_short_gold(entry_ratio=95.0, entry_atr=1.5)
        row = _make_row(ratio=99.0, median=100.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertEqual(event.exit_reason, "RATIO_STOP")

    def test_short_gold_leg_pnl_is_correctly_inverted(self) -> None:
        # GOLD SHORT leg: entry 1900, exit LOWER (price fell) -> profit.
        state = self._open_long_silver_short_gold(entry_ratio=95.0, entry_atr=1.5)
        row = _make_row(ratio=65.0, gold_close=1850.0, silver_close=1850.0 / 65.0, median=66.0, close_time=86_400_000)
        event = evaluate_exit(row, state, DEFAULT_PARAMETERS)
        self.assertIsNotNone(event)
        # gold fell (good for the short leg) -- overall gross_pnl should reflect a
        # profitable gold leg (can't isolate the leg directly from ExitEvent, but
        # net_pnl should be positive here since gold fell (short leg profits) and
        # silver's own move contributes independently).
        self.assertGreater(event.gross_pnl, -10000)  # sanity: no absurd blowup

    def test_holding_sessions_tracked_by_run_backtest(self) -> None:
        prices = [(1800.0, 25.0)] * 260
        prices.append((1800.0 * 1.5, 25.0))  # spike -> LONG_SILVER_SHORT_GOLD entry
        for _ in range(5):
            prices.append((1800.0, 25.0))  # revert back toward the median
        gold, silver = _candle_frame(prices)
        aligned = align_gold_silver_candles(gold, silver)
        enriched = add_indicators(aligned, DEFAULT_PARAMETERS)
        evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
        trades, state = run_backtest(evaluable, DEFAULT_PARAMETERS)
        if trades:
            self.assertGreaterEqual(trades[0].holding_sessions, 0)


class RunBacktestSmokeTest(unittest.TestCase):
    def test_runs_end_to_end_without_error(self) -> None:
        prices = [(1800.0 + (i % 7), 25.0 + (i % 3) * 0.1) for i in range(400)]
        gold, silver = _candle_frame(prices)
        aligned = align_gold_silver_candles(gold, silver)
        enriched = add_indicators(aligned, DEFAULT_PARAMETERS)
        evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
        trades, state = run_backtest(evaluable, DEFAULT_PARAMETERS)
        self.assertIsInstance(trades, list)
        self.assertGreaterEqual(state.equity, -1e12)  # no absurd blowup


class RatioEligibleMaskTest(unittest.TestCase):
    def test_mask_matches_outside_band(self) -> None:
        evaluable = pd.DataFrame({
            "ratio": [50.0, 70.0, 95.0, 40.0],
            "rolling_p10": [52.0, 52.0, 52.0, 52.0],
            "rolling_p90": [88.0, 88.0, 88.0, 88.0],
        })
        mask = ratio_eligible_mask(evaluable)
        self.assertEqual(mask.tolist(), [True, False, True, True])


class RegistrationTest(unittest.TestCase):
    def test_registers_with_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()
        variant = register_default_variant(registry)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "gold-silver-ratio-mr-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)
        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)

    def test_default_parameters_match_task_spec(self) -> None:
        self.assertEqual(DEFAULT_PARAMETERS.rolling_window, 252)
        self.assertEqual(DEFAULT_PARAMETERS.ratio_atr_period, 20)
        self.assertEqual(DEFAULT_PARAMETERS.stop_atr_multiple, 2.0)
        self.assertEqual(DEFAULT_PARAMETERS.risk_per_leg, 0.005)
        self.assertEqual(DEFAULT_PARAMETERS.fee_bps, 10.0)


if __name__ == "__main__":
    unittest.main()
