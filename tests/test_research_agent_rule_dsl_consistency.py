"""HARD TEST (explicitly requested, not in the original task prompt): proves
frequency_gate.py (Task 2) and auto_tester.py (Task 4) actually AGREE on the
same triggers/timestamps for the same hypothesis, rather than merely "should"
agree because both happen to import from rule_dsl.py today. A future edit
that has one of the two modules stop calling rule_dsl (e.g. an entry check
inlined directly into auto_tester's backtest loop) is exactly the divergence
this test exists to catch -- see rule_dsl.py's own module docstring.

Design: candles carry rare, well-separated, single-candle price spikes (100+
hours apart) with a short max_holding_hours exit -- this guarantees no trigger
is ever skipped by auto_tester's "one open position at a time" rule, so
auto_tester's own executed-entry set is provably identical to the FULL trigger
set, not just a subset of it. That lets a plain COUNT comparison between the
gate and the tester be a real, meaningful equality check rather than a
tautology, and a spy on the tester's own entry-sizing call gives the exact
entry TIMESTAMPS actually used inside the backtest loop, which are compared
directly against rule_dsl.find_trigger_timestamps -- the same canonical list
frequency_gate.py computes internally via count_triggers.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from nero_core.research_agent import auto_tester
from nero_core.research_agent.frequency_gate import measure_entry_frequency
from nero_core.research_agent.rule_dsl import (
    compute_indicator_frame,
    find_trigger_rows,
    find_trigger_timestamps,
    parse_exit_plan,
    parse_structured_rule,
)
from nero_core.strategies.mean_reversion import MeanReversionParameters

HOUR_MS = 3_600_000
START_MS = 1_700_000_000_000
SPIKE_INDICES = [100, 250, 400, 550, 700, 850]  # >=150 hours apart -- see module docstring
SPIKE_VALUE = 500.0
BASELINE = 100.0

ENTRY_RULE = {"conditions": [{"field": "close", "op": "gt", "value": 200.0}]}
EXIT_PLAN = {"stop_atr_multiple": 1.5, "target_r_multiple": 1.0, "max_holding_hours": 2.0}


def _sparse_spike_candles(n: int = 1000) -> pd.DataFrame:
    rows = []
    for i in range(n):
        close = SPIKE_VALUE if i in SPIKE_INDICES else BASELINE + 0.1 * ((i % 7) - 3)
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    return pd.DataFrame(rows)


class GateAndTesterConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.candles = _sparse_spike_candles()
        self.generated_at = datetime.fromtimestamp((START_MS + len(self.candles) * HOUR_MS) / 1000, tz=timezone.utc)

    def test_trigger_counts_agree(self) -> None:
        gate_result = measure_entry_frequency(self.candles, ENTRY_RULE, self.generated_at)

        rule = parse_structured_rule(ENTRY_RULE)
        frame = compute_indicator_frame(self.candles)
        canonical_trigger_rows = find_trigger_rows(frame, rule)

        self.assertEqual(len(SPIKE_INDICES), len(canonical_trigger_rows))  # sanity: candle design actually produced the intended triggers
        self.assertEqual(gate_result.triggers_counted, len(canonical_trigger_rows))

    def test_executed_backtest_entries_match_the_gates_trigger_count_exactly(self) -> None:
        gate_result = measure_entry_frequency(self.candles, ENTRY_RULE, self.generated_at)

        rule = parse_structured_rule(ENTRY_RULE)
        exit_plan = parse_exit_plan(EXIT_PLAN)
        frame = compute_indicator_frame(self.candles)
        params = MeanReversionParameters(max_holding_hours=exit_plan.max_holding_hours)
        trades, _ = auto_tester.run_backtest(frame, rule, exit_plan, params)

        # every trigger closed (no overlap, per module docstring) -> one resolved
        # trade per trigger, and that count matches the gate's own measured count exactly.
        self.assertEqual(len(trades), gate_result.triggers_counted)

    def test_executed_backtest_entry_timestamps_match_the_gates_canonical_timestamps(self) -> None:
        rule = parse_structured_rule(ENTRY_RULE)
        exit_plan = parse_exit_plan(EXIT_PLAN)
        frame = compute_indicator_frame(self.candles)
        params = MeanReversionParameters(max_holding_hours=exit_plan.max_holding_hours)

        canonical_timestamps = find_trigger_timestamps(frame, rule)

        executed_entry_timestamps: list[int] = []
        real_size_entry = auto_tester._size_entry_for_hypothesis

        def _spy(candle, state, p, ep):
            trade = real_size_entry(candle, state, p, ep)
            if trade is not None:
                executed_entry_timestamps.append(trade.open_close_time)
            return trade

        with patch("nero_core.research_agent.auto_tester._size_entry_for_hypothesis", side_effect=_spy):
            auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(executed_entry_timestamps, canonical_timestamps)

    def test_a_future_divergence_would_be_caught(self) -> None:
        """Sanity check on the test design itself: a DIFFERENT rule really does
        produce a different trigger count, proving the equality checks above are
        exercising real agreement, not two constants that happen to match."""
        different_rule_dict = {"conditions": [{"field": "close", "op": "gt", "value": 9999.0}]}  # never fires
        gate_result = measure_entry_frequency(self.candles, different_rule_dict, self.generated_at)
        self.assertEqual(gate_result.triggers_counted, 0)
        self.assertNotEqual(gate_result.triggers_counted, len(SPIKE_INDICES))


# --------------------------------------------------------------------------------
# Field-vs-field (added 2026-07-30): the same gate/tester agreement guarantee must
# hold for a moving-average CROSSOVER, not just a field-vs-constant trigger --
# proving the DSL extension didn't create a second code path either module could
# silently diverge on.
# --------------------------------------------------------------------------------

MA_CROSS_RULE = {"conditions": [{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}]}
# Generous exit -- irrelevant to this test, which only checks ENTRY agreement.
MA_CROSS_EXIT_PLAN = {"stop_atr_multiple": 3.0, "target_r_multiple": 3.0, "max_holding_hours": 5000.0}


def _ma_crossover_candles(flat: int = 70, growth: int = 60) -> pd.DataFrame:
    """`flat` candles at a constant price (ma20 == ma50, both fully warmed up)
    then `growth` candles of sustained 0.8%/candle growth -- the faster ma20
    crosses above the slower ma50 exactly once (verified empirically before
    writing this test: at index `flat` for flat=70, growth=60)."""
    rows = []
    close = 100.0
    for i in range(flat + growth):
        if i >= flat:
            close *= 1.008
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    return pd.DataFrame(rows)


class FieldVsFieldConsistencyTest(unittest.TestCase):
    def test_ma_crossover_trigger_and_entry_timestamps_agree_between_gate_and_tester(self) -> None:
        candles = _ma_crossover_candles()
        generated_at = datetime.fromtimestamp((START_MS + len(candles) * HOUR_MS) / 1000, tz=timezone.utc)

        gate_result = measure_entry_frequency(candles, MA_CROSS_RULE, generated_at)

        rule = parse_structured_rule(MA_CROSS_RULE)
        exit_plan = parse_exit_plan(MA_CROSS_EXIT_PLAN)
        frame = compute_indicator_frame(candles)
        canonical_timestamps = find_trigger_timestamps(frame, rule)

        self.assertEqual(len(canonical_timestamps), 1)  # sanity: the candle design produced exactly one crossover
        self.assertEqual(gate_result.triggers_counted, 1)

        params = MeanReversionParameters(max_holding_hours=exit_plan.max_holding_hours)
        executed_entry_timestamps: list[int] = []
        real_size_entry = auto_tester._size_entry_for_hypothesis

        def _spy(candle, state, p, ep):
            trade = real_size_entry(candle, state, p, ep)
            if trade is not None:
                executed_entry_timestamps.append(trade.open_close_time)
            return trade

        with patch("nero_core.research_agent.auto_tester._size_entry_for_hypothesis", side_effect=_spy):
            auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(executed_entry_timestamps, canonical_timestamps)


# --------------------------------------------------------------------------------
# ADX (added for feature/exitplan-dynamic-target-and-hysteresis, RMR_LONG_ONLY_
# EURUSD_4H's own regime gate): the same gate/tester agreement guarantee must hold
# for adx14 as an ENTRY field, not just as part of an exit shape.
# --------------------------------------------------------------------------------

ADX_ENTRY_RULE = {"conditions": [{"field": "adx14", "op": "cross_below", "value": 25.0}]}
# Generous exit -- irrelevant to this test, which only checks ENTRY agreement.
ADX_EXIT_PLAN = {"stop_atr_multiple": 3.0, "target_r_multiple": 3.0, "max_holding_hours": 5000.0}


def _trend_then_range_candles(trend: int = 60, ranging: int = 60) -> pd.DataFrame:
    """`trend` candles of sustained directional movement (drives ADX up, well
    past 25) followed by `ranging` candles of small oscillation around a flat
    level (drives ADX back down) -- ADX crossing below 25 is exactly the
    regime-entry condition RMR_LONG_ONLY_EURUSD_4H itself depends on, so this
    exercises the real mechanism, not a synthetic stand-in for it."""
    rows = []
    close = 100.0
    for i in range(trend):
        close *= 1.006
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    for j in range(ranging):
        i = trend + j
        close = close * (1.0 + 0.0006 * ((j % 4) - 1.5))  # tiny back-and-forth, near-zero net drift
        rows.append({"close_time": START_MS + i * HOUR_MS, "close": close, "high": close + 0.3, "low": close - 0.3, "volume": 1.0})
    return pd.DataFrame(rows)


class AdxConsistencyTest(unittest.TestCase):
    """Proves the ADX wiring didn't create a second code path either module
    could silently diverge on, exactly like FieldVsFieldConsistencyTest above
    already proves for a moving-average crossover."""

    def test_adx_regime_entry_trigger_and_timestamps_agree_between_gate_and_tester(self) -> None:
        candles = _trend_then_range_candles()
        generated_at = datetime.fromtimestamp((START_MS + len(candles) * HOUR_MS) / 1000, tz=timezone.utc)

        gate_result = measure_entry_frequency(candles, ADX_ENTRY_RULE, generated_at)

        rule = parse_structured_rule(ADX_ENTRY_RULE)
        exit_plan = parse_exit_plan(ADX_EXIT_PLAN)
        frame = compute_indicator_frame(candles)
        canonical_timestamps = find_trigger_timestamps(frame, rule)

        # sanity: the trend->range design actually produced at least one real
        # ADX-below-25 regime entry -- otherwise the equality checks below would
        # be vacuously true (0 == 0) rather than exercising real agreement.
        self.assertGreater(len(canonical_timestamps), 0)
        self.assertEqual(gate_result.triggers_counted, len(canonical_timestamps))

        params = MeanReversionParameters(max_holding_hours=exit_plan.max_holding_hours)
        executed_entry_timestamps: list[int] = []
        real_size_entry = auto_tester._size_entry_for_hypothesis

        def _spy(candle, state, p, ep):
            trade = real_size_entry(candle, state, p, ep)
            if trade is not None:
                executed_entry_timestamps.append(trade.open_close_time)
            return trade

        with patch("nero_core.research_agent.auto_tester._size_entry_for_hypothesis", side_effect=_spy):
            auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(executed_entry_timestamps, canonical_timestamps)


# --------------------------------------------------------------------------------
# RMR-shaped exit plan (dynamic_target_condition + regime_break_condition + no
# time cap): frequency_gate never reads structured_exit_plan at all (see
# frequency_gate.py's own docstring/measure_entry_frequency, which only takes
# structured_entry_rule) -- so ENTRY-side gate/tester agreement is unaffected by
# the exit shape BY CONSTRUCTION. The real value of this test is proving
# run_backtest doesn't crash/mis-parse when given the new exit shape at all,
# while re-confirming that construction holds rather than merely asserting it.
# --------------------------------------------------------------------------------

RMR_SHAPED_EXIT_PLAN = {
    "stop_atr_multiple": 2.0,
    "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
    "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
    "regime_break_consecutive_bars": 2,
}


class RmrShapedExitPlanConsistencyTest(unittest.TestCase):
    def test_entry_side_agreement_holds_unchanged_with_the_new_exit_shape(self) -> None:
        candles = _ma_crossover_candles()
        generated_at = datetime.fromtimestamp((START_MS + len(candles) * HOUR_MS) / 1000, tz=timezone.utc)

        gate_result = measure_entry_frequency(candles, MA_CROSS_RULE, generated_at)

        rule = parse_structured_rule(MA_CROSS_RULE)
        exit_plan = parse_exit_plan(RMR_SHAPED_EXIT_PLAN)
        frame = compute_indicator_frame(candles)
        canonical_timestamps = find_trigger_timestamps(frame, rule)

        self.assertEqual(len(canonical_timestamps), 1)  # same sanity as FieldVsFieldConsistencyTest above
        self.assertEqual(gate_result.triggers_counted, 1)

        params = MeanReversionParameters()  # max_holding_hours irrelevant -- exit_plan's own None wins
        executed_entry_timestamps: list[int] = []
        real_size_entry = auto_tester._size_entry_for_hypothesis

        def _spy(candle, state, p, ep):
            trade = real_size_entry(candle, state, p, ep)
            if trade is not None:
                executed_entry_timestamps.append(trade.open_close_time)
            return trade

        # Must not raise -- the real proof this test adds beyond entry-agreement
        # (which frequency_gate's own ignorance of exit_plan already guarantees).
        with patch("nero_core.research_agent.auto_tester._size_entry_for_hypothesis", side_effect=_spy):
            auto_tester.run_backtest(frame, rule, exit_plan, params)

        self.assertEqual(executed_entry_timestamps, canonical_timestamps)


if __name__ == "__main__":
    unittest.main()
