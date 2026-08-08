"""CC-1 Master Directive Phase 2: the Factory Loop runner.

Every stage of the Factory Loop (nero_core.research_agent.trial.admit_to_trial,
nero_core.research_agent.repair_to_trial.admit_repair_to_trial,
nero_core.research_agent.graveyard_distillation, trial.run_forward_tick,
tools.factory_loop_status_summary) is built and tested, but nothing ever
CALLED any of them in sequence -- this is why factory_loop_status.json has
read Forward Trial 0 / Repair 0 since the day it was first written. This
script is that missing runner. It performs, in order:

  1. Read every hypothesis with a real verdict from Adam's stores
     (agent_test_results.json joined against agent_hypotheses.json by
     hypothesis_name) and Eve's store (eve_hypotheses.json, verdict_combined
     not None).
  2. Call admit_to_trial for each not already in forward_trial.json -- the
     gate is DSL-valid only (trial.admit_to_trial's own gate); a SKIPPED/
     TOO_SLOW verdict does NOT block admission, per this project's "measure,
     never gate" philosophy. See report_only_summary's own
     admissible_but_currently_skipped field for where this creates a real,
     surfaced tension with the frequency gate's upstream SKIP.
  3. Call admit_repair_to_trial for any repair attempt resolved to
     SURVIVED/PROMISING-WATCHLIST not already in forward_trial.json.
  4. Run graveyard_distillation's family-DIED-count trigger check. A family
     at or past DIED_COUNT_TRIGGER gets a drafted entry (an LLM call --
     this is the ONE step in this script that spends money on a --live run)
     at review_status=REVIEW_PENDING, persisted to
     docs/site_data/graveyard_distillation_drafts.json for human review --
     NEVER committed to graveyard.json/failure_patterns.json by this script
     (commit_graveyard_entry itself refuses a REVIEW_PENDING entry; nothing
     here calls commit_graveyard_entry at all).
  5. Advance every OPEN forward_trial.json record one forward tick
     (trial.run_forward_tick), fetching fresh closed candles via this
     project's own real, already-live fetch layer (tools.timeframe_data.
     fetch_timeframe_candles) -- never a synthetic substitute.
  6. Regenerate docs/site_data/factory_loop_status.json via
     tools.factory_loop_status_summary's own compute_summary_data/write_status
     (read-only aggregation over whatever steps 2-5 just wrote).

DRY-RUN IS THE DEFAULT (item 2b): with no flags, this script reports exactly
what WOULD be admitted/distilled/advanced and writes NOTHING -- not to
forward_trial.json, not to any drafts file, not to factory_loop_status.json.
Only `--live` performs the real writes (and, if any family is distillation-
ready, spends real money on one drafting call per family). Nothing at
REVIEW_PENDING is ever auto-approved by either mode (item 2d) -- that
remains a human editing review_status by hand, or a future Operator Panel
(Phase 3) writing through commit_graveyard_entry after a human clicks
Approve.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.research_agent import graveyard_distillation, repair_forward_tracker, repair_lab, repair_to_trial, trial
from nero_core.research_agent.hypothesis_gen import DEFAULT_HYPOTHESES_PATH, DEFAULT_PARAMETERS
from nero_core.research_agent.storage import append_json_list, read_json_list
from tools import factory_loop_status_summary as status_summary
from tools.timeframe_data import fetch_timeframe_candles

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"
DEFAULT_EVE_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"
DEFAULT_DISTILLATION_DRAFTS_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard_distillation_drafts.json"


@dataclass(frozen=True)
class TrialCandidate:
    """One hypothesis with a real verdict, normalized across Adam's and
    Eve's two different on-disk shapes into the fields admit_to_trial
    actually needs -- see module docstring step 1."""

    hypothesis_name: str
    origin_agent: str  # "adam" | "eve"
    hypothesis_record: dict
    entry_verdict: dict
    measured_trades_per_year: float | None
    session_id_or_run_ref: str | None


def load_adam_candidates(
    test_results_path: Path = DEFAULT_TEST_RESULTS_PATH, hypotheses_path: Path = DEFAULT_HYPOTHESES_PATH,
) -> list[TrialCandidate]:
    """Every Adam hypothesis with a real test result, regardless of verdict
    (SURVIVED/DIED/SKIPPED/PROMISING-WATCHLIST/UNTESTABLE_BY_DSL all count --
    item 2's own gate is DSL-validity, evaluated downstream by admit_to_trial
    itself, never pre-filtered here by verdict)."""
    hypotheses_by_name = {
        h["hypothesis_name"]: h for h in read_json_list(hypotheses_path)
        if isinstance(h, dict) and h.get("hypothesis_name")
    }
    candidates: list[TrialCandidate] = []
    for result in read_json_list(test_results_path):
        if not isinstance(result, dict):
            continue
        name = result.get("hypothesis_name")
        hyp = hypotheses_by_name.get(name)
        if hyp is None:
            continue  # no structured fields available -- cannot evaluate DSL-validity at all
        entry_verdict = {
            "verdict": result.get("verdict"),
            "review_status": result.get("review_status"),
            "frequency_classification": result.get("frequency_classification"),
            "reason": result.get("reason"),
        }
        candidates.append(TrialCandidate(
            hypothesis_name=name, origin_agent="adam", hypothesis_record=hyp, entry_verdict=entry_verdict,
            measured_trades_per_year=result.get("measured_trades_per_year"),
            session_id_or_run_ref=hyp.get("run_id"),
        ))
    return candidates


def load_eve_candidates(eve_hypotheses_path: Path = DEFAULT_EVE_HYPOTHESES_PATH) -> list[TrialCandidate]:
    """Every Eve hypothesis with a real combined verdict -- mirrors
    graveyard_distillation.load_died_records's own Eve-side field reads
    (raw_hypothesis.hypothesis_name, session_id), just not restricted to
    verdict_combined==DIED."""
    candidates: list[TrialCandidate] = []
    for record in read_json_list(eve_hypotheses_path):
        if not isinstance(record, dict) or record.get("verdict_combined") is None:
            continue
        raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
        name = str(raw.get("hypothesis_name", ""))
        if not name:
            continue
        entry_verdict = {
            "verdict": record.get("verdict_combined"),
            "verdict_is": record.get("verdict_is"),
            "verdict_oos": record.get("verdict_oos"),
            "frequency_classification": record.get("frequency_classification"),
        }
        candidates.append(TrialCandidate(
            hypothesis_name=name, origin_agent="eve", hypothesis_record=raw, entry_verdict=entry_verdict,
            measured_trades_per_year=record.get("measured_trades_per_year"),
            session_id_or_run_ref=record.get("session_id"),
        ))
    return candidates


@dataclass(frozen=True)
class AdmissionAttempt:
    candidate: TrialCandidate
    admitted: bool
    reason: str
    trial_record: dict | None


def already_admitted_names(forward_trial_records: list[dict]) -> set[str]:
    return {
        (r.get("source_hypothesis_ref") or {}).get("hypothesis_name")
        for r in forward_trial_records
        if isinstance(r, dict)
    }


def evaluate_fresh_admissions(
    candidates: list[TrialCandidate], forward_trial_records: list[dict], now: datetime,
) -> list[AdmissionAttempt]:
    """Item 2's step 2, pure -- decides what WOULD be admitted without
    writing anything, so both dry-run reporting and a real run share this
    one decision function (no duplicated admission logic between modes)."""
    already = already_admitted_names(forward_trial_records)
    attempts: list[AdmissionAttempt] = []
    for candidate in candidates:
        if candidate.hypothesis_name in already:
            attempts.append(AdmissionAttempt(candidate, False, "already admitted to Trial in an earlier run", None))
            continue
        result = trial.admit_to_trial(
            candidate.hypothesis_record, candidate.entry_verdict,
            origin=trial.ORIGIN_FRESH, origin_agent=candidate.origin_agent,
            hypothesis_name=candidate.hypothesis_name, session_id_or_run_ref=candidate.session_id_or_run_ref,
            measured_trades_per_year=candidate.measured_trades_per_year, now=now,
        )
        record_dict = result.trial_record.to_dict() if result.trial_record is not None else None
        attempts.append(AdmissionAttempt(candidate, result.admitted, result.reason, record_dict))
    return attempts


@dataclass(frozen=True)
class RepairAdmissionAttempt:
    repair_chain_id: str
    attempt_id: str
    admitted: bool
    reason: str
    trial_record: dict | None


def evaluate_repair_admissions(
    repair_events: list[dict], forward_trial_records: list[dict], now: datetime,
) -> list[RepairAdmissionAttempt]:
    """Item 2's step 3, pure. A repair attempt is a candidate once its chain
    reconstructs it as SURVIVED/PROMISING-WATCHLIST (repair_to_trial.
    admit_repair_to_trial's own gate) and it is not already in
    forward_trial.json (deduped by attempt_id, since two different repair
    chains could in principle share an unrelated hypothesis_name)."""
    already_attempt_ids = {
        (r.get("source_hypothesis_ref") or {}).get("attempt_id")
        for r in forward_trial_records
        if isinstance(r, dict) and (r.get("source_hypothesis_ref") or {}).get("origin") == trial.ORIGIN_REPAIRED
    }
    chain_ids = sorted({e.get("repair_chain_id") for e in repair_events if e.get("repair_chain_id")})
    attempts: list[RepairAdmissionAttempt] = []
    for chain_id in chain_ids:
        state = repair_lab.reconstruct_chain_state(chain_id, repair_events)
        for attempt in state["attempts"]:
            attempt_id = str(attempt.get("attempt_id"))
            if attempt.get("status") not in (repair_lab.ATTEMPT_SURVIVED, repair_lab.ATTEMPT_PROMISING_WATCHLIST):
                continue
            if attempt_id in already_attempt_ids:
                attempts.append(RepairAdmissionAttempt(chain_id, attempt_id, False, "already admitted to Trial in an earlier run", None))
                continue
            origin_agent = attempt.get("origin_agent") or "adam"
            result = repair_to_trial.admit_repair_to_trial(chain_id, attempt_id, repair_events, origin_agent=origin_agent, now=now)
            record_dict = result.trial_record.to_dict() if result.trial_record is not None else None
            attempts.append(RepairAdmissionAttempt(chain_id, attempt_id, result.admitted, result.reason, record_dict))
    return attempts


def evaluate_distillation_candidates(
    failure_patterns: list[dict], repair_events: list[dict],
) -> dict[str, int]:
    """Item 2's step 4, pure -- families at or past DIED_COUNT_TRIGGER,
    combining fresh-hypothesis deaths (load_died_records) and repair-attempt
    deaths (load_died_repair_records), exactly as graveyard_distillation's
    own module docstring specifies for item 6d's trigger."""
    died = graveyard_distillation.load_died_records(failure_patterns=failure_patterns)
    died += graveyard_distillation.load_died_repair_records(events=repair_events, failure_patterns=failure_patterns)
    ready = graveyard_distillation.find_families_ready_for_distillation(died)
    return {family: len(members) for family, members in ready.items()}


@dataclass(frozen=True)
class DistillationRunResult:
    drafts: list[dict]
    total_cost_usd: float
    errors: list[str]


def draft_ready_distillations(
    failure_patterns: list[dict], repair_events: list[dict], api_key: str,
) -> DistillationRunResult:
    """Item 2's step 4, the ONE part of a --live run that spends real money:
    one draft_distillation_entry call per family at or past the trigger.
    Returns the drafted entries (review_status=REVIEW_PENDING on every one)
    -- never commits them; see module docstring.

    REAL BUG FOUND AND FIXED, 2026-08-06 (first successful real distillation
    draft, after the API key fix): this used to return a bare `list[dict]`,
    silently discarding `DistillationDraftResult.cost_usd` on every call and
    `.error` entirely whenever `result.entry is None` (an LLM call that WAS
    billed but failed to parse, or returned a `failure_pattern` outside the
    closed vocabulary -- see draft_distillation_entry's own docstring) --
    real spend that would have vanished with no trace anywhere, and a real
    per-family failure that would have produced no drafts and no error,
    indistinguishable from "no family was ready" at the call site. Now
    returns cost and per-family errors explicitly so a caller can never
    silently lose either."""
    died = graveyard_distillation.load_died_records(failure_patterns=failure_patterns)
    died += graveyard_distillation.load_died_repair_records(events=repair_events, failure_patterns=failure_patterns)
    ready = graveyard_distillation.find_families_ready_for_distillation(died)
    drafts: list[dict] = []
    total_cost = 0.0
    errors: list[str] = []
    for family, members in ready.items():
        result = graveyard_distillation.draft_distillation_entry(family, members, api_key, DEFAULT_PARAMETERS)
        total_cost += result.cost_usd
        if result.entry is not None:
            drafts.append(result.entry)
        if result.error:
            errors.append(f"{family}: {result.error}")
    return DistillationRunResult(drafts=drafts, total_cost_usd=total_cost, errors=errors)


def persist_distillation_drafts(drafts: list[dict], path: Path = DEFAULT_DISTILLATION_DRAFTS_PATH) -> None:
    if drafts:
        append_json_list(path, drafts)


@dataclass(frozen=True)
class ForwardTickOutcome:
    trial_id: str
    hypothesis_name: str
    ticked: bool
    reason: str


def advance_open_trials(
    forward_trial_records: list[dict], now: datetime, live: bool, hypothesis_lookup: dict[str, dict] | None = None,
) -> list[ForwardTickOutcome]:
    """Item 2's step 5. Every OPEN record gets exactly one forward tick.
    Dry-run never fetches candles or writes anything -- it only reports how
    many OPEN records exist and what asset/timeframe each would tick
    against. A --live run fetches real, already-closed candles via this
    project's own live fetch layer (tools.timeframe_data.
    fetch_timeframe_candles) -- never a synthetic substitute -- logs the one
    tick (trial.run_forward_tick: ENTRY, EXIT, or NO_TRADE), then separately
    checks trial.compute_forward_verdict -- which stays None (per its own
    docstring) until 2*MIN_SAMPLE_SIZE trades have resolved -- and, only once
    it returns a real verdict, updates the Trial's status via
    trial.update_trial_status (SURVIVED_TRIAL/PROMISING-WATCHLIST both map to
    STATUS_SURVIVED_TRIAL; DIED maps to STATUS_FAILED_TRIAL).

    REAL BUG FOUND AND FIXED, 2026-08-06 (first --live run): a TrialRecord
    (nero_core.research_agent.trial.TrialRecord.to_dict()) never carries a
    "hypothesis" field -- only source_hypothesis_ref.hypothesis_name. The
    first live run's dry-run prediction ("8 OPEN records, ready to tick") was
    therefore wrong in a way dry-run mode itself could never catch (dry-run
    never touches this code path at all -- see the `if not live` branch
    below). Fixed by resolving each OPEN record's asset/timeframe/structured
    fields via `hypothesis_lookup` (built by the caller from the SAME
    Adam/Eve candidate sources load_adam_candidates/load_eve_candidates
    already read) keyed by hypothesis_name, rather than expecting the
    Trial record to carry its own copy.

    CC-1 DIRECTIVE FIX (2026-08-07, Part A): a repaired-origin record's real
    hypothesis_name carries a `"<original>__REPAIR_<attempt_id>"` suffix
    (`repair_to_trial.admit_repair_to_trial`'s own
    `f"{state['original_hypothesis_name']}__REPAIR_{attempt_id}"` construction)
    that never matches `hypothesis_lookup`'s keys, which are always raw,
    unsuffixed Adam/Eve candidate names. Fixed by detecting
    `source_hypothesis_ref["origin"] == trial.ORIGIN_REPAIRED` (set
    unconditionally by `trial.admit_to_trial` for every repaired record, the
    authoritative signal -- not a string-pattern guess) and looking up the
    ORIGINAL hypothesis name instead, recovered by splitting on the exact
    same `"__REPAIR_"` marker the admission path itself uses. This resolves
    correctly because both `load_adam_candidates`/`load_eve_candidates`
    read from append-only stores (`agent_hypotheses.json`/
    `eve_hypotheses.json`) that are never pruned when a hypothesis dies --
    the ancestor a repair is based on is always still present. This is the
    SAME `hypothesis_lookup` a fresh record already resolves through, no
    new resolution pathway.

    ONE REAL, NOT-YET-FIXED GAP, honestly scoped rather than silently
    covered: `tools/repair_chain_launch.py`'s own `EVENT_ATTEMPT_LAUNCHED`
    event never captures the modification's own `asset`/`timeframe` fields
    (only `structured_entry_rule`/`structured_exit_plan`/`modification_type`)
    -- for the common case (asset/timeframe unchanged from the original,
    required for every modification_type except `asset_timeframe_change`,
    per repair_lab.py's own `validate_modification`) this fallback to the
    ORIGINAL hypothesis's asset/timeframe is correct. For the rarer
    `asset_timeframe_change` case it would silently resolve to the WRONG
    (original, pre-change) asset/timeframe. Confirmed via real data
    (`docs/site_data/repair_attempts.json` does not exist -- zero repair
    attempts of any kind have ever been launched in production) that this
    edge case has zero real instances today; fixing it would require
    changing the launch event's own write schema, a separate, larger change
    than this directive's own "small, precise, no new resolution pathway"
    scope."""
    outcomes: list[ForwardTickOutcome] = []
    hypothesis_lookup = hypothesis_lookup or {}
    open_records = [r for r in forward_trial_records if r.get("status") == trial.STATUS_OPEN]
    if not live:
        for r in open_records:
            ref = r.get("source_hypothesis_ref") or {}
            outcomes.append(ForwardTickOutcome(r["trial_id"], ref.get("hypothesis_name", ""), False, "dry-run -- no candles fetched, no tick performed"))
        return outcomes

    client = MarketDataClient()
    for r in open_records:
        ref = r.get("source_hypothesis_ref") or {}
        name = ref.get("hypothesis_name", "")
        lookup_name = name
        if ref.get("origin") == trial.ORIGIN_REPAIRED and "__REPAIR_" in name:
            lookup_name = name.rsplit("__REPAIR_", 1)[0]
        hypothesis = hypothesis_lookup.get(lookup_name)
        asset, timeframe = (hypothesis or {}).get("asset"), (hypothesis or {}).get("timeframe")
        if not asset or not timeframe:
            outcomes.append(ForwardTickOutcome(
                r["trial_id"], name, False,
                f"no hypothesis record found for {lookup_name!r} (resolved from {name!r}) in the current "
                f"Adam/Eve candidate lookup -- cannot resolve asset/timeframe",
            ))
            continue
        try:
            candles, _method = fetch_timeframe_candles(client, asset, timeframe)
        except MarketDataUnavailableError as exc:
            outcomes.append(ForwardTickOutcome(r["trial_id"], name, False, f"candle fetch failed: {exc}"))
            continue
        tick_result = trial.run_forward_tick(r["trial_id"], hypothesis or {}, candles, now)
        verdict = trial.compute_forward_verdict(r["trial_id"])
        if verdict is not None:
            new_status = trial.STATUS_SURVIVED_TRIAL if verdict["verdict"] != "DIED" else trial.STATUS_FAILED_TRIAL
            trial.update_trial_status(r["trial_id"], new_status)
            outcomes.append(ForwardTickOutcome(r["trial_id"], name, True, f"{tick_result.signal_type} tick logged; RESOLVED -> {new_status} ({verdict['reason']})"))
        else:
            outcomes.append(ForwardTickOutcome(r["trial_id"], name, True, f"{tick_result.signal_type} tick logged; still PENDING_FORWARD_DATA"))
    return outcomes


@dataclass(frozen=True)
class RepairAttemptTickOutcome:
    repair_chain_id: str
    attempt_id: str
    ticked: bool
    reason: str


def advance_open_repair_attempts(
    repair_events: list[dict], now: datetime, live: bool, hypothesis_lookup: dict[str, dict] | None = None,
) -> list[RepairAttemptTickOutcome]:
    """Real gap found and closed (2026-08-08): repair_lab.py/repair_forward_
    tracker.py/repair_chain_launch.py build every piece needed to forward-
    track a launched repair attempt (repair_forward_tracker.evaluate_
    forward_tick, compute_forward_verdict), but nothing in this codebase
    ever CALLED evaluate_forward_tick for a PENDING_FORWARD_DATA repair
    attempt before this function -- confirmed by grepping every non-test
    file for both names. trial.run_forward_tick (used by advance_open_
    trials above) is a thin wrapper around the exact same function, but
    only ever for an ALREADY-ADMITTED Forward Trial record, never a raw,
    still-pending repair_attempts.json entry. This is that missing piece,
    mirroring advance_open_trials's own real-candle-fetch, one-tick-per-run
    discipline exactly.

    GLOBALLY-UNIQUE KEY, not the bare per-chain attempt_id: the launcher's
    own commit-and-launch step (tools/repair_chain_launch.py) mints
    attempt_id as f"A{n}" -- unique WITHIN one chain, but NOT across chains
    (two different repair chains can each have their own "A1").
    repair_forward_tracker's own execution_log key
    is f"{strategy_prefix}:{attempt_id}" -- passing bare "A1" would let a
    second chain's own "A1" silently write into and read from the SAME
    execution_log rows as this chain's "A1" (confirmed via
    repair_forward_tracker._strategy_key; the ONE existing collision test,
    test_trial_and_repair_attempt_with_same_literal_id_never_collide,
    covers Trial-vs-repair-attempt collision, not repair-chain-vs-repair-
    chain). Passes f"{original_hypothesis_name}__REPAIR_{attempt_id}"
    instead -- globally unique since hypothesis names are, and the SAME
    naming convention repair_to_trial.admit_repair_to_trial already uses
    for a PROMOTED attempt's own Trial hypothesis_name, so this isn't an
    invented scheme.

    Ticks the MODIFIED structured_entry_rule/structured_exit_plan (the
    attempt's own launched fields -- what's actually being tested), never
    the original hypothesis's own rule. Asset/timeframe resolved from the
    ORIGINAL hypothesis via hypothesis_lookup -- correct for every
    modification_type except asset_timeframe_change, whose own real
    asset/timeframe is not yet captured on the launch event at all (a
    separate, already-documented gap in repair_chain_launch.py; zero real
    attempts of that modification_type exist yet, so this has no live
    instance to get wrong today).

    Only attempts with fresh_data_method="forward_testing" (the default,
    and the only method any real launch has used so far) and a current
    status of PENDING_FORWARD_DATA are ticked -- an already-resolved or
    historical_reservation attempt is left untouched. On resolution
    (compute_forward_verdict returns non-None), appends a REAL
    EVENT_ATTEMPT_RESOLVED event (a real event type this codebase already
    defines and reconstruct_chain_state already knows how to replay, but
    which nothing has ever emitted before this function -- confirmed via
    grep) -- never an intermediate per-tick event, mirroring Forward
    Trial's own "only write on actual state change" discipline."""
    outcomes: list[RepairAttemptTickOutcome] = []
    hypothesis_lookup = hypothesis_lookup or {}
    chain_ids = sorted({e.get("repair_chain_id") for e in repair_events if e.get("repair_chain_id")})
    pending: list[tuple[str, dict]] = []
    for chain_id in chain_ids:
        state = repair_lab.reconstruct_chain_state(chain_id, repair_events)
        for attempt in state["attempts"]:
            if attempt.get("status") != repair_lab.ATTEMPT_PENDING_FORWARD_DATA:
                continue
            if attempt.get("fresh_data_method") != "forward_testing":
                continue
            pending.append((chain_id, attempt))

    if not live:
        for chain_id, attempt in pending:
            outcomes.append(RepairAttemptTickOutcome(chain_id, str(attempt.get("attempt_id")), False, "dry-run -- no candles fetched, no tick performed"))
        return outcomes

    client = MarketDataClient()
    for chain_id, attempt in pending:
        attempt_id = str(attempt.get("attempt_id"))
        original_name = chain_id[len("RC-"):] if chain_id.startswith("RC-") else chain_id
        original_hypothesis = hypothesis_lookup.get(original_name)
        asset, timeframe = (original_hypothesis or {}).get("asset"), (original_hypothesis or {}).get("timeframe")
        if not asset or not timeframe:
            outcomes.append(RepairAttemptTickOutcome(
                chain_id, attempt_id, False,
                f"no hypothesis record found for {original_name!r} in the current Adam/Eve candidate "
                f"lookup -- cannot resolve asset/timeframe",
            ))
            continue
        tracking_id = f"{original_name}__REPAIR_{attempt_id}"
        modified_hypothesis = {
            **(original_hypothesis or {}),
            "asset": asset,
            "timeframe": timeframe,
            "structured_entry_rule": attempt.get("structured_entry_rule"),
            "structured_entry_rule_short": attempt.get("structured_entry_rule_short"),
            "structured_exit_plan": attempt.get("structured_exit_plan"),
        }
        try:
            candles, _method = fetch_timeframe_candles(client, asset, timeframe)
        except MarketDataUnavailableError as exc:
            outcomes.append(RepairAttemptTickOutcome(chain_id, attempt_id, False, f"candle fetch failed: {exc}"))
            continue
        tick_result = repair_forward_tracker.evaluate_forward_tick(tracking_id, modified_hypothesis, candles, now)
        verdict = repair_forward_tracker.compute_forward_verdict(tracking_id)
        if verdict is not None:
            # Real constants, not hardcoded literals -- VERDICT_PROMISING_WATCHLIST's
            # own real string value is hyphenated ("PROMISING-WATCHLIST"), confirmed
            # in tools/backtest_statistics.py; a literal-string comparison here would
            # have silently misclassified every real PROMISING-WATCHLIST as DIED.
            if verdict["verdict"] == repair_lab.ATTEMPT_SURVIVED:
                new_status = repair_lab.ATTEMPT_SURVIVED
            elif verdict["verdict"] == repair_lab.ATTEMPT_PROMISING_WATCHLIST:
                new_status = repair_lab.ATTEMPT_PROMISING_WATCHLIST
            else:
                new_status = repair_lab.ATTEMPT_DIED
            repair_lab.append_repair_event({
                "event": repair_lab.EVENT_ATTEMPT_RESOLVED,
                "repair_chain_id": chain_id,
                "attempt_id": attempt_id,
                "status": new_status,
                "result_ref": tracking_id,
                "result": verdict,
                "resolved_at": now.isoformat(),
            })
            outcomes.append(RepairAttemptTickOutcome(chain_id, attempt_id, True, f"{tick_result.signal_type} tick logged; RESOLVED -> {new_status} ({verdict['reason']})"))
        else:
            outcomes.append(RepairAttemptTickOutcome(chain_id, attempt_id, True, f"{tick_result.signal_type} tick logged; still PENDING_FORWARD_DATA"))
    return outcomes


def build_report(
    fresh_attempts: list[AdmissionAttempt],
    repair_attempts: list[RepairAdmissionAttempt],
    distillation_ready: dict[str, int],
    tick_outcomes: list[ForwardTickOutcome],
    live: bool,
) -> str:
    lines = [f"Factory Loop run ({'LIVE' if live else 'DRY-RUN -- nothing written'}):", ""]
    admitted = [a for a in fresh_attempts if a.admitted]
    not_admitted = [a for a in fresh_attempts if not a.admitted]
    lines.append(f"Fresh admissions: {len(admitted)} admitted, {len(not_admitted)} not admitted, out of {len(fresh_attempts)} candidates considered.")
    for a in fresh_attempts:
        verb = "ADMITTED" if a.admitted else "skipped"
        lines.append(f"  [{verb}] {a.candidate.hypothesis_name} ({a.candidate.origin_agent}): {a.reason}")
        if a.trial_record is not None:
            lines.append(f"    projected_time_to_min_sample: {a.trial_record['projected_time_to_min_sample_label']}")

    repair_admitted = [a for a in repair_attempts if a.admitted]
    lines.append("")
    lines.append(f"Repair admissions: {len(repair_admitted)} admitted, out of {len(repair_attempts)} resolved-passing attempts found.")
    for a in repair_attempts:
        verb = "ADMITTED" if a.admitted else "skipped"
        lines.append(f"  [{verb}] chain={a.repair_chain_id} attempt={a.attempt_id}: {a.reason}")

    lines.append("")
    if distillation_ready:
        lines.append(f"Graveyard distillation: {len(distillation_ready)} family/families at or past the trigger:")
        for family, count in distillation_ready.items():
            lines.append(f"  {family}: {count} DIED")
    else:
        lines.append("Graveyard distillation: no family at or past the trigger.")

    lines.append("")
    lines.append(f"Forward Trial ticks: {len(tick_outcomes)} OPEN record(s).")
    for o in tick_outcomes:
        lines.append(f"  {o.hypothesis_name or o.trial_id}: {o.reason}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Perform the real run (admit, draft, tick, regenerate status). Default is dry-run.")
    args = parser.parse_args()
    live = args.live
    now = datetime.now(timezone.utc)

    forward_trial_records = read_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH)
    repair_events = read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    failure_patterns = read_json_list(graveyard_distillation.DEFAULT_FAILURE_PATTERNS_PATH)

    candidates = load_adam_candidates() + load_eve_candidates()
    fresh_attempts = evaluate_fresh_admissions(candidates, forward_trial_records, now)
    repair_attempts = evaluate_repair_admissions(repair_events, forward_trial_records, now)
    distillation_ready = evaluate_distillation_candidates(failure_patterns, repair_events)

    new_records = [a.trial_record for a in fresh_attempts if a.admitted] + [a.trial_record for a in repair_attempts if a.admitted]
    tick_input_records = forward_trial_records + new_records if live else forward_trial_records
    hypothesis_lookup = {c.hypothesis_name: c.hypothesis_record for c in candidates}
    tick_outcomes = advance_open_trials(tick_input_records, now, live=live, hypothesis_lookup=hypothesis_lookup)
    # Real gap closed 2026-08-08: a repair attempt still PENDING (not yet
    # admitted to Forward Trial) was never ticked forward by anything --
    # advance_open_trials above only ever sees ALREADY-ADMITTED records.
    # This advances the raw repair_attempts.json chains themselves, so a
    # newly-launched attempt (e.g. the first real one, RC-CHANNEL_LOW_
    # PULLBACK_UPTREND_SOL_4H) actually accrues real forward trades instead
    # of sitting frozen at PENDING_FORWARD_DATA forever.
    repair_tick_outcomes = advance_open_repair_attempts(repair_events, now, live=live, hypothesis_lookup=hypothesis_lookup)

    print(build_report(fresh_attempts, repair_attempts, distillation_ready, tick_outcomes, live))
    if repair_tick_outcomes:
        print(f"\nRepair attempt forward ticks: {len(repair_tick_outcomes)} PENDING_FORWARD_DATA attempt(s).")
        for o in repair_tick_outcomes:
            print(f"  {o.repair_chain_id}/{o.attempt_id}: {o.reason}")

    if not live:
        print("\n(dry-run -- nothing written; re-run with --live to admit/draft/tick/regenerate status for real)")
        return

    if new_records:
        append_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH, new_records)
        print(f"\n{len(new_records)} new Trial record(s) written to {trial.DEFAULT_FORWARD_TRIAL_PATH}")

    if distillation_ready:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key.strip():
            print("\nDistillation drafting skipped: ANTHROPIC_API_KEY not set (no call made, no cost incurred).")
        else:
            # REAL BUG FOUND AND FIXED, 2026-08-06 (first --live run): a
            # rejected key (401 -- confirmed $0, never billed, per
            # validate_api_key's own docstring) raised ApiKeyRejectedError
            # uncaught here, crashing main() BEFORE the deterministic steps
            # below (regenerating factory_loop_status.json) ever ran, even
            # though those steps have nothing to do with whether the LLM
            # call succeeded. Caught here so a drafting failure is reported,
            # not silently fatal to the rest of a real run.
            try:
                distillation_result = draft_ready_distillations(failure_patterns, repair_events, api_key)
                persist_distillation_drafts(distillation_result.drafts)
                print(
                    f"\n{len(distillation_result.drafts)} distillation draft(s) written to {DEFAULT_DISTILLATION_DRAFTS_PATH} "
                    f"at review_status=REVIEW_PENDING (human approval required before commit_graveyard_entry may write them). "
                    f"Real cost: ${distillation_result.total_cost_usd:.6f}."
                )
                for err in distillation_result.errors:
                    print(f"  DISTILLATION ERROR (call WAS billed, no draft produced for this family): {err}")
            except graveyard_distillation.ApiKeyRejectedError as exc:
                print(f"\nDistillation drafting failed: {exc} (confirmed $0 -- rejected before any token was processed; the rest of this run still completes).")

    final_forward_trial = read_json_list(trial.DEFAULT_FORWARD_TRIAL_PATH)
    graveyard_entries = read_json_list(graveyard_distillation.DEFAULT_GRAVEYARD_PATH)
    distillation_drafts = read_json_list(DEFAULT_DISTILLATION_DRAFTS_PATH)
    summary_data = status_summary.compute_summary_data(
        final_forward_trial, graveyard_entries, read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH), distillation_drafts,
    )
    status_summary.write_status(summary_data)
    print(f"\nfactory_loop_status.json regenerated:\n{status_summary.build_summary({**summary_data})}")


if __name__ == "__main__":
    main()
