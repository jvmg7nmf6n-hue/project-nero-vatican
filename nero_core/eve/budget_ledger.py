"""Phase 1 -- Eve's budget ledger: a hard $20/calendar-month (UTC) ceiling
plus a per-session sub-budget, enforced BEFORE every single LLM call via a
projected-cost bound (never an average), with reserve-then-reconcile
accounting so a crash mid-call can never leave real spend unrecorded.

UTC MONTH SCOPING (1.1): "current month" is always computed in UTC
(`current_utc_month`), never local/PKT time -- stated explicitly because a
PKT boundary (UTC+5) would grant a few hours of double allowance around the
1st of the month relative to Anthropic's own UTC billing cycle. A new UTC
month's first call starts a fresh running total (see month_spent_usd, which
filters by month string); every prior month's entries are retained forever in
the ledger file (an append-only list, per nero_core.eve.storage) -- nothing
here ever deletes an old month's entries.

RESERVE-THEN-RECONCILE (1.5): reserve_entry() is written to the ledger
BEFORE the LLM call is issued, status="reserved", carrying the PROJECTED
cost. reconcile_entry() (called after the call completes, from the real
`usage` block) flips it to status="actual" with the real cost. Crucially,
month_spent_usd/session_spent_usd below treat a still-"reserved" entry as
real spend AT ITS PROJECTED VALUE, unconditionally -- not just "on startup"
as a special case, but on every single read. This is what makes an orphaned
reserved entry (the process crashed between issuing the call and reconciling
it) automatically counted as spend the next time anything reads the ledger,
with no separate startup-recovery code path needed: the conservative
treatment IS the read path, always.

UNDER-COUNTING IS THE ONE DIRECTION THIS MUST NEVER DRIFT (1.2): every cost
figure here routes through nero_core.eve.cost.call_cost_usd_with_tools, which
sums all four usage fields (input, cache_creation at 1.25x, cache_read at
0.1x, output) plus real per-search fees -- never just input+output.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nero_core.eve import storage
from nero_core.eve.cost import (
    DEFAULT_COST_PARAMETERS,
    CostParameters,
    call_cost_usd_with_tools,
    usage_token_breakdown,
    web_search_count,
)

# A HARD ceiling, not an env-configurable knob -- deliberately NOT read from
# an environment variable (unlike EVE_SESSION_BUDGET_USD below), so a stray
# env var can never silently raise Eve's real-money ceiling. Changing this
# number is a code change, reviewed like any other.
MONTH_CEILING_USD = 20.0

# Per-session sub-budget (spec 1.4): without this, one session could consume
# the whole month's ceiling in one shot. $1.50 default -- see this branch's
# closing report for the full justification (roughly: generous enough for a
# real multi-turn research session with a few web searches, small enough that
# even a maximally unlucky run leaves >90% of the month's ceiling intact for
# every other session that month).
SESSION_BUDGET_ENV_VAR = "EVE_SESSION_BUDGET_USD"
DEFAULT_SESSION_BUDGET_USD = 1.50

REASON_MONTH_EXHAUSTED = "budget-exhausted-for-month"
REASON_SESSION_EXHAUSTED = "budget-exhausted-for-session"

STATUS_RESERVED = "reserved"
STATUS_ACTUAL = "actual"


def session_budget_usd(env: "os._Environ | dict[str, str] | None" = None) -> float:
    """Reads EVE_SESSION_BUDGET_USD, defaulting to DEFAULT_SESSION_BUDGET_USD
    when unset or unparseable -- never raises on a malformed env var, since a
    typo'd env value should fail safe (the conservative default) rather than
    crash a session before it starts."""
    source = env if env is not None else os.environ
    raw = source.get(SESSION_BUDGET_ENV_VAR)
    if raw is None:
        return DEFAULT_SESSION_BUDGET_USD
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SESSION_BUDGET_USD


def current_utc_month(now: datetime | None = None) -> str:
    """'YYYY-MM' in UTC -- see module docstring on why UTC, never local time."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m")


def _entry_cost_usd(entry: dict) -> float:
    """A 'reserved' entry counts at its PROJECTED cost (conservative -- see
    module docstring); an 'actual' entry counts at its real reconciled cost."""
    if entry.get("status") == STATUS_ACTUAL:
        return float(entry.get("actual_cost_usd") or 0.0)
    return float(entry.get("projected_cost_usd") or 0.0)


def month_spent_usd(entries: list[dict], month: str) -> float:
    """Total spend (actual + conservatively-counted-reserved) for `month`
    ('YYYY-MM', UTC) across ALL sessions. This is the ledger's single source
    of truth for 'how much has this UTC month spent so far' -- every
    pre-call check reads this, never a cached/derived running total."""
    return sum(_entry_cost_usd(e) for e in entries if e.get("month") == month)


def session_spent_usd(entries: list[dict], session_id: str) -> float:
    """Total spend (actual + conservatively-counted-reserved) for one
    session, across however many months it happens to span (a session is not
    expected to cross a UTC month boundary in practice, but nothing here
    assumes it can't)."""
    return sum(_entry_cost_usd(e) for e in entries if e.get("session_id") == session_id)


def project_call_cost_usd(
    current_history_tokens: int,
    expected_tool_result_tokens: int,
    max_tokens: int,
    max_searches_per_turn: int,
    params: CostParameters = DEFAULT_COST_PARAMETERS,
) -> float:
    """The pre-call BOUND (1.3): a worst-case projection for the NEXT call,
    never a typical/average call's cost. In a multi-turn loop resending full
    history every turn, input cost grows monotonically turn over turn -- an
    average-derived margin would happily approve a call that blows the
    ceiling in one shot on a later, much-larger turn. This assumes every
    projected input token bills at the base input rate (no caching credit
    taken in the projection, even though the real call may hit the cache) --
    deliberately the more expensive assumption, since UNDER-projecting is the
    one failure mode that could let a call breach the ceiling.

    current_history_tokens/expected_tool_result_tokens are the caller's own
    estimate (see nero_core.eve.session's token-estimation method -- this
    function does not compute them itself, it only applies the bound formula
    to whatever the caller supplies)."""
    input_tokens_est = current_history_tokens + expected_tool_result_tokens
    return (
        (input_tokens_est / 1_000_000.0) * params.input_cost_per_mtok
        + (max_tokens / 1_000_000.0) * params.output_cost_per_mtok
        + max_searches_per_turn * params.web_search_cost_per_search
    )


@dataclass(frozen=True)
class PreCallCheckResult:
    allowed: bool
    reason: str
    projected_cost_usd: float
    month_spent_usd: float
    session_spent_usd: float


def pre_call_check(
    entries: list[dict],
    session_id: str,
    projected_cost_usd: float,
    month_ceiling_usd: float = MONTH_CEILING_USD,
    session_budget: float | None = None,
    now: datetime | None = None,
) -> PreCallCheckResult:
    """Refuses (allowed=False) if EITHER ceiling would be breached by the
    projected cost of the NEXT call -- called before every single LLM call,
    not just at session start (1.3)."""
    month = current_utc_month(now)
    m_spent = month_spent_usd(entries, month)
    s_spent = session_spent_usd(entries, session_id)
    session_budget = session_budget_usd() if session_budget is None else session_budget

    if m_spent + projected_cost_usd > month_ceiling_usd:
        return PreCallCheckResult(
            False,
            f"{REASON_MONTH_EXHAUSTED}: month_spent=${m_spent:.4f} + projected=${projected_cost_usd:.4f} "
            f"> ceiling=${month_ceiling_usd:.2f}",
            projected_cost_usd, m_spent, s_spent,
        )
    if s_spent + projected_cost_usd > session_budget:
        return PreCallCheckResult(
            False,
            f"{REASON_SESSION_EXHAUSTED}: session_spent=${s_spent:.4f} + projected=${projected_cost_usd:.4f} "
            f"> budget=${session_budget:.2f}",
            projected_cost_usd, m_spent, s_spent,
        )
    return PreCallCheckResult(True, "ok", projected_cost_usd, m_spent, s_spent)


def reserve_entry(session_id: str, turn_index: int, projected_cost_usd: float, now: datetime | None = None) -> dict:
    """Built and appended to the ledger BEFORE the LLM call is issued (1.5
    step 1)."""
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": storage.SCHEMA_VERSION,
        "entry_id": str(uuid.uuid4()),
        "session_id": session_id,
        "turn_index": turn_index,
        "status": STATUS_RESERVED,
        "month": current_utc_month(now),
        "projected_cost_usd": projected_cost_usd,
        "actual_cost_usd": None,
        "usage": None,
        "created_at": now.isoformat(),
        "reconciled_at": None,
    }


def reconcile_entry(entry: dict, usage: dict, now: datetime | None = None, params: CostParameters = DEFAULT_COST_PARAMETERS) -> dict:
    """Returns a NEW entry dict (status="actual") from the call's real
    `usage` block (1.5 step 2) -- the caller persists it via update_entry.
    Never mutates `entry` in place."""
    now = now or datetime.now(timezone.utc)
    actual_cost = call_cost_usd_with_tools(usage, params)
    usage_breakdown = usage_token_breakdown(usage)
    usage_breakdown["web_search_requests"] = web_search_count(usage)
    return {
        **entry,
        "status": STATUS_ACTUAL,
        "actual_cost_usd": actual_cost,
        "usage": usage_breakdown,
        "reconciled_at": now.isoformat(),
    }


def load_ledger(path: Path = storage.DEFAULT_BUDGET_LEDGER_PATH) -> list[dict]:
    return storage.read_json_list(path)


def append_entry(entry: dict, path: Path = storage.DEFAULT_BUDGET_LEDGER_PATH) -> None:
    storage.append_json_list(path, [entry])


def update_entry(entry_id: str, updated_entry: dict, path: Path = storage.DEFAULT_BUDGET_LEDGER_PATH) -> None:
    """Atomic full-list rewrite (via storage.atomic_write_json_list) that
    replaces exactly one entry by entry_id -- this is the one ledger
    operation that is NOT append-only (reconciliation genuinely changes an
    existing entry's status), but it is still crash-safe: the write is
    atomic (temp file + rename), so a crash mid-write leaves the prior
    on-disk state (the "reserved" entry) intact, which 1.5's own
    conservative-counting behavior already handles correctly."""
    entries = storage.read_json_list(path)
    new_entries = []
    replaced = False
    for e in entries:
        if e.get("entry_id") == entry_id:
            new_entries.append(updated_entry)
            replaced = True
        else:
            new_entries.append(e)
    if not replaced:
        raise ValueError(f"entry_id {entry_id!r} not found in ledger at {path}")
    storage.atomic_write_json_list(path, new_entries)
