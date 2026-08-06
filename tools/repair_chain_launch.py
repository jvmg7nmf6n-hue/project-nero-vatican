"""CC-1 directive, item 2: the missing link between "eligible" and "a
repair chain exists."

**The real gap, confirmed from code (item 2a):** every atomic piece Repair
Lab v1 needs is real, tested, and built --
`nero_core.research_agent.repair_lab.check_eligibility`,
`propose_modification`, `validate_modification`, `check_in_chain_duplicate`,
`can_launch_new_attempt`, `append_repair_event`, plus the two fresh-data
mechanisms (`repair_historical_reservation.reserve_historical_segment`,
`repair_forward_tracker.evaluate_forward_tick`) -- confirmed by
`tests/test_repair_lab_no_auto_wire.py::test_a_full_repair_lab_flow_never_
changes_the_strategy_registry`, which assembles ALL of them, in the
correct order, end to end, inside a TEST. That test is proof the pieces
compose correctly -- it is not, and was never meant to be, a production
entry point. Confirmed by direct search: zero non-test files anywhere in
this codebase call `append_repair_event` with `EVENT_ATTEMPT_LAUNCHED`
before this file. This module is that missing orchestration, nothing more
-- no new mechanism, no new write path.

**Deliberately split at the one real-money boundary:**
1. PROPOSE (a real LLM call, real money) -- already built and unchanged:
   `tools/operator_panel/app.py`'s own `/api/repair/propose`
   (`repair_lab.propose_modification` + `validate_modification`). This
   module does NOT duplicate that call -- every function below takes an
   ALREADY-OBTAINED `proposal` dict as input.
2. COMMIT (this module's own new piece, zero additional LLM cost) --
   re-validates, checks the in-chain duplicate, checks the real 4-attempt
   cap (`repair_lab.MAX_ATTEMPTS_PER_CHAIN`, confirmed currently 4 --
   the directive's own "MAX_REPAIR_ATTEMPTS" name does not exist in this
   codebase, see the closing report's own stale-figures section),
   allocates fresh data, and writes the chain-open + attempt-launched
   events via the real, existing `repair_lab.append_repair_event`.

**Fresh-data default: `forward_testing`, not `historical_reservation`.**
Confirmed from `reconstruct_chain_state`'s own logic
(`nero_core/research_agent/repair_lab.py`): an `EVENT_ATTEMPT_LAUNCHED`
event with `fresh_data_method="forward_testing"` starts the attempt at
`ATTEMPT_PENDING_FORWARD_DATA` -- no candle fetch is required AT LAUNCH
TIME at all (the first real tick happens later, exactly like a Trial
record's own `run_forward_tick`, currently NOT wired for repair attempts
-- see this module's own `main()` docstring on what happens next).
`historical_reservation` is supported but requires the caller to supply
real historical candles up front (`reserve_historical_segment` needs the
full candle history plus every prior attempt's own reserved segment in
this chain) -- deliberately not the default, to keep launching itself a
zero-extra-data-dependency operation.

**DELIBERATELY NOT AUTO-WIRED**: nothing here is called by any scheduler,
pipeline entrypoint, or the Factory Loop runner -- matches
`repair_to_trial.py`'s own precedent. See
`tests/test_repair_chain_launch_no_auto_wire.py`.

Run with (from the repo root):
    python -m tools.repair_chain_launch   # prints get_candidate_status() for every real candidate, no write, no flags
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent import repair_lab
from nero_core.research_agent.hypothesis_gen import DEFAULT_HYPOTHESES_PATH
from nero_core.research_agent.repair_historical_reservation import reserve_historical_segment
from nero_core.research_agent.storage import read_json_list

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"

FRESH_DATA_FORWARD_TESTING = "forward_testing"
FRESH_DATA_HISTORICAL_RESERVATION = "historical_reservation"


def get_repair_chain_id(original_hypothesis_name: str) -> str:
    """One chain per original hypothesis, for its whole repair lifecycle
    (up to MAX_ATTEMPTS_PER_CHAIN launches) -- deterministic, not a UUID,
    so a second call for the same hypothesis always finds the same chain
    rather than accidentally opening a parallel one."""
    return f"RC-{original_hypothesis_name}"


@dataclass(frozen=True)
class LaunchPrecondition:
    can_launch: bool
    reason: str
    chain_id: str
    is_new_chain: bool
    attempts_launched: int


def check_launch_preconditions(
    original_hypothesis_name: str,
    original_result: dict,
    original_hypothesis: dict,
    proposal: dict,
    repair_candidates: list[dict],
    repair_events: list[dict],
) -> LaunchPrecondition:
    """Every real, existing gate, in order -- pure, no write, safe to call
    from a dry-run or a UI preview. Returns can_launch=False with the exact
    reason the moment any gate fails; never partially evaluates further
    gates once one has already failed (matches this project's own
    fail-fast, one-clear-reason discipline elsewhere)."""
    chain_id = get_repair_chain_id(original_hypothesis_name)
    chain_state = repair_lab.reconstruct_chain_state(chain_id, repair_events)
    is_new_chain = chain_state["opened_at"] is None
    attempts = chain_state["attempts"]

    eligibility = repair_lab.check_eligibility(original_result)
    if not eligibility.eligible:
        return LaunchPrecondition(False, eligibility.reason, chain_id, is_new_chain, len(attempts))

    can_launch, cap_reason = repair_lab.can_launch_new_attempt(attempts)
    if not can_launch:
        return LaunchPrecondition(False, cap_reason, chain_id, is_new_chain, len(attempts))

    validation = repair_lab.validate_modification(original_hypothesis, proposal, repair_candidates)
    if not validation.approved:
        return LaunchPrecondition(False, validation.reason, chain_id, is_new_chain, len(attempts))

    duplicate = repair_lab.check_in_chain_duplicate(proposal, original_hypothesis, attempts)
    if duplicate.is_duplicate:
        return LaunchPrecondition(False, duplicate.reason, chain_id, is_new_chain, len(attempts))

    return LaunchPrecondition(True, "eligible: DSL-valid proposal, cap not reached, no in-chain duplicate", chain_id, is_new_chain, len(attempts))


@dataclass(frozen=True)
class LaunchResult:
    launched: bool
    reason: str
    chain_id: str
    attempt_id: str | None


def commit_repair_launch(
    original_hypothesis_name: str,
    original_result: dict,
    original_hypothesis: dict,
    proposal: dict,
    repair_candidates: list[dict],
    *,
    origin_agent: str,
    original_failure_type: str = "DIED",
    original_result_ref: str | None = None,
    fresh_data_method: str = FRESH_DATA_FORWARD_TESTING,
    historical_candles=None,
    now: datetime | None = None,
    events_path: Path = repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH,
) -> LaunchResult:
    """THE new piece (item 2c): commits an actual repair chain launch
    through existing repair_lab functions only -- `append_repair_event` is
    the ONLY write in this function, called once for `EVENT_CHAIN_OPENED`
    (only when this is genuinely the first attempt for this hypothesis)
    and once for `EVENT_ATTEMPT_LAUNCHED`. Re-runs every precondition via
    check_launch_preconditions first and refuses to write anything if any
    gate fails -- never trusts a caller's own earlier eligibility check
    without re-verifying against the CURRENT chain state (a second launch
    could have landed between the caller's preview and this call).

    Provenance (item 2c's own requirement): the launch event itself carries
    `origin_agent` and the modified `structured_entry_rule`/
    `structured_exit_plan` -- `repair_to_trial.admit_repair_to_trial`
    already reads exactly these fields off a launch event (confirmed from
    its own docstring/source) to build a Trial record's lineage, so a
    launch produced here is traceable through the SAME existing mechanism
    every other repaired-origin Trial admission already uses -- no new
    provenance path either."""
    now = now or datetime.now(timezone.utc)
    events = read_json_list(events_path)
    pre = check_launch_preconditions(original_hypothesis_name, original_result, original_hypothesis, proposal, repair_candidates, events)
    if not pre.can_launch:
        return LaunchResult(False, pre.reason, pre.chain_id, None)

    if fresh_data_method == FRESH_DATA_HISTORICAL_RESERVATION:
        if historical_candles is None:
            return LaunchResult(False, "fresh_data_method=historical_reservation requires historical_candles -- none supplied", pre.chain_id, None)
        already_consumed = [
            (a["fresh_data_reserved_start_ms"], a["fresh_data_reserved_end_ms"])
            for a in repair_lab.reconstruct_chain_state(pre.chain_id, events)["attempts"]
            if a.get("fresh_data_reserved_start_ms") is not None
        ]
        segment = reserve_historical_segment(historical_candles, already_consumed)
        if segment is None:
            return LaunchResult(False, "no disjoint historical segment of adequate size remains for this chain", pre.chain_id, None)
        fresh_data_extra = {
            "fresh_data_snapshot_ref": segment.content_hash,
            "fresh_data_reserved_start_ms": segment.start_close_time_ms,
            "fresh_data_reserved_end_ms": segment.end_close_time_ms,
        }
    elif fresh_data_method == FRESH_DATA_FORWARD_TESTING:
        # No candle fetch here, deliberately -- see this module's own
        # docstring: forward_testing starts PENDING_FORWARD_DATA, ticked
        # forward later, exactly like a Trial record.
        fresh_data_extra = {"fresh_data_snapshot_ref": f"forward-tracking started {now.isoformat()}"}
    else:
        return LaunchResult(False, f"unknown fresh_data_method={fresh_data_method!r}", pre.chain_id, None)

    attempt_id = f"A{pre.attempts_launched + 1}"

    if pre.is_new_chain:
        repair_lab.append_repair_event(
            {
                "event": repair_lab.EVENT_CHAIN_OPENED,
                "repair_chain_id": pre.chain_id,
                "original_hypothesis_name": original_hypothesis_name,
                "original_failure_type": original_failure_type,
                "original_result_ref": original_result_ref,
                "opened_at": now.isoformat(),
            },
            path=events_path,
        )

    repair_lab.append_repair_event(
        {
            "event": repair_lab.EVENT_ATTEMPT_LAUNCHED,
            "repair_chain_id": pre.chain_id,
            "attempt_id": attempt_id,
            "origin_agent": origin_agent,
            "fresh_data_method": fresh_data_method,
            "structured_entry_rule": proposal.get("structured_entry_rule"),
            "structured_entry_rule_short": proposal.get("structured_entry_rule_short"),
            "structured_exit_plan": proposal.get("structured_exit_plan"),
            "modification_type": proposal.get("modification_type"),
            "launched_at": now.isoformat(),
            **fresh_data_extra,
        },
        path=events_path,
    )
    return LaunchResult(True, f"launched attempt {attempt_id} in chain {pre.chain_id}", pre.chain_id, attempt_id)


def get_candidate_status() -> list[dict]:
    """Read-only report (item 2a/2b's own 'dry-run' surface): every real
    repair_candidates.json entry with its real, live-computed eligibility
    and cap status -- same computation the Operator Panel's own
    /api/repair/candidates already exposes, reinlined here so the CLI
    doesn't need the panel running."""
    candidates = repair_lab.load_repair_candidates()
    events = read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    hypotheses_by_name = {h.get("hypothesis_name"): h for h in read_json_list(DEFAULT_HYPOTHESES_PATH) if h.get("hypothesis_name")}
    results_by_name = {r.get("hypothesis_name"): r for r in read_json_list(AGENT_TEST_RESULTS_PATH) if r.get("hypothesis_name")}
    out = []
    for c in candidates:
        parent = c.get("parent_strategy")
        chain_id = get_repair_chain_id(c.get("hypothesis_name", ""))
        attempts = repair_lab.reconstruct_chain_state(chain_id, events)["attempts"]
        can_launch, cap_reason = repair_lab.can_launch_new_attempt(attempts)
        original_hypothesis = hypotheses_by_name.get(parent)
        original_result = results_by_name.get(parent)
        out.append({
            **c,
            "chain_id": chain_id,
            "attempts_launched": len(attempts),
            "can_launch_new_attempt": can_launch,
            "cap_reason": cap_reason,
            "original_data_available": original_hypothesis is not None and original_result is not None,
        })
    return out


def main() -> None:
    """CLI surface today is report-only, deliberately (item 2e: this
    directive builds the mechanism and proves it with tests, but leaves
    the actual first launch for the owner to trigger explicitly -- via the
    Operator Panel's own confirm-gated button, see tools/operator_panel/
    app.py, not a bare CLI flag with no confirmation step)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    for c in get_candidate_status():
        print(f"{c['hypothesis_name']} (parent: {c['parent_strategy']}) -- chain {c['chain_id']}: "
              f"{c['attempts_launched']} launched, can_launch_new_attempt={c['can_launch_new_attempt']} ({c['cap_reason']})")
        if not c["original_data_available"]:
            print(f"  NOTE: original hypothesis/result data for parent_strategy={c['parent_strategy']!r} not found in "
                  f"agent_hypotheses.json/agent_test_results.json -- this candidate's own repair_lab.check_eligibility "
                  f"cannot be evaluated from these files (its parent may be an internally-authored strategy, not an "
                  f"Adam/Eve hypothesis). A real launch for this candidate needs its original data sourced some other way.")


if __name__ == "__main__":
    main()
