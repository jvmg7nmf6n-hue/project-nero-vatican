"""Phase D of the CC-1 substitution investigation-only audit
(docs/investigations/phase_d_exit_idempotency.md): does re-evaluating the
IDENTICAL exit tick a second time behave idempotently, matching the
ENTRY-side guarantee tests/test_repair_lab_forward_tracker.py already
proves (test_logging_the_exact_same_candle_twice_is_idempotent_not_a_
duplicate_signal)? This is a NEW, additive test file -- it does not modify
that file or nero_core/research_agent/repair_forward_tracker.py.

Uses its own temp SQLite file, never the repo's real
data/repair_lab_forward_tracking.db and never data/truth_ledger.db."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.research_agent.repair_forward_tracker import evaluate_forward_tick, resolved_trade_count

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)

# Identical fixture shape to tests/test_repair_lab_forward_tracker.py's own
# ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS (duplicated here, not imported, to keep
# this file fully self-contained per this phase's own instructions).
ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS = {
    "hypothesis_name": "REPAIR_ATTEMPT_TEST", "asset": "BTC", "timeframe": "1h",
    "structured_entry_rule": {"conditions": [{"field": "close", "op": "gt", "value": 0.0}]},
    "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.04},
}


def _candle(close_time: int, close: float, high: float | None = None, low: float | None = None) -> dict:
    return {
        "close_time": close_time, "open_time": close_time - 3_600_000,
        "close": close, "high": high if high is not None else close, "low": low if low is not None else close,
    }


class ExitTickIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_forward_tracking.db"
        self.addCleanup(self._tmp.cleanup)

    def test_reevaluating_the_identical_exit_tick_again_is_idempotent_not_a_new_entry(self) -> None:
        """Mirrors the ENTRY-side idempotency test's shape exactly: open,
        exit, then re-run the SAME tick that produced the exit. The
        ENTRY-side guarantee (test_logging_the_exact_same_candle_twice_is_
        idempotent_not_a_duplicate_signal) asserts the second call returns
        NO_TRADE. This test asserts the same for the EXIT side."""
        entry_candles = pd.DataFrame([_candle(1_700_000_000_000, 100.0)])
        entry_result = evaluate_forward_tick(
            "attempt-exit-idem", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, entry_candles, NOW, db_path=self.db_path
        )
        self.assertEqual(entry_result.signal_type, "ENTRY")
        target = entry_result.trade.target

        exit_candles = pd.DataFrame([
            _candle(1_700_000_000_000, 100.0),
            _candle(1_700_003_600_000, target + 0.5, high=target + 1.0, low=100.0),
        ])
        first_exit = evaluate_forward_tick(
            "attempt-exit-idem", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, exit_candles, NOW, db_path=self.db_path
        )
        self.assertEqual(first_exit.signal_type, "EXIT")
        self.assertEqual(resolved_trade_count("attempt-exit-idem", db_path=self.db_path), 1)

        # Re-evaluate the IDENTICAL exit tick again -- same attempt_id, same
        # candles, same `now`. Nothing new has happened; this must be a no-op.
        second_call = evaluate_forward_tick(
            "attempt-exit-idem", ALWAYS_FIRES_LONG_ONLY_HYPOTHESIS, exit_candles, NOW, db_path=self.db_path
        )
        self.assertEqual(
            second_call.signal_type, "NO_TRADE",
            "Re-evaluating the identical exit tick should be a no-op (matching the "
            "ENTRY-side idempotency guarantee), not open a new position.",
        )
        self.assertEqual(
            resolved_trade_count("attempt-exit-idem", db_path=self.db_path), 1,
            "The resolved trade count must not change from re-evaluating the same tick.",
        )


if __name__ == "__main__":
    unittest.main()
