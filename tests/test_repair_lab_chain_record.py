"""Repair Lab v1, Task 6: the append-only chain record. Every test uses its
own tempfile path (never docs/site_data/repair_attempts.json itself)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nero_core.research_agent.repair_lab import (
    ATTEMPT_DIED,
    ATTEMPT_LAUNCHED,
    ATTEMPT_PENDING_FORWARD_DATA,
    ATTEMPT_SURVIVED,
    CHAIN_OPEN,
    CHAIN_PERMANENTLY_DIED,
    CHAIN_RESOLVED,
    EVENT_ATTEMPT_LAUNCHED,
    EVENT_ATTEMPT_RESOLVED,
    EVENT_ATTEMPT_STATUS_CHANGED,
    EVENT_CHAIN_CLOSED,
    EVENT_CHAIN_OPENED,
    EVENT_PROPOSAL_REJECTED,
    MAX_ATTEMPTS_PER_CHAIN,
    append_repair_event,
    load_repair_events,
    reconstruct_chain_state,
)

CHAIN_ID = "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H-001"


class AppendAndLoadTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "repair_attempts.json"
        self.addCleanup(self._tmp.cleanup)

    def test_append_then_load_round_trips(self) -> None:
        append_repair_event({"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "opened_at": "t0"}, path=self.path)
        events = load_repair_events(path=self.path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], EVENT_CHAIN_OPENED)

    def test_append_is_additive_never_overwrites_prior_events(self) -> None:
        append_repair_event({"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "opened_at": "t0"}, path=self.path)
        append_repair_event({"event": EVENT_PROPOSAL_REJECTED, "repair_chain_id": CHAIN_ID, "reason": "x"}, path=self.path)
        events = load_repair_events(path=self.path)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], EVENT_CHAIN_OPENED)
        self.assertEqual(events[1]["event"], EVENT_PROPOSAL_REJECTED)

    def test_loading_a_missing_file_returns_empty_not_an_error(self) -> None:
        self.assertEqual(load_repair_events(path=self.path), [])


class ChainReconstructionTest(unittest.TestCase):
    def test_chain_opened_alone_reconstructs_to_open_with_no_attempts(self) -> None:
        events = [{"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "original_failure_type": "DIED", "opened_at": "t0"}]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["original_hypothesis_name"], "H")
        self.assertEqual(state["chain_status"], CHAIN_OPEN)
        self.assertEqual(state["attempts"], [])
        self.assertEqual(state["attempts_launched"], 0)
        self.assertEqual(state["attempts_remaining"], MAX_ATTEMPTS_PER_CHAIN)

    def test_rejected_proposals_are_recorded_but_never_counted_as_launched(self) -> None:
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "opened_at": "t0"},
            {"event": EVENT_PROPOSAL_REJECTED, "repair_chain_id": CHAIN_ID, "reason": "rejected: out of boundary", "rejected_at": "t1"},
            {"event": EVENT_PROPOSAL_REJECTED, "repair_chain_id": CHAIN_ID, "reason": "rejected: in-chain duplicate", "rejected_at": "t2"},
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(len(state["rejected_proposals"]), 2)
        self.assertEqual(state["attempts_launched"], 0)
        self.assertEqual(state["attempts_remaining"], MAX_ATTEMPTS_PER_CHAIN)

    def test_a_historical_reservation_attempt_starts_launched_then_resolves(self) -> None:
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "opened_at": "t0"},
            {
                "event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": CHAIN_ID, "attempt_id": "A1", "attempt_number": 1,
                "fresh_data_method": "historical_reservation", "fresh_data_snapshot_ref": "sha256:abc",
                "launched_at": "t1",
            },
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["attempts"][0]["status"], ATTEMPT_LAUNCHED)
        self.assertEqual(state["attempts_launched"], 1)

        events.append({"event": EVENT_ATTEMPT_RESOLVED, "repair_chain_id": CHAIN_ID, "attempt_id": "A1", "status": ATTEMPT_DIED, "result_ref": "docs/site_data/agent_test_results.json#A1", "resolved_at": "t2"})
        state_2 = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state_2["attempts"][0]["status"], ATTEMPT_DIED)
        self.assertEqual(state_2["attempts"][0]["result_ref"], "docs/site_data/agent_test_results.json#A1")

    def test_a_forward_testing_attempt_starts_pending_not_launched(self) -> None:
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "opened_at": "t0"},
            {
                "event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": CHAIN_ID, "attempt_id": "A2", "attempt_number": 2,
                "fresh_data_method": "forward_testing", "fresh_data_snapshot_ref": "forward-tracking started t1",
                "launched_at": "t1",
            },
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["attempts"][0]["status"], ATTEMPT_PENDING_FORWARD_DATA)

    def test_pending_forward_data_is_never_the_same_value_as_any_resolved_status(self) -> None:
        # Structural proof this can never be mistaken for a resolved verdict
        # anywhere the chain is read.
        self.assertNotIn(ATTEMPT_PENDING_FORWARD_DATA, (ATTEMPT_DIED, ATTEMPT_SURVIVED, "PROMISING-WATCHLIST", ATTEMPT_LAUNCHED))

    def test_status_changed_events_update_pending_attempts_progress_without_resolving(self) -> None:
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "opened_at": "t0"},
            {"event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": CHAIN_ID, "attempt_id": "A1", "fresh_data_method": "forward_testing", "launched_at": "t1"},
            {"event": EVENT_ATTEMPT_STATUS_CHANGED, "repair_chain_id": CHAIN_ID, "attempt_id": "A1", "status": ATTEMPT_PENDING_FORWARD_DATA, "trades_accrued_so_far": 7, "as_of": "t2"},
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["attempts"][0]["status"], ATTEMPT_PENDING_FORWARD_DATA)
        self.assertEqual(state["attempts"][0]["trades_accrued_so_far"], 7)

    def test_lineage_is_structural_attempt_3_always_comes_with_attempts_1_and_2(self) -> None:
        events = [{"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "opened_at": "t0"}]
        for i in range(1, 4):
            events.append({
                "event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": CHAIN_ID, "attempt_id": f"A{i}",
                "fresh_data_method": "historical_reservation", "launched_at": f"t{i}",
            })
            status = "DIED" if i < 3 else "PROMISING-WATCHLIST"
            events.append({"event": EVENT_ATTEMPT_RESOLVED, "repair_chain_id": CHAIN_ID, "attempt_id": f"A{i}", "status": status, "resolved_at": f"t{i}b"})

        state = reconstruct_chain_state(CHAIN_ID, events)
        # There is no function that returns "just attempt 3" -- reading the
        # chain always yields the full, ordered attempts list.
        self.assertEqual([a["attempt_id"] for a in state["attempts"]], ["A1", "A2", "A3"])
        self.assertEqual(state["attempts"][0]["status"], "DIED")
        self.assertEqual(state["attempts"][1]["status"], "DIED")
        self.assertEqual(state["attempts"][2]["status"], "PROMISING-WATCHLIST")
        self.assertEqual(state["original_hypothesis_name"], "H")  # always present alongside any attempt
        self.assertEqual(state["chain_status"], CHAIN_RESOLVED)

    def test_chain_reaches_permanently_died_derived_from_4_died_attempts_with_no_explicit_close_event(self) -> None:
        events = [{"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "opened_at": "t0"}]
        for i in range(1, MAX_ATTEMPTS_PER_CHAIN + 1):
            events.append({"event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": CHAIN_ID, "attempt_id": f"A{i}", "fresh_data_method": "historical_reservation", "launched_at": f"t{i}"})
            events.append({"event": EVENT_ATTEMPT_RESOLVED, "repair_chain_id": CHAIN_ID, "attempt_id": f"A{i}", "status": "DIED", "resolved_at": f"t{i}b"})
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["chain_status"], CHAIN_PERMANENTLY_DIED)
        self.assertEqual(state["attempts_remaining"], 0)

    def test_explicit_chain_closed_event_is_recorded_and_respected(self) -> None:
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "opened_at": "t0"},
            {"event": EVENT_CHAIN_CLOSED, "repair_chain_id": CHAIN_ID, "chain_status": CHAIN_PERMANENTLY_DIED, "attempts_used": 4, "closed_at": "t99"},
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["chain_status"], CHAIN_PERMANENTLY_DIED)
        self.assertEqual(state["closed_at"], "t99")

    def test_events_from_a_different_chain_never_leak_in(self) -> None:
        other_chain = "RC-SOME_OTHER_HYPOTHESIS-001"
        events = [
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": CHAIN_ID, "original_hypothesis_name": "H", "opened_at": "t0"},
            {"event": EVENT_CHAIN_OPENED, "repair_chain_id": other_chain, "original_hypothesis_name": "OTHER", "opened_at": "t0"},
            {"event": EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": other_chain, "attempt_id": "OTHER-A1", "fresh_data_method": "historical_reservation", "launched_at": "t1"},
        ]
        state = reconstruct_chain_state(CHAIN_ID, events)
        self.assertEqual(state["original_hypothesis_name"], "H")
        self.assertEqual(state["attempts"], [])


if __name__ == "__main__":
    unittest.main()
