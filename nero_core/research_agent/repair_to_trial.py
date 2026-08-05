"""CC-1 Factory Loop directive, item 5: REPAIR -> TRIAL.

Repair Lab v1 (nero_core.research_agent.repair_lab) is fully built and
fully tested, but was entirely unwired -- nothing ever turned a resolved
SURVIVED/PROMISING-WATCHLIST repair attempt into anything downstream (see
docs/investigations/factory_loop_specification.md's own B3/0b). This module
is that wiring, and it is its OWN admission path, deliberately NOT a reuse
of nero_core.research_agent.trial.admit_to_trial's DSL/freshness gate: a
repair attempt has already passed a stricter, repair-specific admission
sequence before ever being launched (check_eligibility, validate_
modification, check_in_chain_duplicate, can_launch_new_attempt, one of the
two "genuinely fresh data" mechanisms) -- reusing item 4's mechanism
wholesale would either lose that enforcement (no 4-attempt cap, no
in-chain-duplicate check) or require bolting it on awkwardly (spec B3).

Both paths converge on the SAME TrialRecord shape (nero_core.research_agent.
trial.TrialRecord), via trial.admit_to_trial itself -- called here with
origin="repaired" so source_hypothesis_ref carries the full repair_chain_id/
attempt_id lineage. A repaired hypothesis in Trial is always traceable back
to its original DIED ancestor via reconstruct_chain_state, unchanged.

DELIBERATELY NOT AUTO-WIRED (item 5c): this module provides a function a
HUMAN (or a human-invoked script) calls after inspecting a resolved chain --
nothing here is called by any scheduler or pipeline entrypoint. See
tests/test_repair_to_trial.py's own no-auto-wire assertions, extending
tests/test_repair_lab_no_auto_wire.py's existing static check to this new
file."""
from __future__ import annotations

from datetime import datetime

from nero_core.research_agent import repair_lab, trial
from nero_core.research_agent.repair_lab import (
    ATTEMPT_DIED,
    ATTEMPT_PROMISING_WATCHLIST,
    ATTEMPT_SURVIVED,
)


def _measured_trades_per_year_from_result(result: dict | None) -> float | None:
    """Defensive, never crashes on a missing/differently-shaped result --
    historical-reservation and forward-tracking resolutions (repair_
    historical_reservation.py / repair_forward_tracker.compute_forward_
    verdict) do not currently carry a measured_trades_per_year field the
    way auto_tester.TestResult does; this degrades to None (item 4a's own
    UNMEASURABLE labeling) honestly rather than guessing one."""
    if not isinstance(result, dict):
        return None
    value = result.get("measured_trades_per_year")
    return float(value) if isinstance(value, (int, float)) else None


def _p_value_oos_from_result(result: dict | None) -> float | None:
    if not isinstance(result, dict):
        return None
    value = result.get("p_value_oos")
    return float(value) if isinstance(value, (int, float)) else None


def admit_repair_to_trial(
    repair_chain_id: str,
    attempt_id: str,
    events: list[dict],
    *,
    origin_agent: str,
    now: datetime | None = None,
) -> trial.AdmissionResult:
    """The real gate here (distinct from item 4e's DSL/freshness gate): the
    named attempt must exist in this chain and have RESOLVED to SURVIVED or
    PROMISING-WATCHLIST -- a still-OPEN, PENDING_FORWARD_DATA, or DIED
    attempt is never admitted (item 5d: a DIED repair stays in the
    Graveyard instead, via nero_core.research_agent.graveyard_distillation's
    load_died_repair_records).

    A launch event for `attempt_id` MUST have carried the modified
    hypothesis's own structured_entry_rule/structured_exit_plan (reconstruct_
    chain_state preserves every field on a launch event unmodified) --
    without them, this returns a clear not-admitted reason rather than
    crashing or guessing a DSL-validity verdict from nothing."""
    state = repair_lab.reconstruct_chain_state(repair_chain_id, events)
    attempt = next((a for a in state["attempts"] if str(a.get("attempt_id")) == str(attempt_id)), None)
    if attempt is None:
        return trial.AdmissionResult(None, False, f"attempt {attempt_id!r} not found in chain {repair_chain_id!r}")

    status = attempt.get("status")
    if status not in (ATTEMPT_SURVIVED, ATTEMPT_PROMISING_WATCHLIST):
        return trial.AdmissionResult(
            None, False,
            f"attempt {attempt_id!r} has status={status!r}, not SURVIVED/PROMISING-WATCHLIST -- not admitted "
            f"to Trial (item 5d: a DIED repair stays in the Graveyard instead)",
        )

    hypothesis_record = {
        "structured_entry_rule": attempt.get("structured_entry_rule"),
        "structured_exit_plan": attempt.get("structured_exit_plan"),
    }
    if hypothesis_record["structured_entry_rule"] is None and hypothesis_record["structured_exit_plan"] is None:
        return trial.AdmissionResult(
            None, False,
            f"attempt {attempt_id!r}'s launch event carries no structured_entry_rule/structured_exit_plan -- "
            f"cannot evaluate DSL-validity; the caller launching a repair attempt must include the modified "
            f"hypothesis's structured fields on its EVENT_ATTEMPT_LAUNCHED event",
        )

    result = attempt.get("result") if isinstance(attempt.get("result"), dict) else None
    entry_verdict = {
        "verdict": status,
        "p_value_oos": _p_value_oos_from_result(result),
        "review_status": "pending_human_approval",
    }
    hypothesis_name = f"{state['original_hypothesis_name']}__REPAIR_{attempt_id}"

    return trial.admit_to_trial(
        hypothesis_record, entry_verdict,
        origin=trial.ORIGIN_REPAIRED, origin_agent=origin_agent,
        hypothesis_name=hypothesis_name, session_id_or_run_ref=state.get("original_result_ref"),
        measured_trades_per_year=_measured_trades_per_year_from_result(result),
        repair_chain_id=repair_chain_id, attempt_id=attempt_id, now=now,
    )
