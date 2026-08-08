"""Real, structured "Factory Loop scoreboard" data
(docs/site_data/factory_loop_scoreboard.json) -- built to answer the owner's
own real questions, none of which the site could answer at a glance before
this: what has the factory loop actually done recently, how many
hypotheses have gone through Repair Lab and come out healthy, how many are
currently ACTIVE (holding a real position right now) vs merely LIVE
(tracked/admitted, eligible to trade), and how many strategies total.

ACTIVE vs LIVE, precisely (2026-08-08 investigation, the real distinction
the owner asked for): "live" = present in the tracked roster/admission
list at all; "active" = a real, currently-open position (an ENTRY with no
later EXIT). These are NOT the same number and the gap is real and large
-- most tracked strategies are flat most of the time, which is expected
for low-frequency edge-testing, not a malfunction.

- Live-scheduler strategies: "active" reuses docs/site_data/stats.json's
  own already-correct, already-quarantine-aware `open_position` field
  (nero_core.execution.export_site_data._strategy_stats) -- never
  recomputed here, so this can never silently drift from what /strategy
  pages already show.
- Forward Trial: NO existing mechanism answers "is this trial currently
  open" -- nero_core.execution.export_trial_entries.py is deliberately
  ENTRY-only (ntfy-alert feed of a discrete historical fact, confirmed
  from its own docstring), so an admitted-but-since-closed trial (e.g.
  ETH_BIDIRECTIONAL_ZSCORE_FADE, which entered 2026-08-05 and exited
  2026-08-08) would misreport as "active" if trial_entries.json were used
  naively for this purpose. This module pairs ENTRY/EXIT rows itself
  (same trailing-open-entry algorithm as export_site_data._pair_round_
  trips, reinlined rather than imported since it's that module's own
  private helper) against the real strategy key TRIAL:<trial_id>.
- Repair Lab: the OLD, hand-curated docs/site_data/repair_candidates.json
  system (3 candidates, all currently unbackfillable -- see tools/
  repair_alert.py's own finding) and the NEW automated repair_attempts.json
  chain system are DELIBERATELY reported as two separate blocks, never
  merged into one number -- they are structurally different systems (see
  repair_alert.py's own module docstring for the full reasoning) and
  merging them would misrepresent "0 automated chains resolved healthy"
  as if it were about the 3 manual candidates, or vice versa.

FAIL-INDEPENDENT: one section's real data being unavailable is recorded
as its own `error` field and never prevents the other sections from being
written, matching this codebase's own export-script convention
(export_quant_metrics.py, export_survivor_distance.py).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.research_agent import repair_lab
from nero_core.research_agent.trial import TRIAL_STRATEGY_PREFIX, load_trial_records
from nero_core.research_agent.repair_forward_tracker import DEFAULT_FORWARD_TRACKING_DB_PATH
from nero_core.truth_ledger.execution_log import list_execution_log
from tools.repair_alert import find_newly_launchable_candidates

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = REPO_ROOT / "docs" / "site_data" / "factory_loop_scoreboard.json"
DEFAULT_STRATEGIES_PATH = REPO_ROOT / "docs" / "site_data" / "strategies.json"
DEFAULT_STATS_PATH = REPO_ROOT / "docs" / "site_data" / "stats.json"
DEFAULT_FORWARD_TRIAL_PATH = REPO_ROOT / "docs" / "site_data" / "forward_trial.json"
DEFAULT_GRAVEYARD_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard.json"
DEFAULT_AGENT_RUN_SUMMARIES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_run_summaries.json"
DEFAULT_EVE_SESSION_REGISTRY_PATH = REPO_ROOT / "docs" / "site_data" / "eve_session_registry.json"

RECENT_ACTIVITY_CAP = 10


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _live_scheduler_section() -> dict:
    strategies = _load_json(DEFAULT_STRATEGIES_PATH, {}).get("strategies", [])
    stats = _load_json(DEFAULT_STATS_PATH, {}).get("strategies", [])
    active = [
        {
            "strategy": s.get("strategy"), "strategy_version": s.get("strategy_version"), "asset": s.get("asset"),
            "entry_price": (s.get("open_position") or {}).get("entry_price"),
            "entered_at": (s.get("open_position") or {}).get("entry_timestamp"),
        }
        for s in stats if s.get("open_position")
    ]
    return {"tracked_count": len(strategies), "active_count": len(active), "active": active}


def _forward_trial_active_trial_ids(db_path: Path = DEFAULT_FORWARD_TRACKING_DB_PATH) -> dict[str, dict]:
    """Real trailing-open-ENTRY pairing, per trial_id -- reinlines export_
    site_data._pair_round_trips's own small algorithm (that module's own
    private helper, not a shared API -- see this file's own docstring)
    against the TRIAL: strategy-key prefix instead of a live-scheduler
    strategy_id."""
    prefix = f"{TRIAL_STRATEGY_PREFIX}:"
    rows = [r for r in list_execution_log(db_path=db_path) if r.strategy.startswith(prefix)]
    by_trial: dict[str, list] = {}
    for row in rows:
        by_trial.setdefault(row.strategy[len(prefix):], []).append(row)

    active: dict[str, dict] = {}
    for trial_id, trial_rows in by_trial.items():
        trial_rows.sort(key=lambda r: r.timestamp)
        open_entry = None
        for row in trial_rows:
            if row.signal_type == "ENTRY":
                open_entry = row
            elif row.signal_type == "EXIT":
                open_entry = None
        if open_entry is not None:
            active[trial_id] = {"entry_price": open_entry.entry_price, "entered_at": open_entry.timestamp.isoformat(), "asset": open_entry.asset}
    return active


def _forward_trial_section() -> dict:
    records = load_trial_records(DEFAULT_FORWARD_TRIAL_PATH)
    open_records = [r for r in records if r.get("status") == "OPEN"]
    by_origin: dict[str, int] = {}
    for r in open_records:
        origin = (r.get("source_hypothesis_ref") or {}).get("origin_agent") or "unknown"
        by_origin[origin] = by_origin.get(origin, 0) + 1

    try:
        active_by_trial_id = _forward_trial_active_trial_ids()
    except Exception as exc:  # noqa: BLE001 -- one DB-read failure must not blank the whole section
        return {"tracked_count": len(open_records), "active_count": None, "active": [], "by_origin": by_origin, "error": f"{exc.__class__.__name__}: {exc}"}

    active = []
    for r in open_records:
        info = active_by_trial_id.get(r.get("trial_id"))
        if info:
            active.append({
                "trial_id": r.get("trial_id"),
                "hypothesis_name": (r.get("source_hypothesis_ref") or {}).get("hypothesis_name"),
                **info,
            })
    return {"tracked_count": len(open_records), "active_count": len(active), "active": active, "by_origin": by_origin}


def _repair_lab_section() -> dict:
    manual_candidates = repair_lab.load_repair_candidates()
    try:
        launchable = find_newly_launchable_candidates()
        launchable_error = None
    except Exception as exc:  # noqa: BLE001
        launchable = []
        launchable_error = f"{exc.__class__.__name__}: {exc}"

    events = repair_lab.read_json_list(repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH)
    chain_ids = sorted({e.get("repair_chain_id") for e in events if e.get("repair_chain_id")})
    chains = []
    open_chains = 0
    resolved_chains = 0
    healthy_count = 0
    for chain_id in chain_ids:
        # chain_status is real_lab's own already-computed field (reconstruct_
        # chain_state -> evaluate_chain_terminal_state), never re-derived here.
        state = repair_lab.reconstruct_chain_state(chain_id, events)
        attempts = state["attempts"]
        if state["chain_status"] == repair_lab.CHAIN_OPEN:
            open_chains += 1
        else:
            resolved_chains += 1
        if any(a.get("status") in (repair_lab.ATTEMPT_SURVIVED, repair_lab.ATTEMPT_PROMISING_WATCHLIST) for a in attempts):
            healthy_count += 1
        chains.append({
            "repair_chain_id": chain_id,
            "original_hypothesis_name": state.get("original_hypothesis_name"),
            "chain_status": state["chain_status"],
            "attempts": [{"attempt_id": a.get("attempt_id"), "status": a.get("status"), "modification_type": a.get("modification_type")} for a in attempts],
        })

    return {
        "manual_candidates": {
            "count": len(manual_candidates),
            "launchable_count": len(launchable),
            "note": "hand-curated docs/site_data/repair_candidates.json entries -- a DIFFERENT system from the automated chains below",
            **({"error": launchable_error} if launchable_error else {}),
        },
        "automated_chains": {
            "count": len(chain_ids),
            "open_chains": open_chains,
            "resolved_chains": resolved_chains,
            "healthy_count": healthy_count,
            "chains": chains,
            "note": "real repair_attempts.json chains -- launched via tools/repair_chain_launch.py, ticked forward via tools/factory_loop_run.py",
        },
    }


def _graveyard_section() -> dict:
    return {"count": len(_load_json(DEFAULT_GRAVEYARD_PATH, []))}


def _recent_activity_section(cap: int = RECENT_ACTIVITY_CAP) -> list[dict]:
    events: list[dict] = []
    for run in _load_json(DEFAULT_AGENT_RUN_SUMMARIES_PATH, []):
        agg = run.get("run_aggregate", {})
        events.append({
            "source": "adam",
            "at": run.get("run_at"),
            "summary": f"{agg.get('hypotheses_generated') or 0} hypotheses generated, ${agg.get('total_llm_cost_usd') or 0:.4f} spent",
        })
    registry = _load_json(DEFAULT_EVE_SESSION_REGISTRY_PATH, {})
    for session in registry.get("sessions", []):
        session_id = session.get("session_id", "")
        # session_id shape: "eve-<YYYYMMDDTHHMMSSZ>-<hex>" -- real timestamp
        # embedded in the id itself, no separate field on this record.
        at = None
        parts = session_id.split("-")
        if len(parts) >= 2 and len(parts[1]) == 16 and parts[1].endswith("Z"):
            try:
                at = datetime.strptime(parts[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                at = None
        events.append({
            "source": "eve",
            "at": at,
            "summary": f"{session.get('classification', 'unknown')} -- {session.get('reason', '')[:140]}",
        })
    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:cap]


def build_scoreboard(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "last_updated": now.isoformat(),
        "live_scheduler": _live_scheduler_section(),
        "forward_trial": _forward_trial_section(),
        "repair_lab": _repair_lab_section(),
        "graveyard": _graveyard_section(),
        "recent_activity": _recent_activity_section(),
    }


def write_scoreboard(output_path: Path = DEFAULT_OUTPUT_PATH, now: datetime | None = None) -> Path:
    payload = build_scoreboard(now)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    """Never raises -- a script failure must show up in the GitHub Actions
    log but must not fail the workflow step itself (same convention as
    export_quant_metrics.main())."""
    try:
        path = write_scoreboard()
        print(f"Factory Loop scoreboard exported: {path}")
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
