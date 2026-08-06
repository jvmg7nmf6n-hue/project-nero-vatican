"""CC-1 directive, item 4: the Local Operator Panel.

LOCAL ONLY, NEVER DEPLOYED (see tests/test_operator_panel_no_public_bundle.py's
own hard guard, asserting website/ contains zero references to this
package). No authentication anywhere in this file -- there is nothing to
authenticate against: this runs on the owner's own machine, against the
owner's own local repo checkout, bound to 127.0.0.1 by default (see
`main()` below). This is the exact reasoning the directive's own item 3
report gave for recommending "no auth needed" -- restated here since this
file is what actually ships it.

EVERY WRITE GOES THROUGH AN EXISTING FUNCTION -- no new write path, no gate
bypass (per this directive's own explicit instruction). Each endpoint's own
docstring below names exactly which existing nero_core/tools function it
calls. The one deliberate exception, reported rather than silently built:
committing a NEW repair-chain launch (choosing a fresh-data mechanism and
calling repair_lab.append_repair_event with EVENT_ATTEMPT_LAUNCHED) has no
existing single entry point anywhere in this codebase to call through --
nothing has ever launched one in production (confirmed, prior directive's
own finding). Assembling that commit sequence for the first time inside
this panel would BE a new write path, which this directive explicitly says
to stop and report on rather than build. This file therefore implements
the repair-chain flow up through PROPOSING and VALIDATING a modification
(both real, existing, tested functions: repair_lab.propose_modification,
repair_lab.validate_modification) and stops there -- see /api/repair/propose's
own docstring.

Run with (from the repo root):
    pip install -r requirements.txt -r requirements-operator-panel.txt
    python -m uvicorn tools.operator_panel.app:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from nero_core.eve import config as eve_config
from nero_core.research_agent import graveyard_distillation, repair_lab, trial
from nero_core.research_agent.hypothesis_gen import DEFAULT_HYPOTHESES_PATH, DEFAULT_PARAMETERS
from nero_core.research_agent.storage import read_json_list, append_json_list
from tools import factory_loop_run, factory_loop_status_summary

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"

EVE_BUDGET_LEDGER_PATH = REPO_ROOT / "docs" / "site_data" / "eve_budget_ledger.json"
EVE_SESSION_REGISTRY_PATH = REPO_ROOT / "docs" / "site_data" / "eve_session_registry.json"
DISTILLATION_DRAFTS_PATH = factory_loop_run.DEFAULT_DISTILLATION_DRAFTS_PATH
AGENT_TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"

# Mirrors nero_core.eve.budget_ledger.MONTH_CEILING_USD/DEFAULT_SESSION_BUDGET_USD
# and eve_session_registry.json's own "~$14" pre-registration figure --
# reinlined as plain floats here (not imported), matching this project's own
# established "small constant, reinline rather than cross-import" precedent
# (see nero_core/eve/session.py's DSL vocabulary reinlines). This file is
# neither nero_core/eve/ nor nero_core/research_agent/ -- a tools/ script
# reading real budget numbers for DISPLAY only, never a decision input.
MONTH_CEILING_USD = 20.0
PRE_REGISTRATION_BUDGET_USD = 14.0
EVE_SESSION_CEILING_USD = 1.50

app = FastAPI(title="Vatican Operator Panel (local only)")

# Tracks currently-running subprocesses for the kill switch -- in-memory
# only, deliberately: this panel is a single local process, restarting it
# is itself a valid "everything is stopped" state.
_RUNNING: dict[str, subprocess.Popen] = {}
_RUNNING_LOCK = threading.Lock()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# Budget meter -- read-only, real numbers only (item 4's own requirement:
# spent, remaining, unknown-cost call count, the 6 orphaned reservations).
# ---------------------------------------------------------------------------


@app.get("/api/budget")
def get_budget() -> dict:
    """Real numbers from docs/site_data/eve_budget_ledger.json -- no writer,
    read-only. Matches the arithmetic in this directive's own Item 1a
    report exactly (same source file, same computation)."""
    entries = read_json_list(EVE_BUDGET_LEDGER_PATH)
    actual = [e for e in entries if e.get("status") == "actual"]
    reserved = [e for e in entries if e.get("status") == "reserved"]
    actual_total = sum(float(e.get("actual_cost_usd") or 0.0) for e in actual)
    reserved_total = sum(float(e.get("projected_cost_usd") or 0.0) for e in reserved)
    consumed = actual_total + reserved_total
    return {
        "eve_actual_spend_usd": round(actual_total, 6),
        "eve_orphaned_reservations": {
            "count": len(reserved),
            "total_usd": round(reserved_total, 6),
            "session_ids": [e.get("session_id") for e in reserved],
        },
        "pre_registration_budget_usd": PRE_REGISTRATION_BUDGET_USD,
        "pre_registration_remaining_usd": round(PRE_REGISTRATION_BUDGET_USD - consumed, 4),
        "month_ceiling_usd": MONTH_CEILING_USD,
        "month_ceiling_remaining_usd": round(MONTH_CEILING_USD - actual_total, 4),
        "eve_session_ceiling_usd": EVE_SESSION_CEILING_USD,
        # Real, confirmed gap (Item 1a): Adam's own per-run unknown-cost call
        # count is computed by nero_core.research_agent.pipeline.PipelineRunResult
        # but never persisted to agent_run_summaries.json -- reported honestly
        # as unavailable, never guessed.
        "adam_unknown_cost_calls": None,
        "adam_unknown_cost_calls_note": (
            "not recoverable from any committed file -- pipeline.py computes this "
            "per-run and prints it to console, but tools/research_agent_run_summary.py "
            "never persists it (confirmed gap, see this directive's own Item 1a report)"
        ),
    }


# ---------------------------------------------------------------------------
# Factory Loop -- dry-run first, explicit confirm for a real run. Every
# write goes through tools.factory_loop_run's own functions, unchanged.
# ---------------------------------------------------------------------------


@app.post("/api/factory-loop/dry-run")
def factory_loop_dry_run() -> dict:
    """Calls the exact same pure functions tools/factory_loop_run.py's own
    main() calls in dry-run mode -- no write, this endpoint cannot write
    anything (there is no `live=True` path reachable from here)."""
    now = datetime.now(timezone.utc)
    forward_trial_records = read_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH)
    repair_events = read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    failure_patterns = read_json_list(graveyard_distillation.DEFAULT_FAILURE_PATTERNS_PATH)

    candidates = factory_loop_run.load_adam_candidates() + factory_loop_run.load_eve_candidates()
    fresh_attempts = factory_loop_run.evaluate_fresh_admissions(candidates, forward_trial_records, now)
    repair_attempts = factory_loop_run.evaluate_repair_admissions(repair_events, forward_trial_records, now)
    distillation_ready = factory_loop_run.evaluate_distillation_candidates(failure_patterns, repair_events)
    tick_outcomes = factory_loop_run.advance_open_trials(forward_trial_records, now, live=False)

    report = factory_loop_run.build_report(fresh_attempts, repair_attempts, distillation_ready, tick_outcomes, live=False)
    return {
        "report_text": report,
        "would_admit": sum(1 for a in fresh_attempts if a.admitted) + sum(1 for a in repair_attempts if a.admitted),
        "distillation_ready_families": distillation_ready,
    }


class FactoryLoopLiveRequest(BaseModel):
    confirm: bool = False


@app.post("/api/factory-loop/live")
def factory_loop_live(body: FactoryLoopLiveRequest) -> dict:
    """The ONLY endpoint in this file that can admit/draft/tick/regenerate
    status for real -- requires confirm=true explicitly (mirrors
    tools/factory_loop_run.py's own --live flag; this calls the identical
    functions that script's main() does, in the identical order)."""
    if not body.confirm:
        raise HTTPException(400, "confirm=true required for a real (live) Factory Loop run")

    now = datetime.now(timezone.utc)
    forward_trial_records = read_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH)
    repair_events = read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    failure_patterns = read_json_list(graveyard_distillation.DEFAULT_FAILURE_PATTERNS_PATH)

    candidates = factory_loop_run.load_adam_candidates() + factory_loop_run.load_eve_candidates()
    fresh_attempts = factory_loop_run.evaluate_fresh_admissions(candidates, forward_trial_records, now)
    repair_attempts = factory_loop_run.evaluate_repair_admissions(repair_events, forward_trial_records, now)
    distillation_ready = factory_loop_run.evaluate_distillation_candidates(failure_patterns, repair_events)

    new_records = [a.trial_record for a in fresh_attempts if a.admitted] + [a.trial_record for a in repair_attempts if a.admitted]
    hypothesis_lookup = {c.hypothesis_name: c.hypothesis_record for c in candidates}
    tick_outcomes = factory_loop_run.advance_open_trials(
        forward_trial_records + new_records, now, live=True, hypothesis_lookup=hypothesis_lookup,
    )
    report = factory_loop_run.build_report(fresh_attempts, repair_attempts, distillation_ready, tick_outcomes, live=True)

    if new_records:
        append_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH, new_records)

    draft_note = None
    if distillation_ready:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key.strip():
            draft_note = "ANTHROPIC_API_KEY not set -- no drafting call made, no cost incurred"
        else:
            try:
                distillation_result = factory_loop_run.draft_ready_distillations(failure_patterns, repair_events, api_key)
                factory_loop_run.persist_distillation_drafts(distillation_result.drafts)
                draft_note = (
                    f"{len(distillation_result.drafts)} draft(s) written at review_status=pending_human_approval "
                    f"-- real cost ${distillation_result.total_cost_usd:.6f}"
                )
                if distillation_result.errors:
                    draft_note += f" -- errors: {'; '.join(distillation_result.errors)}"
            except graveyard_distillation.ApiKeyRejectedError as exc:
                draft_note = f"drafting failed: {exc}"

    final_forward_trial = read_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH)
    graveyard_entries = read_json_list(graveyard_distillation.DEFAULT_GRAVEYARD_PATH)
    distillation_drafts = read_json_list(DISTILLATION_DRAFTS_PATH)
    summary_data = factory_loop_status_summary.compute_summary_data(
        final_forward_trial, graveyard_entries, read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH), distillation_drafts,
    )
    factory_loop_status_summary.write_status(summary_data)

    return {"report_text": report, "new_records_written": len(new_records), "draft_note": draft_note, "status": summary_data}


# ---------------------------------------------------------------------------
# Approval queue -- every REVIEW_PENDING item, Approve/Reject writing the
# SAME review_status field a human would edit by hand. Approve calls the
# real, existing graveyard_distillation.commit_graveyard_entry -- the ONLY
# function in this codebase allowed to write graveyard.json/failure_
# patterns.json, and it already refuses (EntryNotApprovedError) anything
# still at review_status=pending_human_approval, so this endpoint cannot
# accidentally commit an unapproved draft even if it tried.
# ---------------------------------------------------------------------------


@app.get("/api/approval-queue")
def get_approval_queue() -> dict:
    drafts = read_json_list(DISTILLATION_DRAFTS_PATH)
    pending = [d for d in drafts if d.get("review_status") == graveyard_distillation.REVIEW_PENDING]
    return {"pending": pending, "count": len(pending)}


def _load_drafts() -> list[dict]:
    return read_json_list(DISTILLATION_DRAFTS_PATH)


def _write_drafts(drafts: list[dict]) -> None:
    DISTILLATION_DRAFTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISTILLATION_DRAFTS_PATH.write_text(json.dumps(drafts, indent=2) + "\n", encoding="utf-8")


@app.post("/api/approval-queue/{name}/approve")
def approve_draft(name: str) -> dict:
    """Sets review_status the same way a human editing the JSON by hand
    would (REVIEW_PENDING -> "approved"), then calls graveyard_distillation.
    commit_graveyard_entry -- the real, existing, only-ever writer of
    graveyard.json/failure_patterns.json. No new write path."""
    drafts = _load_drafts()
    entry = next((d for d in drafts if d.get("name") == name), None)
    if entry is None:
        raise HTTPException(404, f"no draft named {name!r} in the approval queue")
    entry["review_status"] = "approved"
    entry["approved_at"] = datetime.now(timezone.utc).isoformat()
    _write_drafts(drafts)
    try:
        result = graveyard_distillation.commit_graveyard_entry(entry)
    except graveyard_distillation.EntryNotApprovedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"committed": True, **result}


@app.post("/api/approval-queue/{name}/reject")
def reject_draft(name: str) -> dict:
    """Sets review_status to "rejected" (the same field a human would edit
    by hand) -- never calls commit_graveyard_entry, so a rejected draft can
    never reach graveyard.json/failure_patterns.json."""
    drafts = _load_drafts()
    entry = next((d for d in drafts if d.get("name") == name), None)
    if entry is None:
        raise HTTPException(404, f"no draft named {name!r} in the approval queue")
    entry["review_status"] = "rejected"
    entry["rejected_at"] = datetime.now(timezone.utc).isoformat()
    _write_drafts(drafts)
    return {"rejected": True, "name": name}


# ---------------------------------------------------------------------------
# Repair chain -- candidates + real eligibility/cap status (read-only), and
# a propose-and-validate step using the real, existing repair_lab functions.
# Does NOT launch (commit) a chain -- see module docstring for why.
# ---------------------------------------------------------------------------


@app.get("/api/repair/candidates")
def get_repair_candidates() -> dict:
    candidates = repair_lab.load_repair_candidates()
    repair_events = read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    out = []
    for c in candidates:
        chain_id = c.get("hypothesis_name")  # one candidate == one chain, by this project's own convention
        state = repair_lab.reconstruct_chain_state(chain_id, repair_events) if repair_events else None
        attempts = state["attempts"] if state else []
        can_launch, cap_reason = repair_lab.can_launch_new_attempt(attempts)
        out.append({**c, "attempts_launched": len(attempts), "can_launch_new_attempt": can_launch, "cap_reason": cap_reason})
    return {"candidates": out}


class ProposeRepairRequest(BaseModel):
    hypothesis_name: str


@app.post("/api/repair/propose")
def propose_repair(body: ProposeRepairRequest) -> dict:
    """Item 4's own explicit scope boundary (see module docstring): calls
    the real repair_lab.propose_modification (ONE real LLM call -- this IS
    real spend, the owner must click knowing that) and repair_lab.
    validate_modification -- both existing, tested functions -- and returns
    the proposal for human review. Does NOT call repair_lab.append_repair_event
    or launch anything -- that commit step has no existing single entry
    point in this codebase to call through, and assembling one for the
    first time here would be a new write path, which this directive says to
    report rather than build."""
    candidates = repair_lab.load_repair_candidates()
    candidate = next((c for c in candidates if c.get("hypothesis_name") == body.hypothesis_name), None)
    if candidate is None:
        raise HTTPException(404, f"{body.hypothesis_name!r} is not a known repair candidate")

    hypotheses_by_name = {h.get("hypothesis_name"): h for h in read_json_list(DEFAULT_HYPOTHESES_PATH) if h.get("hypothesis_name")}
    results_by_name = {r.get("hypothesis_name"): r for r in read_json_list(AGENT_TEST_RESULTS_PATH) if r.get("hypothesis_name")}
    parent_name = candidate.get("parent_strategy")
    original_hypothesis = hypotheses_by_name.get(parent_name)
    original_result = results_by_name.get(parent_name)
    if original_hypothesis is None or original_result is None:
        raise HTTPException(
            422,
            f"original hypothesis/result data for parent_strategy={parent_name!r} not found in "
            f"agent_hypotheses.json/agent_test_results.json -- cannot propose a modification without it "
            f"(this candidate's parent may be an internally-authored strategy, not an Adam/Eve hypothesis)",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key.strip():
        raise HTTPException(400, "ANTHROPIC_API_KEY not set -- no call made, no cost incurred")

    eligibility = repair_lab.check_eligibility(original_result)
    if not eligibility.eligible:
        raise HTTPException(409, eligibility.reason)

    result = repair_lab.propose_modification(original_hypothesis, original_result, candidates, api_key)
    if result.error:
        raise HTTPException(502, result.error)

    validation = repair_lab.validate_modification(original_hypothesis, result.proposal, candidates)
    return {
        "proposal": result.proposal,
        "cost_usd": result.cost_usd,
        "validation_approved": validation.approved,
        "validation_reason": validation.reason,
        "note": "PROPOSED AND VALIDATED ONLY -- this panel does not launch/commit a repair chain (see /api/repair/propose's own docstring)",
    }


# ---------------------------------------------------------------------------
# Run Adam / Run Eve -- live-streamed subprocess output, kill switch.
# ---------------------------------------------------------------------------


def _stream_subprocess(cmd: list[str], env: dict, run_id: str):
    process = subprocess.Popen(
        cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    with _RUNNING_LOCK:
        _RUNNING[run_id] = process
    try:
        yield f"event: started\ndata: {json.dumps({'run_id': run_id, 'pid': process.pid})}\n\n"
        for line in iter(process.stdout.readline, ""):
            yield f"event: line\ndata: {json.dumps({'text': line.rstrip()})}\n\n"
        process.wait()
        yield f"event: done\ndata: {json.dumps({'returncode': process.returncode})}\n\n"
    finally:
        with _RUNNING_LOCK:
            _RUNNING.pop(run_id, None)


@app.post("/api/adam/run")
def run_adam() -> StreamingResponse:
    """Triggers `python -m nero_core.research_agent.pipeline` -- the exact
    same entrypoint .github/workflows/research_agent_manual.yml's
    workflow_dispatch calls, run locally instead. RESEARCH_AGENT_ENABLED=true
    is set ONLY for this one subprocess's own environment (mirrors the
    workflow's own inline-env pattern) -- this click IS the "deliberate,
    watched click" the pipeline's own kill switch exists to require, not a
    bypass of it."""
    run_id = str(uuid.uuid4())
    env = dict(os.environ)
    env["RESEARCH_AGENT_ENABLED"] = "true"
    return StreamingResponse(
        _stream_subprocess([sys.executable, "-m", "nero_core.research_agent.pipeline"], env, run_id),
        media_type="text/event-stream",
    )


@app.get("/api/eve/preflight")
def eve_preflight() -> dict:
    """Item 4's own requirement: show the budget ceiling BEFORE confirming.
    Real numbers, same source as /api/budget."""
    budget = get_budget()
    return {
        "session_ceiling_usd": EVE_SESSION_CEILING_USD,
        "pre_registration_remaining_usd": budget["pre_registration_remaining_usd"],
        "eve_enabled": eve_config.is_enabled(),
    }


class EveRunRequest(BaseModel):
    confirm: bool = False


@app.post("/api/eve/run")
def run_eve(body: EveRunRequest) -> StreamingResponse:
    """Triggers `python -m nero_core.eve.pipeline` -- requires confirm=true
    (the UI must show /api/eve/preflight's real ceiling first). EVE_ENABLED=true
    set ONLY for this one subprocess -- see run_adam's own docstring for why
    this is the deliberate click the kill switch requires, not a bypass."""
    if not body.confirm:
        raise HTTPException(400, "confirm=true required -- show /api/eve/preflight's budget ceiling first")
    run_id = str(uuid.uuid4())
    env = dict(os.environ)
    env["EVE_ENABLED"] = "true"
    return StreamingResponse(
        _stream_subprocess([sys.executable, "-m", "nero_core.eve.pipeline"], env, run_id),
        media_type="text/event-stream",
    )


@app.get("/api/runs")
def list_runs() -> dict:
    with _RUNNING_LOCK:
        return {"running": [{"run_id": rid, "pid": p.pid} for rid, p in _RUNNING.items()]}


@app.post("/api/kill/{run_id}")
def kill_run(run_id: str) -> dict:
    """The kill switch: terminates the tracked subprocess for run_id. Does
    NOT touch any file -- a killed Adam/Eve run's own budget-ledger
    reservation is left exactly where nero_core.eve.budget_ledger's own
    RESERVE-THEN-RECONCILE design already handles it (an orphaned
    reservation, conservatively counted, never silently freed)."""
    with _RUNNING_LOCK:
        process = _RUNNING.get(run_id)
    if process is None:
        raise HTTPException(404, f"no running process for run_id={run_id!r}")
    process.terminate()
    return {"killed": run_id, "pid": process.pid}


if __name__ == "__main__":
    # Bound to 127.0.0.1, not 0.0.0.0, IN CODE -- not just in the module
    # docstring's documented command -- so running this file directly can
    # never accidentally listen on a network-reachable interface.
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
