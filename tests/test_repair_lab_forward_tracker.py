"""Repair Lab v1, Task 4b: the forward-testing tick and PENDING_FORWARD_DATA
resolution. Every test uses its own temp SQLite file (never the repo's real
data/repair_lab_forward_tracking.db, and never data/truth_ledger.db --
proving physical isolation is trivial by construction: a different db_path
argument to every call)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.research_agent.repair_forward_tracker import (
    compute_forward_verdict,
    evaluate_forward_tick,
    resolved_trade_count,
)
from tools.backtest_statistics import MIN_SAMPLE_SIZE

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)

# Fires unconditionally (no warmup needed -- "close" is never NaN), keeping
# these tests about the TICK MECHANISM (state reconstruction, idempotency,
# verdict computation), not about indicator warmup or rule semantics --
# those are already covered by test_research_agent_rule_dsl*.py.
ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS = {
    "hypothesis_name": "REPAIR_ATTEMPT_TEST", "asset": "BTC", "timeframe": "1h",
    "structured_entry_rule": {"conditions": [{"field": "close", "op": "gt", "value": 0.0}]},
    # target (4%) comfortably clears entry+exit fee/slippage drag (~20bps at
    # MeanReversionParameters' own defaults) so a TARGET exit is unambiguously
    # net-positive, and a STOP exit (2%) is unambiguously net-negative.
    "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.04},
}


def _candle(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "close_time": close_time, "open_time": close_time - 3_600_000,
        "close": close, "high": high if high is not None else close, "low": low if low is not None else close,
    }


class ForwardTickMechanismTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_forward_tracking.db"
        self.addCleanup(self._tmp.cleanup)

    def test_first_tick_with_no_open_position_and_a_firing_rule_opens_a_long(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        result = evaluate_forward_tick("attempt-1", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        self.assertEqual(result.signal_type, "ENTRY")
        self.assertIsNotNone(result.trade)
        self.assertEqual(result.trade.direction, "LONG")

    def test_a_tick_with_an_open_position_and_no_exit_condition_met_is_no_trade(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        evaluate_forward_tick("attempt-2", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)

        # Price barely moves -- target (0.1% above entry) and stop (50% below) both miss.
        candles_2 = pd.DataFrame([_candle(1_700_000_000_000, 100.0), _candle(1_700_003_600_000, 100.05, high=100.06, low=100.04)])
        result = evaluate_forward_tick("attempt-2", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles_2, NOW, db_path=self.db_path)
        self.assertEqual(result.signal_type, "NO_TRADE")

    def test_a_tick_that_hits_target_closes_the_position(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        entry_result = evaluate_forward_tick("attempt-3", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        target = entry_result.trade.target

        candles_2 = pd.DataFrame([
            _candle(1_700_000_000_000, 100.0),
            _candle(1_700_003_600_000, target + 0.5, high=target + 1.0, low=100.0),
        ])
        exit_result = evaluate_forward_tick("attempt-3", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles_2, NOW, db_path=self.db_path)
        self.assertEqual(exit_result.signal_type, "EXIT")
        self.assertEqual(exit_result.exit_event.exit_reason, "TARGET")
        self.assertGreater(exit_result.exit_event.r_multiple, 0.0)

    def test_after_an_exit_the_next_firing_tick_opens_a_new_position_not_stuck_closed(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        entry_1 = evaluate_forward_tick("attempt-4", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        target = entry_1.trade.target

        candles_2 = pd.DataFrame([
            _candle(1_700_000_000_000, 100.0),
            _candle(1_700_003_600_000, target + 0.5, high=target + 1.0, low=100.0),
        ])
        evaluate_forward_tick("attempt-4", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles_2, NOW, db_path=self.db_path)

        candles_3 = pd.concat([candles_2, pd.DataFrame([_candle(1_700_007_200_000, target + 0.6)])], ignore_index=True)
        entry_2 = evaluate_forward_tick("attempt-4", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles_3, NOW, db_path=self.db_path)
        self.assertEqual(entry_2.signal_type, "ENTRY")

    def test_logging_the_exact_same_candle_twice_is_idempotent_not_a_duplicate_signal(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        first = evaluate_forward_tick("attempt-5", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        self.assertEqual(first.signal_type, "ENTRY")

        # Re-evaluating the IDENTICAL single-candle tick again must not open a
        # second position (the entry is already logged for this candle_timestamp).
        second = evaluate_forward_tick("attempt-5", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        self.assertEqual(second.signal_type, "NO_TRADE")

    def test_two_different_attempts_never_see_each_others_open_positions(self) -> None:
        candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        evaluate_forward_tick("attempt-a", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)

        # attempt-b's own first tick, same db_path, same candle -- must see NO
        # open position of its own (attempt-a's state must not leak across).
        result_b = evaluate_forward_tick("attempt-b", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, candles, NOW, db_path=self.db_path)
        self.assertEqual(result_b.signal_type, "ENTRY")

    def test_no_candles_is_no_trade_not_an_error(self) -> None:
        result = evaluate_forward_tick("attempt-6", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, pd.DataFrame(), NOW, db_path=self.db_path)
        self.assertEqual(result.signal_type, "NO_TRADE")


class ForwardVerdictResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_forward_tracking.db"
        self.addCleanup(self._tmp.cleanup)

    def _run_one_entry_exit_cycle(self, attempt_id: str, cycle_index: int, win: bool) -> None:
        base = 1_700_000_000_000 + cycle_index * 100_000_000_000
        entry_candles = pd.DataFrame([_candle(base, 100.0)])
        entry = evaluate_forward_tick(attempt_id, ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, entry_candles, NOW, db_path=self.db_path)
        self.assertEqual(entry.signal_type, "ENTRY")
        target, stop = entry.trade.target, entry.trade.stop_loss

        if win:
            exit_close = target + 0.5
            exit_high, exit_low = target + 1.0, 100.0
        else:
            exit_close = stop - 0.5
            exit_high, exit_low = 100.0, stop - 1.0

        exit_candles = pd.DataFrame([_candle(base, 100.0), _candle(base + 3_600_000, exit_close, high=exit_high, low=exit_low)])
        exit_result = evaluate_forward_tick(attempt_id, ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, exit_candles, NOW, db_path=self.db_path)
        self.assertEqual(exit_result.signal_type, "EXIT")

    def test_pending_below_two_times_min_sample_size_returns_none_not_a_fabricated_verdict(self) -> None:
        for i in range(MIN_SAMPLE_SIZE):  # only 1x MIN_SAMPLE_SIZE, not 2x -- must stay pending
            self._run_one_entry_exit_cycle("attempt-pending", i, win=(i % 2 == 0))
        self.assertEqual(resolved_trade_count("attempt-pending", db_path=self.db_path), MIN_SAMPLE_SIZE)
        self.assertIsNone(compute_forward_verdict("attempt-pending", db_path=self.db_path))

    def test_enough_resolved_trades_produces_a_real_verdict_via_the_shared_classify_verdict(self) -> None:
        for i in range(2 * MIN_SAMPLE_SIZE):
            self._run_one_entry_exit_cycle("attempt-resolved", i, win=True)  # every trade a winner
        self.assertEqual(resolved_trade_count("attempt-resolved", db_path=self.db_path), 2 * MIN_SAMPLE_SIZE)

        verdict_result = compute_forward_verdict("attempt-resolved", db_path=self.db_path)
        self.assertIsNotNone(verdict_result)
        self.assertEqual(verdict_result["train"]["trades"], MIN_SAMPLE_SIZE)
        self.assertEqual(verdict_result["test"]["trades"], MIN_SAMPLE_SIZE)
        self.assertGreater(verdict_result["train"]["expectancy_r"], 0.0)
        self.assertGreater(verdict_result["test"]["expectancy_r"], 0.0)
        # every trade a real, resolved winner on adequate sample -- SURVIVED is the
        # expected, honest verdict here (not asserted as a magic string elsewhere).
        self.assertIn(verdict_result["verdict"], ("SURVIVED", "PROMISING-WATCHLIST"))

    def test_all_losing_trades_at_adequate_sample_produces_died(self) -> None:
        for i in range(2 * MIN_SAMPLE_SIZE):
            self._run_one_entry_exit_cycle("attempt-died", i, win=False)
        verdict_result = compute_forward_verdict("attempt-died", db_path=self.db_path)
        self.assertIsNotNone(verdict_result)
        self.assertEqual(verdict_result["verdict"], "DIED")


if __name__ == "__main__":
    unittest.main()
