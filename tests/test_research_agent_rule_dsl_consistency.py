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


if __name__ == "__main__":
    unittest.main()
