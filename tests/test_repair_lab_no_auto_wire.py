"""Repair Lab v1, Task 7: architectural isolation. Extends test_research_
agent_no_auto_wire.py's own HARD TEST to explicitly cover Repair Lab's new
code paths -- proven, not assumed. Two independent checks, mirroring that
file's own structure exactly:

1. STATIC -- proves every new Repair Lab file actually lives where the
   EXISTING static test's glob (nero_core/research_agent/*.py) already
   scans, and that the existing check itself reports zero offenders for
   each one -- not inferred from "the glob is dynamic so it must work,"
   verified directly against the real function.
2. DYNAMIC -- runs a full, realistic Repair Lab flow (eligibility ->
   diagnosis boundary validation -> in-chain duplicate check -> historical
   reservation -> a forward-tracking tick -> chain record append/
   reconstruct -> cap check) end to end, LLM/network never called, and
   proves nero_core.strategies.registry.default_registry's variant count
   is completely unchanged -- exactly ORDERFLOW_IMBALANCE's own kind of
   experimental, forward-testing-only mechanism, but never auto-wired
   anywhere near the live scheduler or the registry, regardless of how
   many attempts SURVIVE (this module's own CRITICAL SAFETY guarantee)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.research_agent.repair_forward_tracker import evaluate_forward_tick
from nero_core.research_agent.repair_historical_reservation import reserve_historical_segment
from nero_core.research_agent.repair_lab import (
    ATTEMPT_LAUNCHED,
    EVENT_ATTEMPT_LAUNCHED,
    EVENT_CHAIN_OPENED,
    append_repair_event,
    can_launch_new_attempt,
    check_eligibility,
    check_in_chain_duplicate,
    load_repair_events,
    reconstruct_chain_state,
    validate_modification,
)
from nero_core.strategies.registry import default_registry
from tests.test_research_agent_no_auto_wire import RESEARCH_AGENT_DIR, _forbidden_references

# CC-1 directive item 5c (2026-08-05): trial.py/repair_to_trial.py added
# here, extending the SAME static check every original Repair Lab file
# already gets -- the narrowed boundary that survives item 5 is "repair_lab
# never auto-invokes itself" (still true, still checked below), NOT
# "nothing ever calls repair_lab" (repair_to_trial.admit_repair_to_trial now
# legitimately does, but only when a human/human-invoked script calls IT --
# see tests/test_repair_to_trial.py's own RepairToTrialNoAutoWireTest for
# the grep-based confirmation that no workflow/scheduler file references it).
NEW_REPAIR_LAB_FILES = (
    "repair_lab.py", "repair_forward_tracker.py", "repair_historical_reservation.py",
    "trial.py", "repair_to_trial.py",
)
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


class RepairLabStaticNoAutoWireTest(unittest.TestCase):
    def test_every_new_repair_lab_file_actually_lives_under_the_existing_static_glob(self) -> None:
        # NOT assumed: the existing static test's own glob is re-run here,
        # right now, and every new file's presence in its result is checked
        # directly -- if a future refactor ever moved one of these files out
        # of nero_core/research_agent/, this test (not just intuition about
        # "the glob is dynamic") would catch it.
        py_file_names = {p.name for p in RESEARCH_AGENT_DIR.glob("*.py")}
        for filename in NEW_REPAIR_LAB_FILES:
            with self.subTest(file=filename):
                self.assertIn(filename, py_file_names)

    def test_the_existing_static_check_function_reports_zero_offenders_for_every_new_file(self) -> None:
        for filename in NEW_REPAIR_LAB_FILES:
            path = RESEARCH_AGENT_DIR / filename
            with self.subTest(file=filename):
                self.assertTrue(path.exists())
                hits = _forbidden_references(path)
                self.assertEqual(hits, [], f"{filename} references live_scheduler/default_registry: {hits}")


class RepairLabDynamicNoAutoWireTest(unittest.TestCase):
    def test_a_full_repair_lab_flow_never_changes_the_strategy_registry(self) -> None:
        before_count = len(default_registry.all_variants())

        original_hypothesis = {
            "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
            "structured_entry_rule": {
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 25.0},
                ],
            },
            "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.04},
        }
        original_result = {
            "verdict": "DIED", "reason": "train: N=176 ExpR=-0.330; test: N=53 ExpR=-0.057 -> DIED",
            "train": {"trades": 176, "expectancy_r": -0.330, "bootstrap_ci": {"lower_2_5": -0.5, "upper_97_5": -0.1, "crosses_zero": False}},
            "test": {"trades": 53, "expectancy_r": -0.057, "bootstrap_ci": {"lower_2_5": -0.3, "upper_97_5": 0.2, "crosses_zero": True}},
        }

        # Task 1
        eligibility = check_eligibility(original_result)
        self.assertTrue(eligibility.eligible)

        # Task 2 (a hand-crafted, already-approved proposal -- no LLM/network call)
        proposal = {
            "modification_type": "entry_threshold",
            "structured_entry_rule": {
                "conditions": [
                    {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
                    {"field": "adx14", "op": "lt", "value": 20.0},
                ],
            },
            "structured_entry_rule_short": None,
            "structured_exit_plan": original_hypothesis["structured_exit_plan"],
            "asset": "ETH", "timeframe": "4h",
        }
        validation = validate_modification(original_hypothesis, proposal, [])
        self.assertTrue(validation.approved, validation.reason)

        # Task 3
        duplicate = check_in_chain_duplicate(proposal, original_hypothesis, [])
        self.assertFalse(duplicate.is_duplicate)

        # Task 4a
        candles = pd.DataFrame([
            {"close_time": 1_700_000_000_000 + i * 14_400_000, "close": 100.0 + i * 0.01,
             "high": 100.5 + i * 0.01, "low": 99.5 + i * 0.01}
            for i in range(100)
        ])
        segment = reserve_historical_segment(candles, [], min_candle_count=50)
        self.assertIsNotNone(segment)

        # Task 4b (own tempfile db -- never the production ledger)
        with tempfile.TemporaryDirectory() as tmp_dir:
            forward_db = Path(tmp_dir) / "forward.db"
            tick = evaluate_forward_tick(
                "no-auto-wire-test-attempt", proposal,
                pd.DataFrame([{"close_time": 1_700_000_000_000, "close": 100.0, "high": 100.0, "low": 100.0}]),
                NOW, db_path=forward_db,
            )
            self.assertIn(tick.signal_type, ("ENTRY", "NO_TRADE"))

            # Task 6
            chain_path = Path(tmp_dir) / "repair_attempts.json"
            chain_id = "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H-001"
            append_repair_event({"event": EVENT_CHAIN_OPENED, "repair_chain_id": chain_id, "original_hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "opened_at": NOW.isoformat()}, path=chain_path)
            append_repair_event({
                "event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": chain_id, "attempt_id": "A1",
                "fresh_data_method": "historical_reservation", "fresh_data_snapshot_ref": segment.content_hash,
                "launched_at": NOW.isoformat(),
            }, path=chain_path)
            events = load_repair_events(path=chain_path)
            state = reconstruct_chain_state(chain_id, events)
            self.assertEqual(state["attempts"][0]["status"], ATTEMPT_LAUNCHED)

            # Task 5
            can_launch, _ = can_launch_new_attempt(state["attempts"])
            self.assertTrue(can_launch)

        after_count = len(default_registry.all_variants())
        self.assertEqual(before_count, after_count, "Repair Lab must never register anything, regardless of any attempt's own result")


if __name__ == "__main__":
    unittest.main()
