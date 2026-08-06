"""CC-1 directive, item 2e: proves tools/repair_chain_launch.py's real
orchestration works end to end WITHOUT any real LLM/network call -- every
test uses a hand-crafted proposal, mirroring tests/test_repair_lab_no_
auto_wire.py's own reference flow (eligibility -> validate -> in-chain-dup
-> cap -> fresh-data allocation -> chain-record append), the only place in
this codebase that assembled these pieces before this file existed."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent import repair_lab
from tools import repair_chain_launch as launcher

NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)

ORIGINAL_HYPOTHESIS = {
    "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 25.0},
        ],
    },
    "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.04},
}
ORIGINAL_RESULT = {"verdict": "DIED", "reason": "train/test both negative expectancy"}
VALID_PROPOSAL = {
    "modification_type": "entry_threshold",
    "structured_entry_rule": {
        "conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 20.0},
        ],
    },
    "structured_entry_rule_short": None,
    "structured_exit_plan": ORIGINAL_HYPOTHESIS["structured_exit_plan"],
    "asset": "ETH", "timeframe": "4h",
}


class CheckLaunchPreconditionsTest(unittest.TestCase):
    def test_eligible_fresh_chain_can_launch(self) -> None:
        pre = launcher.check_launch_preconditions(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [], [],
        )
        self.assertTrue(pre.can_launch)
        self.assertTrue(pre.is_new_chain)
        self.assertEqual(pre.attempts_launched, 0)
        self.assertEqual(pre.chain_id, "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H")

    def test_non_died_verdict_is_never_eligible(self) -> None:
        pre = launcher.check_launch_preconditions(
            "X", {"verdict": "SURVIVED"}, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [], [],
        )
        self.assertFalse(pre.can_launch)
        self.assertIn("SURVIVED", pre.reason)

    def test_cap_reached_blocks_launch(self) -> None:
        chain_id = "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H"
        events = [{"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": chain_id, "original_hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "opened_at": NOW.isoformat()}]
        for i in range(1, 5):
            events.append({
                "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": chain_id, "attempt_id": f"A{i}",
                "fresh_data_method": "forward_testing", "launched_at": NOW.isoformat(),
            })
        pre = launcher.check_launch_preconditions(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [], events,
        )
        self.assertFalse(pre.can_launch)
        self.assertIn("4/4", pre.reason)
        self.assertEqual(pre.attempts_launched, 4)

    def test_in_chain_duplicate_blocks_launch(self) -> None:
        duplicate_of_original = {**VALID_PROPOSAL, "structured_entry_rule": ORIGINAL_HYPOTHESIS["structured_entry_rule"]}
        pre = launcher.check_launch_preconditions(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, duplicate_of_original, [], [],
        )
        self.assertFalse(pre.can_launch)
        self.assertIn("byte-identical", pre.reason)

    def test_out_of_scope_modification_type_blocks_launch(self) -> None:
        bad_proposal = {**VALID_PROPOSAL, "modification_type": "not_a_real_type"}
        pre = launcher.check_launch_preconditions(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, bad_proposal, [], [],
        )
        self.assertFalse(pre.can_launch)


class CommitRepairLaunchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.events_path = self.tmp / "repair_attempts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_launch_writes_chain_opened_and_attempt_launched_via_append_repair_event_only(self) -> None:
        result = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", now=NOW, events_path=self.events_path,
        )
        self.assertTrue(result.launched)
        self.assertEqual(result.attempt_id, "A1")

        events = repair_lab.load_repair_events(path=self.events_path)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], repair_lab.EVENT_CHAIN_OPENED)
        self.assertEqual(events[1]["event"], repair_lab.EVENT_ATTEMPT_LAUNCHED)
        self.assertEqual(events[1]["fresh_data_method"], "forward_testing")
        # Provenance (item 2c): the modified structured fields and
        # origin_agent must be on the launch event itself -- the exact
        # fields repair_to_trial.admit_repair_to_trial reads.
        self.assertEqual(events[1]["structured_entry_rule"], VALID_PROPOSAL["structured_entry_rule"])
        self.assertEqual(events[1]["structured_exit_plan"], VALID_PROPOSAL["structured_exit_plan"])
        self.assertEqual(events[1]["origin_agent"], "adam")

        state = repair_lab.reconstruct_chain_state("RC-EXT_WISE_MAN_HOLD_V5_ETH_4H", events)
        self.assertEqual(state["attempts"][0]["status"], repair_lab.ATTEMPT_PENDING_FORWARD_DATA)

    def test_second_attempt_in_same_chain_does_not_reopen_the_chain(self) -> None:
        first = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", now=NOW, events_path=self.events_path,
        )
        self.assertTrue(first.launched)

        different_proposal = {**VALID_PROPOSAL, "structured_entry_rule": {"conditions": [
            {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
            {"field": "adx14", "op": "lt", "value": 15.0},
        ]}}
        second = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, different_proposal, [],
            origin_agent="adam", now=NOW, events_path=self.events_path,
        )
        self.assertTrue(second.launched)
        self.assertEqual(second.attempt_id, "A2")

        events = repair_lab.load_repair_events(path=self.events_path)
        chain_opened_events = [e for e in events if e["event"] == repair_lab.EVENT_CHAIN_OPENED]
        self.assertEqual(len(chain_opened_events), 1, "a second attempt in the same chain must never re-open it")

    def test_refuses_to_write_anything_when_ineligible(self) -> None:
        result = launcher.commit_repair_launch(
            "X", {"verdict": "SURVIVED"}, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", now=NOW, events_path=self.events_path,
        )
        self.assertFalse(result.launched)
        self.assertFalse(self.events_path.exists(), "an ineligible launch must write nothing at all")

    def test_refuses_to_write_when_cap_reached_even_if_caller_did_not_check_first(self) -> None:
        # Simulates a caller that trusted a stale precondition check --
        # commit_repair_launch must re-verify against the CURRENT file
        # state, never trust the caller.
        chain_id = "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H"
        events = [{"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": chain_id, "original_hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "opened_at": NOW.isoformat()}]
        for i in range(1, 5):
            events.append({
                "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": chain_id, "attempt_id": f"A{i}",
                "fresh_data_method": "forward_testing", "launched_at": NOW.isoformat(),
            })
        self.events_path.write_text(__import__("json").dumps(events), encoding="utf-8")

        result = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", now=NOW, events_path=self.events_path,
        )
        self.assertFalse(result.launched)
        events_after = repair_lab.load_repair_events(path=self.events_path)
        self.assertEqual(len(events_after), 5, "must not append a 6th event past the cap")

    def test_historical_reservation_without_candles_refuses_not_crashes(self) -> None:
        result = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", fresh_data_method=launcher.FRESH_DATA_HISTORICAL_RESERVATION,
            now=NOW, events_path=self.events_path,
        )
        self.assertFalse(result.launched)
        self.assertIn("historical_candles", result.reason)

    def test_historical_reservation_with_real_candles_launches(self) -> None:
        import pandas as pd

        candles = pd.DataFrame([
            {"close_time": 1_700_000_000_000 + i * 14_400_000, "close": 100.0 + i * 0.01,
             "high": 100.5 + i * 0.01, "low": 99.5 + i * 0.01}
            for i in range(100)
        ])
        result = launcher.commit_repair_launch(
            "EXT_WISE_MAN_HOLD_V5_ETH_4H", ORIGINAL_RESULT, ORIGINAL_HYPOTHESIS, VALID_PROPOSAL, [],
            origin_agent="adam", fresh_data_method=launcher.FRESH_DATA_HISTORICAL_RESERVATION,
            historical_candles=candles, now=NOW, events_path=self.events_path,
        )
        self.assertTrue(result.launched)
        events = repair_lab.load_repair_events(path=self.events_path)
        launched_event = events[-1]
        self.assertEqual(launched_event["fresh_data_method"], "historical_reservation")
        self.assertIn("fresh_data_snapshot_ref", launched_event)
        state = repair_lab.reconstruct_chain_state("RC-EXT_WISE_MAN_HOLD_V5_ETH_4H", events)
        self.assertEqual(state["attempts"][0]["status"], repair_lab.ATTEMPT_LAUNCHED)


class GetCandidateStatusTest(unittest.TestCase):
    def test_real_repair_candidates_report_real_cap_status(self) -> None:
        # Real, current repo data -- confirms the CLI's own report mode
        # runs cleanly against the actual repair_candidates.json.
        candidates = launcher.get_candidate_status()
        self.assertGreaterEqual(len(candidates), 1)
        for c in candidates:
            self.assertIn("can_launch_new_attempt", c)
            self.assertIn("chain_id", c)


if __name__ == "__main__":
    unittest.main()
