from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent.performance import load_performance, record_run

NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _FakeResult:
    enabled: bool
    reason: str = ""
    status: str = "clean"
    errors: list = field(default_factory=list)
    hypotheses_generated: int = 0
    duplicates_skipped: int = 0
    llm_calls_made: int = 0
    total_llm_cost_usd: float = 0.0
    cost_limit_hit: bool = False
    too_slow_rejected: int = 0
    unmeasurable_rejected: int = 0
    survived: int = 0
    promising_watchlist: int = 0
    died: int = 0
    untestable: int = 0
    no_candles_available: int = 0
    test_results: list = field(default_factory=list)


class RecordRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "agent_performance.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fresh_file_starts_with_null_survival_rate(self) -> None:
        state = load_performance(self.path)
        self.assertIsNone(state["cumulative"]["survival_rate"])
        self.assertEqual(state["runs"], [])

    def test_single_run_updates_cumulative_and_appends_run_entry(self) -> None:
        result = _FakeResult(
            enabled=True, hypotheses_generated=5, duplicates_skipped=2, llm_calls_made=5,
            total_llm_cost_usd=1.25, too_slow_rejected=1, unmeasurable_rejected=1,
            survived=1, promising_watchlist=1, died=1, untestable=0,
        )
        state = record_run(result, self.path, now=NOW)

        self.assertEqual(state["cumulative"]["hypotheses_generated"], 5)
        self.assertEqual(state["cumulative"]["duplicates_skipped"], 2)
        self.assertEqual(state["cumulative"]["too_slow_rejected"], 1)
        self.assertEqual(state["cumulative"]["unmeasurable_rejected"], 1)
        self.assertEqual(state["cumulative"]["tested"], 3)  # survived+watchlist+died+untestable
        self.assertEqual(state["cumulative"]["survived"], 1)
        self.assertAlmostEqual(state["cumulative"]["total_llm_cost_usd"], 1.25)
        # survival_rate = (survived + watchlist) / tested = 2/3
        self.assertAlmostEqual(state["cumulative"]["survival_rate"], 2 / 3)
        self.assertEqual(len(state["runs"]), 1)
        self.assertEqual(state["runs"][0]["run_at"], NOW.isoformat())

    def test_status_and_errors_are_persisted_into_the_run_entry(self) -> None:
        # A failed run must leave a durable record here, not just console
        # output that scrolls away once the Actions log closes.
        errors = [{"phase": "hypothesis_gen", "context": "(preflight key validation)", "message": "401 rejected"}]
        result = _FakeResult(enabled=True, status="error", errors=errors, hypotheses_generated=0)
        state = record_run(result, self.path, now=NOW)

        self.assertEqual(state["runs"][0]["status"], "error")
        self.assertEqual(state["runs"][0]["errors"], errors)

    def test_clean_run_persists_empty_errors_list(self) -> None:
        result = _FakeResult(enabled=True, status="clean", hypotheses_generated=0)
        state = record_run(result, self.path, now=NOW)

        self.assertEqual(state["runs"][0]["status"], "clean")
        self.assertEqual(state["runs"][0]["errors"], [])

    def test_cumulative_accumulates_across_multiple_runs(self) -> None:
        record_run(_FakeResult(enabled=True, hypotheses_generated=3, survived=1, died=1), self.path, now=NOW)
        state = record_run(_FakeResult(enabled=True, hypotheses_generated=2, survived=1, died=1), self.path, now=NOW)

        self.assertEqual(state["cumulative"]["hypotheses_generated"], 5)
        self.assertEqual(state["cumulative"]["survived"], 2)
        self.assertEqual(state["cumulative"]["tested"], 4)
        self.assertEqual(len(state["runs"]), 2)

    def test_skipped_hypotheses_excluded_from_survival_rate_denominator(self) -> None:
        # 10 TOO_SLOW rejections, 1 tested-and-survived -- survival_rate should be
        # 1/1, NOT 1/11 -- SKIPPED hypotheses never had a chance to survive or die.
        result = _FakeResult(enabled=True, too_slow_rejected=10, survived=1)
        state = record_run(result, self.path, now=NOW)

        self.assertEqual(state["cumulative"]["tested"], 1)
        self.assertAlmostEqual(state["cumulative"]["survival_rate"], 1.0)

    def test_zero_tested_hypotheses_yields_null_survival_rate_not_zero(self) -> None:
        result = _FakeResult(enabled=True, too_slow_rejected=3)
        state = record_run(result, self.path, now=NOW)
        self.assertEqual(state["cumulative"]["tested"], 0)
        self.assertIsNone(state["cumulative"]["survival_rate"])

    def test_load_missing_file_returns_a_well_formed_empty_state(self) -> None:
        state = load_performance(self.tmp / "does_not_exist.json")
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["runs"], [])
        for key in ("hypotheses_generated", "survived", "died", "tested"):
            self.assertEqual(state["cumulative"][key], 0)


if __name__ == "__main__":
    unittest.main()
