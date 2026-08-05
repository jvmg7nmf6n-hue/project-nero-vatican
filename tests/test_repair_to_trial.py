"""CC-1 Factory Loop directive, item 5: REPAIR -> TRIAL.

Covers: a resolved SURVIVED/PROMISING-WATCHLIST repair attempt produces a
TrialRecord with full lineage (origin="repaired", repair_chain_id,
attempt_id); a DIED attempt does NOT (item 5d routes it to the Graveyard
instead, via load_died_repair_records); missing structured fields on the
launch event are handled honestly, not guessed; and the narrowed
no-auto-wire boundary (item 5c) -- repair_to_trial.py still never touches
live_scheduler/default_registry, and nothing calls it automatically."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent import graveyard_distillation, repair_lab, repair_to_trial, trial
from tests.test_research_agent_no_auto_wire import RESEARCH_AGENT_DIR, _forbidden_references

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)

MODIFIED_STRUCTURED_ENTRY = {"conditions": [{"field": "close", "op": "lt", "compare_to_field": "bb_lower"}]}
MODIFIED_STRUCTURED_EXIT = {"stop_atr_multiple": 2.0, "target_r_multiple": 2.0, "max_holding_hours": 48}


def _chain_events(chain_id: str, attempt_id: str, status: str, *, include_structured_fields: bool = True, origin_agent: str = "adam") -> list[dict]:
    launch_event = {
        "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": chain_id, "attempt_id": attempt_id,
        "fresh_data_method": "historical_reservation", "launched_at": NOW.isoformat(),
        "origin_agent": origin_agent,
    }
    if include_structured_fields:
        launch_event["structured_entry_rule"] = MODIFIED_STRUCTURED_ENTRY
        launch_event["structured_exit_plan"] = MODIFIED_STRUCTURED_EXIT

    events = [
        {"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": chain_id, "original_hypothesis_name": "ORIGINAL_HYP", "opened_at": NOW.isoformat()},
        launch_event,
    ]
    if status is not None:
        events.append({
            "event": repair_lab.EVENT_ATTEMPT_RESOLVED, "repair_chain_id": chain_id, "attempt_id": attempt_id,
            "status": status, "result": {"p_value_oos": 0.03, "measured_trades_per_year": 12.0}, "resolved_at": NOW.isoformat(),
        })
    return events


class AdmitRepairToTrialTest(unittest.TestCase):
    def test_survived_attempt_produces_trial_record_with_repair_lineage(self) -> None:
        events = _chain_events("RC-1", "A1", repair_lab.ATTEMPT_SURVIVED)
        result = repair_to_trial.admit_repair_to_trial("RC-1", "A1", events, origin_agent="adam", now=NOW)

        self.assertTrue(result.admitted, result.reason)
        ref = result.trial_record.source_hypothesis_ref
        self.assertEqual(ref["origin"], "repaired")
        self.assertEqual(ref["repair_chain_id"], "RC-1")
        self.assertEqual(ref["attempt_id"], "A1")
        self.assertEqual(result.trial_record.entry_verdict["verdict"], repair_lab.ATTEMPT_SURVIVED)

    def test_promising_watchlist_attempt_is_also_admitted(self) -> None:
        events = _chain_events("RC-2", "A1", repair_lab.ATTEMPT_PROMISING_WATCHLIST)
        result = repair_to_trial.admit_repair_to_trial("RC-2", "A1", events, origin_agent="adam", now=NOW)
        self.assertTrue(result.admitted)

    def test_died_attempt_is_not_admitted(self) -> None:
        events = _chain_events("RC-3", "A1", repair_lab.ATTEMPT_DIED)
        result = repair_to_trial.admit_repair_to_trial("RC-3", "A1", events, origin_agent="adam", now=NOW)
        self.assertFalse(result.admitted)
        self.assertIsNone(result.trial_record)
        self.assertIn("Graveyard", result.reason)

    def test_still_open_attempt_is_not_admitted(self) -> None:
        events = _chain_events("RC-4", "A1", status=None)
        result = repair_to_trial.admit_repair_to_trial("RC-4", "A1", events, origin_agent="adam", now=NOW)
        self.assertFalse(result.admitted)

    def test_unknown_attempt_id_is_not_admitted(self) -> None:
        events = _chain_events("RC-5", "A1", repair_lab.ATTEMPT_SURVIVED)
        result = repair_to_trial.admit_repair_to_trial("RC-5", "NONEXISTENT", events, origin_agent="adam", now=NOW)
        self.assertFalse(result.admitted)
        self.assertIn("not found", result.reason)

    def test_missing_structured_fields_reports_honestly_not_a_crash(self) -> None:
        events = _chain_events("RC-6", "A1", repair_lab.ATTEMPT_SURVIVED, include_structured_fields=False)
        result = repair_to_trial.admit_repair_to_trial("RC-6", "A1", events, origin_agent="adam", now=NOW)
        self.assertFalse(result.admitted)
        self.assertIn("structured_entry_rule", result.reason)

    def test_lineage_is_traceable_back_to_original_died_ancestor(self) -> None:
        events = _chain_events("RC-7", "A1", repair_lab.ATTEMPT_SURVIVED)
        result = repair_to_trial.admit_repair_to_trial("RC-7", "A1", events, origin_agent="adam", now=NOW)
        self.assertTrue(result.admitted)

        repair_chain_id = result.trial_record.source_hypothesis_ref["repair_chain_id"]
        state = repair_lab.reconstruct_chain_state(repair_chain_id, events)
        self.assertEqual(state["original_hypothesis_name"], "ORIGINAL_HYP")


class LoadDiedRepairRecordsTest(unittest.TestCase):
    def test_died_attempt_appears_with_origin_chain_populated(self) -> None:
        events = _chain_events("RC-8", "A1", repair_lab.ATTEMPT_DIED)
        died = graveyard_distillation.load_died_repair_records(events=events, failure_patterns=[])
        self.assertEqual(len(died), 1)
        self.assertEqual(died[0].origin_chain, {"repair_chain_id": "RC-8", "attempt_id": "A1"})

    def test_survived_attempt_never_appears_in_died_records(self) -> None:
        events = _chain_events("RC-9", "A1", repair_lab.ATTEMPT_SURVIVED)
        died = graveyard_distillation.load_died_repair_records(events=events, failure_patterns=[])
        self.assertEqual(died, [])

    def test_two_died_attempts_in_the_same_chain_are_both_recorded_distinctly(self) -> None:
        # A "re-death" scenario -- attempt 1 DIED, a second repair attempt
        # on the SAME chain also DIED. Both must be individually visible,
        # each with its own attempt_id in origin_chain, not collapsed.
        events = _chain_events("RC-10", "A1", repair_lab.ATTEMPT_DIED)
        events += [
            {"event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": "RC-10", "attempt_id": "A2",
             "fresh_data_method": "historical_reservation", "launched_at": NOW.isoformat(),
             "structured_entry_rule": MODIFIED_STRUCTURED_ENTRY, "structured_exit_plan": MODIFIED_STRUCTURED_EXIT},
            {"event": repair_lab.EVENT_ATTEMPT_RESOLVED, "repair_chain_id": "RC-10", "attempt_id": "A2",
             "status": repair_lab.ATTEMPT_DIED, "result": {}, "resolved_at": NOW.isoformat()},
        ]
        died = graveyard_distillation.load_died_repair_records(events=events, failure_patterns=[])
        self.assertEqual(len(died), 2)
        attempt_ids = {d.origin_chain["attempt_id"] for d in died}
        self.assertEqual(attempt_ids, {"A1", "A2"})

    def test_empty_events_returns_empty_list(self) -> None:
        self.assertEqual(graveyard_distillation.load_died_repair_records(events=[], failure_patterns=[]), [])


class RepairToTrialNoAutoWireTest(unittest.TestCase):
    """Item 5c: repair_to_trial.py still never touches live_scheduler/
    default_registry (same static check every other Repair Lab file gets),
    and nothing outside tests/human-invoked contexts calls it automatically."""

    def test_repair_to_trial_file_has_zero_forbidden_references(self) -> None:
        path = RESEARCH_AGENT_DIR / "repair_to_trial.py"
        self.assertTrue(path.exists())
        hits = _forbidden_references(path)
        self.assertEqual(hits, [], f"repair_to_trial.py references live_scheduler/default_registry: {hits}")

    def test_no_workflow_or_scheduler_file_invokes_repair_to_trial_automatically(self) -> None:
        # The narrower boundary (item 5c): repair_to_trial must never be
        # auto-invoked by a scheduled workflow or nero_core/execution/'s own
        # live-running code -- a human (or a human-triggered manual script)
        # is the only allowed caller. Grep-based, not exhaustive static
        # analysis, but catches the exact failure mode (a workflow YAML or
        # live_scheduler.py accidentally importing/calling this module).
        # NON-COMMENT lines only: research_agent_manual.yml's own item 9c
        # comment legitimately explains, in prose, that nothing calls
        # admit_repair_to_trial automatically -- that prose mentioning the
        # function name is not itself an invocation, and must not trip this
        # check (both .py and .yml use '#' for comments).
        def _non_comment_lines(text: str) -> list[str]:
            return [line for line in text.splitlines() if not line.strip().startswith("#")]

        repo_root = RESEARCH_AGENT_DIR.parents[1]
        offenders = []
        execution_dir = repo_root / "nero_core" / "execution"
        for path in execution_dir.glob("*.py"):
            if any("repair_to_trial" in line for line in _non_comment_lines(path.read_text(encoding="utf-8"))):
                offenders.append(str(path))
        workflows_dir = repo_root / ".github" / "workflows"
        for path in workflows_dir.glob("*.yml"):
            if any("repair_to_trial" in line for line in _non_comment_lines(path.read_text(encoding="utf-8"))):
                offenders.append(str(path))
        self.assertEqual(offenders, [], f"repair_to_trial referenced outside human-invoked contexts: {offenders}")


if __name__ == "__main__":
    unittest.main()
