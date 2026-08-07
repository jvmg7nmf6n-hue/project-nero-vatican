"""CLI entrypoint / orchestrator for Eve: kill-switch check -> one session
-> score every hypothesis it produced -> FDR correction -> contamination
tags -> persist scored results back into the same three allowlisted files.
Mirrors nero_core.research_agent.pipeline's own conventions (kill-switch
checked first, ANTHROPIC_API_KEY read exactly once via os.getenv and passed
explicitly thereafter, never printed/logged).

ISOLATION: imports nero_core.eve.* plus
nero_core.execution.export_candle_data.candle_filename -- NOT under
nero_core/research_agent/ (Adam's own pipeline.py already reuses this exact
same helper for its own default candle provider; it is this codebase's
established, neutral place candle-file naming lives, not a
research_agent-specific convention). No nero_core.research_agent import
anywhere in this file -- test_eve_no_auto_wire.py confirms this file has
zero such imports (unlike nero_core.eve.scoring, this module's own dynamic
call INTO scoring.score_all is where the one documented exception actually
lives, not here)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nero_core.asset_universe import APPROVED_EVALUATION_UNIVERSE, APPROVED_RESEARCH_UNIVERSE
from nero_core.execution.export_candle_data import candle_filename
from nero_core.eve import context as eve_context
from nero_core.eve import llm_client, notify as eve_notify, preflight as eve_preflight, scoring, session, storage
from nero_core.eve.config import is_enabled

REPO_ROOT = storage.REPO_ROOT
DEFAULT_CANDLES_DIR = REPO_ROOT / "docs" / "site_data" / "candles"
# Full-history research export (nero_core.execution.export_candle_data.
# export_research_candle_data) -- a SEPARATE, larger export than the
# website's own 200-row display export above. THE ONLY candle source
# default_candles_provider will ever use (see APPROVED_RESEARCH_UNIVERSE
# below) -- scoring needs real backtest history, not a chart-sized slice
# (see docs/investigations/eve_engine_v1_report.md's own finding that 200
# candles left ma200 NaN everywhere but the last row, and zero of 200 random
# baseline hypotheses ever reached MIN_SAMPLE_SIZE out-of-sample trades).
DEFAULT_RESEARCH_CANDLES_DIR = REPO_ROOT / "docs" / "research_data" / "candles"

# APPROVED_RESEARCH_UNIVERSE / APPROVED_EVALUATION_UNIVERSE now live in
# nero_core.asset_universe (shared with Adam's own research_agent/pipeline.py
# -- see that module's own default_candles_provider) -- re-exported here
# under their original names so every existing import of
# `nero_core.eve.pipeline.APPROVED_RESEARCH_UNIVERSE` keeps working
# unchanged. See that module's own docstring for the full standing-rule
# reasoning and why the two universes are kept structurally distinct.

CandlesProvider = Callable[[str, str], "pd.DataFrame | None"]


def _read_candles_file(path: Path) -> "pd.DataFrame | None":
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        rows = data["candles"]
        return pd.DataFrame({
            "close_time": [int(c["time"]) * 1000 for c in rows],
            "close": [float(c["close"]) for c in rows],
            "high": [float(c["high"]) for c in rows],
            "low": [float(c["low"]) for c in rows],
            "volume": [float(c.get("volume") or 0.0) for c in rows],
        })
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ERROR: {path} is malformed ({exc.__class__.__name__}: {exc}) -- treating as no candle data available.", file=sys.stderr)
        return None


def default_candles_provider(
    asset: str,
    timeframe: str,
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    research_candles_dir: Path = DEFAULT_RESEARCH_CANDLES_DIR,
) -> "pd.DataFrame | None":
    """REFUSES (raises scoring.DataSourceRefusedError) rather than degrades:
    an (asset, timeframe) pair outside APPROVED_RESEARCH_UNIVERSE, or one
    inside it whose research export file is missing on disk, never falls
    back to `candles_dir` (the website's 200-row display export) -- that
    silent substitution is exactly the failure mode this function used to
    have (see APPROVED_RESEARCH_UNIVERSE's own comment). `candles_dir` is
    kept as a parameter (unused in the success path) only so existing
    callers/tests that pass it explicitly don't need a signature change.

    This is Eve's own default provider only; nero_core.research_agent.
    pipeline's own default_candles_provider is UNCHANGED (still reads only
    the 200-row site export) -- deliberately not touched here, flagged for
    separate confirmation before Adam's own production data source is
    changed.

    On success, the returned frame is tagged (`.attrs["data_source"]` /
    `.attrs["row_count"]`) so score_hypothesis can record what was actually
    used on every scored record, not just infer it.

    EVALUATION-UNIVERSE PAIRS ARE REJECTED EXPLICITLY, before the general
    "not in the research universe" check below, with their own distinct
    message -- see nero_core.asset_universe's own docstring on why an
    evaluation-only pair (a pre-existing live strategy being backtested,
    never a hypothesis-search candidate) must never reach Eve's scoring
    path, structurally never just by omission from the research universe."""
    if (asset, timeframe) in APPROVED_EVALUATION_UNIVERSE:
        raise scoring.DataSourceRefusedError(
            f"{asset}/{timeframe} is in APPROVED_EVALUATION_UNIVERSE, not APPROVED_RESEARCH_UNIVERSE -- "
            f"evaluation-only pairs (pre-existing live strategies being backtested, never a hypothesis-"
            f"search candidate) are never available for Eve's hypothesis scoring, by design. "
            f"See nero_core.asset_universe."
        )
    if (asset, timeframe) not in APPROVED_RESEARCH_UNIVERSE:
        raise scoring.DataSourceRefusedError(
            f"{asset}/{timeframe} is not in Eve's APPROVED_RESEARCH_UNIVERSE "
            f"{sorted(APPROVED_RESEARCH_UNIVERSE)} -- refusing to silently fall back to the "
            f"{candles_dir.name if hasattr(candles_dir, 'name') else candles_dir} site display export "
            f"(200 rows, no random baseline ever computed for this pair)."
        )
    research_frame = _read_candles_file(research_candles_dir / candle_filename(asset, timeframe))
    if research_frame is None:
        raise scoring.DataSourceRefusedError(
            f"{asset}/{timeframe} is in APPROVED_RESEARCH_UNIVERSE but its research export file is "
            f"missing at {research_candles_dir / candle_filename(asset, timeframe)} -- refusing to "
            f"silently fall back to the site display export."
        )
    research_frame.attrs["data_source"] = "research_export"
    research_frame.attrs["row_count"] = len(research_frame)
    return research_frame


def _compute_backtest_window_start(scored_hypotheses: list[dict], candles_provider: CandlesProvider) -> datetime | None:
    """The earliest close_time across every distinct (asset, timeframe) pair
    this session's scored hypotheses actually touched -- the LOOKAHEAD_RISK
    check's own window-start reference point (spec 3.5). None if no real
    candle data was available for anything scored this session (nothing to
    check against)."""
    earliest: datetime | None = None
    seen_pairs: set[tuple[str, str]] = set()
    for h in scored_hypotheses:
        raw = h.get("raw_hypothesis") if isinstance(h.get("raw_hypothesis"), dict) else {}
        asset, timeframe = raw.get("asset"), raw.get("timeframe")
        if not asset or not timeframe or (asset, timeframe) in seen_pairs:
            continue
        seen_pairs.add((asset, timeframe))
        try:
            candles = candles_provider(asset, timeframe)
        except scoring.DataSourceRefusedError:
            # Same refusal score_hypothesis already recorded on this pair's
            # own scored record -- this is a best-effort secondary check
            # (the lookahead window start), not a second place to report it.
            continue
        if candles is None or len(candles) == 0:
            continue
        first_close_time_ms = int(candles["close_time"].min())
        candidate = datetime.fromtimestamp(first_close_time_ms / 1000.0, tz=timezone.utc)
        if earliest is None or candidate < earliest:
            earliest = candidate
    return earliest


def _persist_scored_hypotheses(scored: list[dict]) -> None:
    """Rewrites eve_hypotheses.json, replacing each already-persisted
    UNSCORED record (matched by (session_id, tool_use_id) -- unique per
    propose_hypothesis call) with its scored counterpart. Atomic full-list
    rewrite (storage.atomic_write_json_list), not a second append -- scoring
    a hypothesis UPDATES its existing record, it does not duplicate it."""
    if not scored:
        return
    existing = storage.read_json_list(storage.DEFAULT_HYPOTHESES_PATH)
    by_key = {(r.get("session_id"), r.get("tool_use_id")): r for r in scored}
    updated = [by_key.get((r.get("session_id"), r.get("tool_use_id")), r) for r in existing]
    storage.atomic_write_json_list(storage.DEFAULT_HYPOTHESES_PATH, updated)


def _load_eve_history_excluding_session(session_id: str) -> list[dict]:
    """CC-1 review, item 1: Eve's own past hypotheses -- every OTHER
    session's raw_hypothesis dicts read straight from eve_hypotheses.json
    (confirmed gap being fixed here: that file was write-only, read back by
    nothing, before this function existed). Filters out `session_id`'s own
    records -- by the time this is called, session.run_session has already
    persisted THIS session's own (still-UNSCORED) records to the same file
    (see session.py's own end-of-function write), so an unfiltered read
    would compare every hypothesis against itself and flag 100% of them."""
    existing = storage.read_json_list(storage.DEFAULT_HYPOTHESES_PATH)
    return [
        r["raw_hypothesis"] for r in existing
        if isinstance(r, dict) and r.get("session_id") != session_id and isinstance(r.get("raw_hypothesis"), dict)
    ]


def _parse_session_started_at(session_record: dict) -> datetime | None:
    """The reference clock for item 7's binding freshness check -- the
    session's own started_at, NOT wall-clock now (this scoring pass can run
    well after the session itself, e.g. a re-score). None (never a
    fabricated fallback) if started_at is missing/unparseable -- the caller
    treats that as "cannot evaluate this rule for this session" rather than
    guessing a reference point."""
    started_at = session_record.get("started_at")
    if not isinstance(started_at, str):
        return None
    try:
        return datetime.fromisoformat(started_at)
    except ValueError:
        return None


def _persist_session_record_amendments(
    session_record: dict, lookahead_flags: list[dict], n_self_derivative: int,
    freshness_flags: list | None = None, entire_session_disqualified: bool = False,
    n_citation_validation_errors: int = 0,
) -> dict:
    """Amends the already-persisted session record with everything only
    knowable AFTER scoring runs -- lookahead-risk flags (spec 3.5), the
    self-derivative count (CC-1 review item 1d, 'record the per-session
    count in ablation metadata'), and (CC-1 directive item 7a/7b, added
    2026-08-05) the binding freshness-disqualification flags plus the
    100%-disqualified fail-loud marker. Scoring is a completely separate
    pass after session.run_session returns (see session.py's own module
    docstring), so none of these can be known at the point session.py
    writes its own record. ONE combined atomic write, not several separate
    ones -- independent read-modify-write calls against the same file would
    let a later one silently clobber an earlier amendment. Always writes
    (an empty flags list, a zero count, and disqualified=False are all
    meaningful facts, not absence of data)."""
    updated_ablation = {
        **(session_record.get("ablation_metadata") or {}),
        "n_self_derivative_hypotheses": n_self_derivative,
        "n_freshness_disqualification_flags": len(freshness_flags or []),
        # CC-1 directive (2026-08-05) item 1: count of hypotheses this
        # session that cited at least one URL never actually returned by
        # this session's own searches -- a hard validation error (item 1's
        # own words), surfaced here (and via pipeline.run_pipeline's own
        # stderr WARNING below) rather than silently dropped.
        "n_citation_validation_errors": n_citation_validation_errors,
    }
    updated = {
        **session_record,
        "lookahead_risk_flags": lookahead_flags,
        "freshness_disqualification_flags": freshness_flags or [],
        "freshness_disqualified_entire_session": entire_session_disqualified,
        "ablation_metadata": updated_ablation,
    }
    storage.atomic_write_json_dict(storage.session_record_path(session_record["session_id"]), updated)
    return updated


@dataclass(frozen=True)
class PipelineRunResult:
    enabled: bool
    reason: str
    session_result: "session.SessionResult | None" = None
    scored_hypotheses: list = field(default_factory=list)
    lookahead_risk_flags: list = field(default_factory=list)
    preflight_ok: bool = True


def run_pipeline(
    api_key: str = "",
    candles_provider: CandlesProvider = default_candles_provider,
    stub: bool | None = None,
    now: datetime | None = None,
) -> PipelineRunResult:
    """The ONE entrypoint every invocation of Eve should call. Kill-switch
    checked FIRST (nero_core.eve.config.is_enabled) -- disabled means no
    session, no LLM call, no candle fetch, no file write, anywhere, exactly
    like Adam's own pipeline.run_pipeline.

    PREFLIGHT SECOND (skipped only in stub mode, where there is no real key
    or network call to validate): nero_core.eve.preflight.check_api_key runs
    BEFORE session.run_session is ever called, so a stale/invalid key is
    caught with zero real spend and zero partial session file written --
    never session.run_session's own budget-exhaustion path, which only
    protects against the CEILING, not a bad key. A preflight failure sends
    exactly one ntfy failure notification and returns immediately.

    EVERY OTHER FAILURE MODE also notifies exactly once: an unhandled
    exception during the session/scoring path, or the ledger already being
    exhausted before a single real turn ran (session.n_turns == 0) both
    route through nero_core.eve.notify.send_failure. A session that
    completed at least one real turn -- even if later truncated by its own
    budget -- gets the richer end-of-session summary instead; a mid-session
    budget stop is correct, expected behavior, not a failure to report as
    one (see this branch's own closing report)."""
    if not is_enabled():
        return PipelineRunResult(enabled=False, reason="EVE_ENABLED is not set to a truthy value -- no-op")

    use_stub = llm_client.is_stub_mode() if stub is None else stub
    if not use_stub:
        preflight = eve_preflight.check_api_key(api_key)
        if not preflight.ok:
            reason = f"preflight_rejected: {preflight.reason}"
            print(f"Eve preflight FAILED: {preflight.reason}", file=sys.stderr)
            eve_notify.send_failure(reason=reason, cost_hint_usd=0.0)
            return PipelineRunResult(enabled=True, reason=reason, preflight_ok=False)

    # CC-1 Master Directive, Phase 1.1d: minted HERE, before run_session is
    # ever called, so the crash notification below can always name the
    # session -- even when run_session itself never returns (a crash mid-
    # loop propagates the exception without a SessionResult to read a
    # session_id from). `now` is resolved to the SAME real clock value used
    # both to mint this id and to pass into run_session, so the id's own
    # embedded timestamp and the session record's own started_at can never
    # disagree by re-resolving "now" a second time at a different instant.
    now = now or datetime.now(timezone.utc)
    session_id = session.new_session_id(now)
    # CC-1 directive, item B1: loaded BEFORE run_session (not just after,
    # as before this directive) so a declared derived_from can be validated
    # live, during the session, against Eve's real prior-session history --
    # same function, same "exclude this session's own not-yet-written
    # records" behavior, called once and reused for both purposes rather
    # than reading the file twice.
    eve_history = _load_eve_history_excluding_session(session_id)
    try:
        result = session.run_session(
            api_key=api_key, stub=stub, now=now, session_id=session_id, eve_history=eve_history,
        )

        adam_history = eve_context.load_adam_history_verdict_stripped()
        scored = scoring.score_all(result.hypothesis_records, candles_provider=candles_provider, now=now)
        # Contamination tagging BEFORE FDR correction (order matters, unlike
        # before CC-1's own item 1 fix): apply_fdr_correction now excludes a
        # SELF_DERIVATIVE-tagged record from the FDR family, so the tag must
        # already be attached by the time it runs.
        scored = scoring.apply_derivative_tags(scored, adam_history=adam_history)
        scored = scoring.apply_self_derivative_tags(scored, eve_history=eve_history)
        # CC-1 directive, "Fix the REFINEMENT tagging mechanism gap"
        # (2026-08-07): apply_self_derivative_tags above only reclassifies a
        # REFINEMENT tag when tag_derivative's similarity check independently
        # fires against `eve_history` (prior sessions only) -- a same-session
        # declared parent, or one below the similarity threshold, would get
        # no tag at all. known_hypothesis_names mirrors session.py's own
        # pre-submit validation universe (Adam's history | Eve's prior
        # sessions | this session's own now-finalized batch) so a same-
        # session parent validates correctly here too.
        known_hypothesis_names = (
            {h.get("hypothesis_name") for h in adam_history if h.get("hypothesis_name")}
            | {h.get("hypothesis_name") for h in eve_history if h.get("hypothesis_name")}
            | {
                r["raw_hypothesis"].get("hypothesis_name")
                for r in scored
                if isinstance(r.get("raw_hypothesis"), dict) and r["raw_hypothesis"].get("hypothesis_name")
            }
        )
        scored = scoring.apply_declared_refinement_tags(scored, known_hypothesis_names)
        # CC-1 directive item 7: binding freshness disqualification MUST run
        # before apply_fdr_correction (same ordering requirement as the
        # self-derivative tags above -- see apply_fdr_correction's own
        # docstring) so a disqualified record is excluded from the FDR
        # family, not just flagged after the fact.
        session_started_at = _parse_session_started_at(result.record)
        freshness_flags = (
            scoring.check_freshness_disqualification(result.record, session_started_at)
            if session_started_at is not None else []
        )
        scored = scoring.apply_freshness_disqualification(scored, freshness_flags)
        # CC-1 directive (2026-08-05) items 1+2: per-hypothesis citation-
        # based freshness attribution -- a SIBLING to the session-wide check
        # just above, not a replacement (see scoring.check_per_hypothesis_
        # freshness's own module-level comment). Strictly informational,
        # exactly like the session-wide check: never consulted by
        # apply_fdr_correction below or by admit_to_trial.
        scored = scoring.apply_per_hypothesis_freshness(scored, result.record, session_started_at)
        scored = scoring.apply_fdr_correction(scored, field="p_value_oos")
        scored = scoring.apply_fdr_correction(scored, field="p_value_is")
        _persist_scored_hypotheses(scored)

        n_self_derivative = sum(1 for r in scored if scoring.is_self_derivative(r))
        window_start = _compute_backtest_window_start(scored, candles_provider)
        lookahead_flags = scoring.tag_lookahead_risk(result.record, window_start) if window_start is not None else []
        # Item 7b -- FAIL LOUD: a session whose real hypothesis count is
        # nonzero but every single one was freshness-disqualified must be
        # surfaced prominently, not buried -- "a rule that silently zeroes a
        # session is the same failure class we have spent this week
        # eliminating" (directive's own words). Computed against `scored`
        # (the real testable population), not the raw proposal count, since
        # a hypothesis dropped pre-scoring for an unrelated reason should
        # not inflate this ratio.
        entire_session_disqualified = bool(scored) and all(scoring.is_freshness_disqualified(r) for r in scored)
        if entire_session_disqualified:
            print(
                f"WARNING: session {result.session_id} -- 100% of its {len(scored)} hypothesis(es) were "
                f"freshness-disqualified (item 7, Variant C, {scoring.FRESHNESS_DISQUALIFICATION_WINDOW_DAYS}-day "
                f"window) -- this session contributes ZERO admissible data points this run.",
                file=sys.stderr,
            )
        # CC-1 directive (2026-08-05) item 1: FAIL LOUD on a citation that
        # names a URL this session never actually searched -- a hard
        # validation error, not a silent pass. One WARNING line per
        # offending hypothesis, naming it and the exact invalid URL(s), so
        # this is grep-able the same way item 7b's 100%-disqualified warning
        # already is.
        n_citation_validation_errors = sum(1 for r in scored if r.get("supporting_source_urls_invalid"))
        for r in scored:
            invalid_urls = r.get("supporting_source_urls_invalid")
            if invalid_urls:
                name = (r.get("raw_hypothesis") or {}).get("hypothesis_name")
                print(
                    f"WARNING: session {result.session_id} -- hypothesis {name!r} cited "
                    f"supporting_source_urls not found in this session's own searches: {invalid_urls} "
                    f"-- treated as a validation error, excluded from this hypothesis's validated citation list.",
                    file=sys.stderr,
                )
        _persist_session_record_amendments(
            result.record, lookahead_flags, n_self_derivative,
            freshness_flags=freshness_flags, entire_session_disqualified=entire_session_disqualified,
            n_citation_validation_errors=n_citation_validation_errors,
        )
    except Exception as exc:
        # CC-1 Master Directive, Phase 1.1d: session_id is now always known
        # here (minted above, before run_session was ever called) -- no
        # longer omitted just because `result` was never assigned.
        eve_notify.send_failure(reason=f"crash: {exc.__class__.__name__}: {exc}", session_id=session_id)
        raise

    if result.n_turns == 0:
        eve_notify.send_failure(
            reason=f"{result.terminated_because} (0 real turns completed)",
            session_id=result.session_id,
            cost_hint_usd=result.session_spent_usd,
        )
    else:
        n_testable = sum(1 for r in scored if r.get("testability") == scoring.TESTABILITY_TESTABLE)
        verdict_counts = dict(Counter(r["verdict_oos"] for r in scored if r.get("verdict_oos") is not None))
        eve_notify.send_session_summary(
            session_id=result.session_id,
            terminated_because=result.terminated_because,
            n_proposed=result.n_proposed,
            n_testable=n_testable,
            verdict_counts=verdict_counts,
            real_cost_usd=result.session_spent_usd,
            session_file_path=str(storage.session_record_path(result.session_id)),
        )

    return PipelineRunResult(
        enabled=True, reason="ok", session_result=result, scored_hypotheses=scored, lookahead_risk_flags=lookahead_flags
    )


def main() -> None:
    # The ONE place in nero_core/eve/ that reads ANTHROPIC_API_KEY from the
    # environment -- read once, passed explicitly as api_key= thereafter,
    # never printed/logged (see test_eve_secret_handling.py's ast-based
    # check, mirroring test_research_agent_secret_handling.py's own).
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    result = run_pipeline(api_key=api_key)
    if not result.enabled or not result.preflight_ok or result.session_result is None:
        print(f"Eve pipeline: {result.reason}")
        return
    sr = result.session_result
    print(
        f"Eve session {sr.session_id}: terminated_because={sr.terminated_because}, "
        f"n_turns={sr.n_turns}, n_searches={sr.n_searches}, n_proposed={sr.n_proposed}, "
        f"session_spent_usd=${sr.session_spent_usd:.4f}, scored={len(result.scored_hypotheses)}, "
        f"lookahead_risk_flags={len(result.lookahead_risk_flags)}"
    )


if __name__ == "__main__":
    main()
