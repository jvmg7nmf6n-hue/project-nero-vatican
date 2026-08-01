"""Repair Lab v1, Task 5: the 4-attempt cap counts LAUNCHES, not
resolutions, and PERMANENTLY_DIED is an explicit, never-silent terminal
state."""
from __future__ import annotations

import unittest

from nero_core.research_agent.repair_lab import (
    ATTEMPT_DIED,
    ATTEMPT_PENDING_FORWARD_DATA,
    ATTEMPT_PROMISING_WATCHLIST,
    ATTEMPT_SURVIVED,
    CHAIN_PERMANENTLY_DIED,
    CHAIN_RESOLVED,
    MAX_ATTEMPTS_PER_CHAIN,
    can_launch_new_attempt,
    count_launched_attempts,
    evaluate_chain_terminal_state,
)


def _attempt(attempt_id: str, status: str) -> dict:
    return {"attempt_id": attempt_id, "status": status}


class AttemptCapCountingTest(unittest.TestCase):
    def test_empty_chain_counts_zero(self) -> None:
        self.assertEqual(count_launched_attempts([]), 0)

    def test_pending_attempts_count_toward_launched_same_as_resolved(self) -> None:
        attempts = [
            _attempt("A1", ATTEMPT_DIED),
            _attempt("A2", ATTEMPT_PENDING_FORWARD_DATA),
            _attempt("A3", ATTEMPT_PENDING_FORWARD_DATA),
        ]
        self.assertEqual(count_launched_attempts(attempts), 3)

    def test_can_launch_when_under_cap(self) -> None:
        attempts = [_attempt("A1", ATTEMPT_DIED)]
        allowed, reason = can_launch_new_attempt(attempts)
        self.assertTrue(allowed)
        self.assertIn("1/4", reason)

    def test_cannot_launch_a_5th_when_4_already_launched_all_died(self) -> None:
        attempts = [_attempt(f"A{i}", ATTEMPT_DIED) for i in range(1, MAX_ATTEMPTS_PER_CHAIN + 1)]
        allowed, reason = can_launch_new_attempt(attempts)
        self.assertFalse(allowed)
        self.assertIn("rejected", reason)
        self.assertIn(f"{MAX_ATTEMPTS_PER_CHAIN}/{MAX_ATTEMPTS_PER_CHAIN}", reason)

    def test_cannot_launch_a_5th_when_some_attempts_are_still_pending_forward_data(self) -> None:
        # THE exact edge case the task calls out explicitly: 2 DIED + 2
        # PENDING_FORWARD_DATA -- cap is fully used regardless of resolution.
        attempts = [
            _attempt("A1", ATTEMPT_DIED), _attempt("A2", ATTEMPT_DIED),
            _attempt("A3", ATTEMPT_PENDING_FORWARD_DATA), _attempt("A4", ATTEMPT_PENDING_FORWARD_DATA),
        ]
        allowed, reason = can_launch_new_attempt(attempts)
        self.assertFalse(allowed)
        self.assertIn("PENDING_FORWARD_DATA attempt counts toward the cap", reason)

    def test_cannot_launch_a_5th_when_all_4_are_still_pending_forward_data(self) -> None:
        attempts = [_attempt(f"A{i}", ATTEMPT_PENDING_FORWARD_DATA) for i in range(1, MAX_ATTEMPTS_PER_CHAIN + 1)]
        allowed, _ = can_launch_new_attempt(attempts)
        self.assertFalse(allowed)


class ChainTerminalStateTest(unittest.TestCase):
    def test_chain_stays_open_below_the_cap(self) -> None:
        attempts = [_attempt("A1", ATTEMPT_DIED), _attempt("A2", ATTEMPT_DIED)]
        self.assertIsNone(evaluate_chain_terminal_state(attempts))

    def test_chain_stays_open_at_the_cap_if_any_attempt_is_still_pending(self) -> None:
        attempts = [_attempt(f"A{i}", ATTEMPT_DIED) for i in range(1, MAX_ATTEMPTS_PER_CHAIN)]
        attempts.append(_attempt("A4", ATTEMPT_PENDING_FORWARD_DATA))
        self.assertIsNone(evaluate_chain_terminal_state(attempts))

    def test_chain_is_permanently_died_when_the_cap_is_used_and_every_attempt_died(self) -> None:
        attempts = [_attempt(f"A{i}", ATTEMPT_DIED) for i in range(1, MAX_ATTEMPTS_PER_CHAIN + 1)]
        self.assertEqual(evaluate_chain_terminal_state(attempts), CHAIN_PERMANENTLY_DIED)

    def test_chain_is_resolved_the_instant_any_attempt_survives_even_before_the_cap(self) -> None:
        attempts = [_attempt("A1", ATTEMPT_DIED), _attempt("A2", ATTEMPT_SURVIVED)]
        self.assertEqual(evaluate_chain_terminal_state(attempts), CHAIN_RESOLVED)

    def test_chain_is_resolved_on_promising_watchlist_too(self) -> None:
        attempts = [_attempt("A1", ATTEMPT_DIED), _attempt("A2", ATTEMPT_PROMISING_WATCHLIST)]
        self.assertEqual(evaluate_chain_terminal_state(attempts), CHAIN_RESOLVED)

    def test_resolved_status_takes_priority_even_if_the_cap_was_also_reached(self) -> None:
        attempts = [_attempt(f"A{i}", ATTEMPT_DIED) for i in range(1, MAX_ATTEMPTS_PER_CHAIN)]
        attempts.append(_attempt("A4", ATTEMPT_SURVIVED))
        self.assertEqual(evaluate_chain_terminal_state(attempts), CHAIN_RESOLVED)


if __name__ == "__main__":
    unittest.main()
