"""CC-1 Factory Loop directive, item 4: TEST -> TRIAL (core).

Before this, a SURVIVED/PROMISING-WATCHLIST verdict meant exactly one thing:
auto_tester.py set review_status="pending_human_approval" on the TestResult
-- nothing forward-tracked it, nothing distinguished "reviewed and
approved" from "never looked at." The only real forward-testing
infrastructure in this codebase was nero_core.research_agent.
repair_forward_tracker, scoped exclusively to Repair Lab attempts. This
module is a THIN WRAPPER around that same proven mechanism (see
repair_forward_tracker.evaluate_forward_tick's own `strategy_prefix`
parameter, added alongside this module) -- not a second, separately
invented forward-tracking scheme (docs/investigations/
factory_loop_specification.md's own B1 recommendation).

THE ADMISSION GATE: DSL-validity is the gate, NOT the backtest verdict. Any
hypothesis whose structured_entry_rule/structured_exit_plan parse via
rule_dsl (the SAME parser frequency_gate.py/auto_tester.py/nero_core.eve.
scoring already use for testability -- re-implemented here in 5 lines
rather than imported across the eve/research_agent boundary, matching this
project's own "re-inline a small helper, don't import a private one"
precedent) is admitted, REGARDLESS of whether it SURVIVED, DIED, or landed
anywhere in between -- the backtest verdict becomes an advisory tag on the
Trial record (entry_verdict), never a condition for admission.

FRESHNESS DISQUALIFICATION IS NOT PART OF THIS GATE (CC-1 correction
directive, 2026-08-05): item 4e originally specified DSL-valid AND NOT
freshness-disqualified (item 7's Variant C check). That was shipped in
commit `61d78a8`, then reverted the same day: item 7d's real re-score of
Eve Session 1 showed the check is necessarily session-wide (one qualifying
web search disqualifies every hypothesis in the session, not just the ones
it might have actually informed -- see nero_core.eve.scoring.
check_freshness_disqualification's own PER-HYPOTHESIS ATTRIBUTION
LIMITATION docstring), which combined with the FDR-family exclusion this
gate used to trigger made the pre-registered per-session 5%-FDR-corrected
bar unsatisfiable by construction. `admit_to_trial` below now consults
DSL-validity only -- see its own docstring for the full reversal record,
and docs/site_data/eve_session_registry.json's `freshness_gate_reversal_
provenance` field for the dated, provenance-tracked account.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from nero_core.research_agent import repair_forward_tracker
from nero_core.research_agent.rule_dsl import RuleAmbiguousError, parse_bidirectional_entry_rules, parse_exit_plan
from nero_core.research_agent.storage import append_json_list, read_json_list
from tools.backtest_statistics import MIN_SAMPLE_SIZE

REPO_ROOT = Path(__file__).resolve().parents[2]
# item 8c's locked naming decision: the NEW concept here is "Forward Trial"
# in every public surface (this file's own JSON export, item 8's page copy,
# item 9's status JSON key) -- the EXISTING public "Under Trial" roster tier
# (website/lib/tier.ts, 17 live configs) is UNRELATED and UNCHANGED. Internal
# status values (OPEN/SURVIVED_TRIAL/FAILED_TRIAL below) keep their own
# names, per the directive's own explicit instruction.
DEFAULT_FORWARD_TRIAL_PATH = REPO_ROOT / "docs" / "site_data" / "forward_trial.json"

# item 4's own forward-tracking population shares repair_forward_tracker's
# proven mechanism and (by default) its SAME SQLite file -- a distinct
# strategy_prefix ("TRIAL" vs "REPAIR_LAB_ATTEMPT") is what keeps the two
# populations from colliding in execution_log's own `strategy` column, not a
# second database.
TRIAL_STRATEGY_PREFIX = "TRIAL"
DEFAULT_FORWARD_TRACKING_DB_PATH = repair_forward_tracker.DEFAULT_FORWARD_TRACKING_DB_PATH

ORIGIN_FRESH = "fresh"
ORIGIN_REPAIRED = "repaired"

STATUS_OPEN = "OPEN"
STATUS_SURVIVED_TRIAL = "SURVIVED_TRIAL"
STATUS_FAILED_TRIAL = "FAILED_TRIAL"

# item 4b: a projected time beyond this many years marks a Trial entry as
# effectively unmeasurable within any practical planning horizon -- surfaced
# via queue_health below, never silently absorbed into an undifferentiated
# OPEN count.
UNMEASURABLE_HORIZON_YEARS = 2.0


def is_dsl_valid(hypothesis_record: dict) -> tuple[bool, str]:
    """The DSL-validity half of item 4e's admission gate. Re-implements
    nero_core.eve.scoring.classify_testability's own try/except shape
    directly against rule_dsl (not imported from nero_core.eve.scoring --
    see module docstring) -- same two parse calls, same exception handling,
    applied to Adam's OR Eve's hypothesis record shape identically, since
    both carry structured_entry_rule/structured_exit_plan at the same keys."""
    try:
        parse_bidirectional_entry_rules(hypothesis_record)
        parse_exit_plan(hypothesis_record.get("structured_exit_plan"))
    except RuleAmbiguousError as exc:
        return False, str(exc)
    except (AttributeError, TypeError, KeyError) as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
    return True, "structured_entry_rule and structured_exit_plan both parse via rule_dsl"


def compute_projected_time_to_min_sample(
    measured_trades_per_year: float | None, min_sample_size: int = MIN_SAMPLE_SIZE,
) -> tuple[float | None, str]:
    """item 4a: MANDATORY on every Trial record, never silently omitted.
    None (not a fabricated number) when measured_trades_per_year is
    missing/non-positive -- an unmeasurable hypothesis is still ADMITTED
    (item 4e's gate never depends on this), but must be visibly labeled as
    such rather than sitting in the queue indistinguishable from a viable
    one (the directive's own words)."""
    if not measured_trades_per_year or measured_trades_per_year <= 0:
        return None, (
            f"UNMEASURABLE -- no positive measured trade rate available "
            f"(need >=1 trade/year to project a time to {min_sample_size} trades)"
        )
    years = min_sample_size / measured_trades_per_year
    label = f"{years:.1f} years at the currently measured rate ({measured_trades_per_year:.2f} trades/year)"
    if years > UNMEASURABLE_HORIZON_YEARS:
        label += f" -- EXCEEDS the {UNMEASURABLE_HORIZON_YEARS:.0f}-year visibility horizon (item 4b)"
    return years, label


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    source_hypothesis_ref: dict
    entry_verdict: dict
    measured_trades_per_year: float | None
    projected_time_to_min_sample_years: float | None
    projected_time_to_min_sample_label: str
    opened_at: str
    status: str
    forward_tracking_db_ref: str
    # item 4c: attribution must be renderable wherever a Trial entry is
    # shown -- pre-formatted here from source_hypothesis_ref.origin_agent so
    # every caller (item 8's page, item 9's status export) gets an
    # identical string rather than re-deriving it.
    attribution: str = field(init=False)

    def __post_init__(self) -> None:
        agent = str(self.source_hypothesis_ref.get("origin_agent", "")).capitalize() or "Unknown"
        object.__setattr__(self, "attribution", f"Explored by {agent}, our research agent.")

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "source_hypothesis_ref": self.source_hypothesis_ref,
            "entry_verdict": self.entry_verdict,
            "measured_trades_per_year": self.measured_trades_per_year,
            "projected_time_to_min_sample_years": self.projected_time_to_min_sample_years,
            "projected_time_to_min_sample_label": self.projected_time_to_min_sample_label,
            "opened_at": self.opened_at,
            "status": self.status,
            "forward_tracking_db_ref": self.forward_tracking_db_ref,
            "attribution": self.attribution,
        }


@dataclass(frozen=True)
class AdmissionResult:
    trial_record: TrialRecord | None
    admitted: bool
    reason: str


def admit_to_trial(
    hypothesis_record: dict,
    entry_verdict: dict,
    *,
    origin: str,
    origin_agent: str,
    hypothesis_name: str,
    session_id_or_run_ref: str | None,
    measured_trades_per_year: float | None,
    repair_chain_id: str | None = None,
    attempt_id: str | None = None,
    now: datetime | None = None,
    forward_tracking_db_ref: Path = DEFAULT_FORWARD_TRACKING_DB_PATH,
) -> AdmissionResult:
    """The real gate is DSL-validity alone. The backtest verdict
    (`entry_verdict`) is NEVER a condition here either -- an advisory tag,
    stored as-is on the resulting record.

    FRESHNESS DISQUALIFICATION -- NOT CONSULTED HERE, DELIBERATELY (CC-1
    correction directive, reverting item 4e/7c): a `freshness_disqualified`
    parameter briefly gated admission here (2026-08-05, commit `61d78a8`),
    then was reverted the same day once item 7d's real Session 1 re-score
    showed the check is necessarily session-wide (nero_core.eve.scoring.
    check_freshness_disqualification's own PER-HYPOTHESIS ATTRIBUTION
    LIMITATION) -- one qualifying search result disqualifies an entire
    session's hypotheses, which made the pre-registered per-session FDR bar
    unsatisfiable by construction. This parameter was REMOVED from this
    signature entirely, not merely defaulted off, specifically so a future
    edit cannot silently re-enable binding disqualification by flipping a
    default -- re-adding it requires a new, visible parameter and a
    deliberate human decision outside any "continue without stopping"
    context. See docs/site_data/eve_session_registry.json's own
    freshness_gate_reversal_provenance field and tests/test_trial_admission.
    py's own AdmitToTrialNeverConsultsFreshnessTest for the standing
    regression guard. nero_core.eve.scoring.check_freshness_
    disqualification/apply_freshness_disqualification/is_freshness_
    disqualified and item 7b's fail-loud warning are UNCHANGED and continue
    to compute and record freshness disqualification -- only this
    function's use of that result was reverted.

    `origin` must be "fresh" (a direct Adam/Eve hypothesis) or "repaired" --
    item 5's admit_repair_to_trial is the ONLY caller that should ever pass
    "repaired"; this function does not itself distinguish a fresh caller
    from a repair one beyond trusting this parameter, since the two
    admission PATHS are deliberately separate (spec B3) even though they
    converge on this same record shape."""
    dsl_valid, dsl_reason = is_dsl_valid(hypothesis_record)
    if not dsl_valid:
        return AdmissionResult(None, False, f"DSL-invalid -- not admitted to Trial: {dsl_reason}")

    now = now or datetime.now(timezone.utc)
    source_ref = {
        "origin": origin,
        "origin_agent": origin_agent,
        "hypothesis_name": hypothesis_name,
        "session_id_or_run_ref": session_id_or_run_ref,
    }
    if origin == ORIGIN_REPAIRED:
        source_ref["repair_chain_id"] = repair_chain_id
        source_ref["attempt_id"] = attempt_id

    projected_years, projected_label = compute_projected_time_to_min_sample(measured_trades_per_year)
    record = TrialRecord(
        trial_id=str(uuid.uuid4()),
        source_hypothesis_ref=source_ref,
        entry_verdict=dict(entry_verdict),
        measured_trades_per_year=measured_trades_per_year,
        projected_time_to_min_sample_years=projected_years,
        projected_time_to_min_sample_label=projected_label,
        opened_at=now.isoformat(),
        status=STATUS_OPEN,
        forward_tracking_db_ref=str(forward_tracking_db_ref),
    )
    return AdmissionResult(record, True, "admitted: DSL-valid and not freshness-disqualified")


def run_forward_tick(
    trial_id: str, hypothesis: dict, recent_candles: pd.DataFrame, now: datetime,
    db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH,
) -> repair_forward_tracker.ForwardTickResult:
    """ONE tick against a Trial entry's own forward-tracked history -- the
    exact same mechanism a Repair Lab attempt uses (repair_forward_tracker.
    evaluate_forward_tick), keyed under TRIAL_STRATEGY_PREFIX instead of
    REPAIR_LAB_ATTEMPT so the two populations never collide in the shared
    execution_log table."""
    return repair_forward_tracker.evaluate_forward_tick(
        attempt_id=trial_id, hypothesis=hypothesis, recent_candles=recent_candles, now=now,
        db_path=db_path, strategy_prefix=TRIAL_STRATEGY_PREFIX,
    )


def resolved_trade_count(trial_id: str, db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH) -> int:
    return repair_forward_tracker.resolved_trade_count(trial_id, db_path=db_path, strategy_prefix=TRIAL_STRATEGY_PREFIX)


def compute_forward_verdict(trial_id: str, db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH) -> dict | None:
    return repair_forward_tracker.compute_forward_verdict(trial_id, db_path=db_path, strategy_prefix=TRIAL_STRATEGY_PREFIX)


def persist_trial_records(records: list[TrialRecord], path: Path = DEFAULT_FORWARD_TRIAL_PATH) -> None:
    """Append-only, matching agent_hypotheses.json's own convention (see
    nero_core.research_agent.storage.append_json_list) -- a Trial record's
    STATUS can change over its lifetime (OPEN -> SURVIVED_TRIAL/
    FAILED_TRIAL), but that is handled by load-modify-rewrite in the caller
    (mirroring nero_core.eve.pipeline._persist_scored_hypotheses's own
    "UPDATE an existing record, don't duplicate it" pattern), not by this
    function, which only ever appends brand-new records."""
    append_json_list(path, [r.to_dict() for r in records])


def load_trial_records(path: Path = DEFAULT_FORWARD_TRIAL_PATH) -> list[dict]:
    return read_json_list(path)


def update_trial_status(trial_id: str, new_status: str, path: Path = DEFAULT_FORWARD_TRIAL_PATH) -> bool:
    """Rewrites the ONE record matching trial_id in place -- returns False
    (no-op, never a fabricated success) if no record with that id exists."""
    records = read_json_list(path)
    found = False
    for r in records:
        if r.get("trial_id") == trial_id:
            r["status"] = new_status
            found = True
    if found:
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        path.write_text(json.dumps(records, indent=2) + "\n")
    return found


def queue_health(records: list[dict]) -> dict:
    """item 4b: total OPEN count, and how many of those have a projected
    time to MIN_SAMPLE_SIZE beyond UNMEASURABLE_HORIZON_YEARS -- if the
    second number is a wide majority of the first, the queue is full of
    unmeasurable entries, and this is what makes that visible rather than
    letting it silently accumulate."""
    open_records = [r for r in records if r.get("status") == STATUS_OPEN]
    beyond_horizon = [
        r for r in open_records
        if r.get("projected_time_to_min_sample_years") is not None
        and r["projected_time_to_min_sample_years"] > UNMEASURABLE_HORIZON_YEARS
    ]
    # A record with projected_time_to_min_sample_years=None is UNMEASURABLE
    # in the strongest sense (no positive trade rate at all) -- counted here
    # too, since "we cannot even project a number" is at least as concerning
    # as "the projected number is large."
    unmeasurable = [r for r in open_records if r.get("projected_time_to_min_sample_years") is None]
    return {
        "open_count": len(open_records),
        "beyond_2_years_count": len(beyond_horizon) + len(unmeasurable),
    }
