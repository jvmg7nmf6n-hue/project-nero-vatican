"""CC-1 Factory Loop directive, item 9: live Factory Loop status snapshot.

Follows tools/research_agent_run_summary.py's exact convention: read-only,
computes an aggregate/derived summary (never raw hypothesis text), prints a
human-readable report, then persists to docs/site_data/. UNLIKE that
script's append-only agent_run_summaries.json, this is a point-in-time
SNAPSHOT overwritten in full each run (matching the shape sketched in
docs/investigations/factory_loop_specification.md's own B8) -- there is one
current Factory Loop status, not a history of runs, so there is nothing to
append.

Reads: docs/site_data/forward_trial.json (item 4/5's Trial store),
docs/site_data/graveyard.json + failure_patterns.json (item 6),
docs/site_data/repair_attempts.json (repair_lab.py's own chain event log,
item 5). Never calls run_pipeline, admit_to_trial, or any writer directly --
purely a reader/aggregator over whatever those already wrote.

UNLIKE research_agent_run_summary.py, this DOES import from nero_core
(nero_core.research_agent.repair_lab's reconstruct_chain_state) rather than
reimplementing chain-replay logic locally -- that script's own "reimplement
rather than import nero_core" choice was about avoiding a dependency for 3
trivial read-json-list helpers; reconstructing a repair chain's real status
is non-trivial replay logic (Task 6 of repair_lab.py) that would risk silent
drift from the real implementation if duplicated here. Read-only, no risk of
auto-wiring anything (this script writes nothing repair_lab.py itself reads
back).

KEY NAME (item 8c's locked naming decision): "forward_trial", not "trial" --
the site's EXISTING public "Under Trial" roster tier is a different,
unrelated concept (see website/lib/tier.ts). Both item 8's page and item 9's
export use "Forward Trial"/"forward_trial" consistently.

KNOWN LIMITATION, reported honestly rather than silently guessed: `graveyard.
distilled_this_period` and `graveyard.pending_review` both report 0 always
today -- no committed file currently tracks "distillation drafts pending
human review" as a durable record (graveyard_distillation.draft_
distillation_entry's own output is only ever passed directly to a human
reviewer in memory; nothing persists a draft to disk before approval). This
is a real gap, not a fabricated zero -- see docs/investigations/
factory_loop_implementation_report.md."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nero_core.research_agent.repair_lab import (
    CHAIN_OPEN,
    CHAIN_RESOLVED,
    reconstruct_chain_state,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FORWARD_TRIAL_PATH = REPO_ROOT / "docs" / "site_data" / "forward_trial.json"
GRAVEYARD_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard.json"
FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"
REPAIR_ATTEMPTS_PATH = REPO_ROOT / "docs" / "site_data" / "repair_attempts.json"
STATUS_PATH = REPO_ROOT / "docs" / "site_data" / "factory_loop_status.json"
# CC-1 Master Directive Phase 2: tools.factory_loop_run is the first writer
# of this file (one drafted entry per family reaching DIED_COUNT_TRIGGER,
# at review_status=REVIEW_PENDING) -- closes this module's own previously
# documented KNOWN LIMITATION ("nothing persists a draft to disk before
# approval"). Missing file -> [], same convention as every other JSON list
# this project reads.
DISTILLATION_DRAFTS_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard_distillation_drafts.json"

SCHEMA_VERSION = 1

# item 4b/9b: matches nero_core.research_agent.trial.UNMEASURABLE_HORIZON_YEARS
# -- duplicated as a plain float here (not imported) so this script has no
# import-time dependency beyond repair_lab, keeping its own dependency
# surface minimal and matching research_agent_run_summary.py's own "as few
# imports as the job needs" discipline.
UNMEASURABLE_HORIZON_YEARS = 2.0


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _forward_trial_summary(records: list[dict]) -> dict:
    by_origin = {"adam": 0, "eve": 0, "repaired": 0}
    unmeasurable = 0
    for r in records:
        ref = r.get("source_hypothesis_ref") or {}
        origin = ref.get("origin")
        origin_agent = ref.get("origin_agent")
        key = "repaired" if origin == "repaired" else origin_agent
        if key in by_origin:
            by_origin[key] += 1

        if r.get("status") != "OPEN":
            continue
        years = r.get("projected_time_to_min_sample_years")
        if years is None or years > UNMEASURABLE_HORIZON_YEARS:
            unmeasurable += 1

    return {"count": len(records), "by_origin": by_origin, "unmeasurable_count": unmeasurable}


def _graveyard_summary(graveyard_entries: list[dict], distillation_drafts: list[dict] | None = None) -> dict:
    # `distilled_this_period` stays honestly 0 -- no committed file tracks
    # "distilled in the current period" as a durable, dated record; a real
    # count here would require inventing a period boundary this codebase
    # doesn't define anywhere else. `pending_review` is now real (CC-1
    # Master Directive Phase 2): tools.factory_loop_run drafts entries at
    # review_status=REVIEW_PENDING to DISTILLATION_DRAFTS_PATH, so this
    # counts drafts still at that status -- 0 when the file is missing or
    # every draft has since been approved/rejected, never fabricated.
    drafts = distillation_drafts or []
    pending = sum(1 for d in drafts if isinstance(d, dict) and d.get("review_status") == "pending_human_approval")
    return {"count": len(graveyard_entries), "distilled_this_period": 0, "pending_review": pending}


def _repair_summary(repair_events: list[dict]) -> dict:
    chain_ids = sorted({e.get("repair_chain_id") for e in repair_events if e.get("repair_chain_id")})
    open_chains = 0
    resolved_chains = 0
    for chain_id in chain_ids:
        state = reconstruct_chain_state(chain_id, repair_events)
        if state["chain_status"] == CHAIN_OPEN:
            open_chains += 1
        elif state["chain_status"] == CHAIN_RESOLVED:
            resolved_chains += 1
        # CHAIN_PERMANENTLY_DIED chains are counted in `count` (total chains
        # opened) but in neither open_chains nor resolved_chains -- a
        # permanently-died chain is neither still open nor a Trial-bound
        # resolution, and conflating it with either would misstate it.
    return {"count": len(chain_ids), "open_chains": open_chains, "resolved_chains": resolved_chains}


def compute_summary_data(
    forward_trial_records: list[dict], graveyard_entries: list[dict], repair_events: list[dict],
    distillation_drafts: list[dict] | None = None,
) -> dict:
    """THE ONE PLACE this snapshot's numbers are derived -- pure, no I/O,
    directly testable. main() and any future workflow step both read THIS
    function's output rather than re-deriving the same counts twice."""
    return {
        "forward_trial": _forward_trial_summary(forward_trial_records),
        "graveyard": _graveyard_summary(graveyard_entries, distillation_drafts),
        "repair": _repair_summary(repair_events),
    }


def build_summary(status: dict) -> str:
    ft = status["forward_trial"]
    gy = status["graveyard"]
    rp = status["repair"]
    lines = [
        "Factory Loop status:",
        f"  Forward Trial: {ft['count']} (adam={ft['by_origin']['adam']} eve={ft['by_origin']['eve']} "
        f"repaired={ft['by_origin']['repaired']}, unmeasurable={ft['unmeasurable_count']})",
        f"  Graveyard: {gy['count']} (distilled_this_period={gy['distilled_this_period']} pending_review={gy['pending_review']})",
        f"  Repair: {rp['count']} chains (open={rp['open_chains']} resolved={rp['resolved_chains']})",
    ]
    return "\n".join(lines)


def write_status(summary_data: dict, path: Path = STATUS_PATH) -> None:
    """Full-file overwrite (a point-in-time snapshot, not an append-only
    log) -- atomic via write-to-temp-then-replace, matching this project's
    own convention elsewhere (see append_run_summary's identical pattern)."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        **summary_data,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def main() -> None:
    forward_trial_records = _read_json_list(FORWARD_TRIAL_PATH)
    graveyard_entries = _read_json_list(GRAVEYARD_PATH)
    repair_events = _read_json_list(REPAIR_ATTEMPTS_PATH)
    distillation_drafts = _read_json_list(DISTILLATION_DRAFTS_PATH)

    summary_data = compute_summary_data(forward_trial_records, graveyard_entries, repair_events, distillation_drafts)
    status = {"schema_version": SCHEMA_VERSION, "last_updated": datetime.now(timezone.utc).isoformat(), **summary_data}
    print(build_summary(status))

    write_status(summary_data)
    print(f"\n(status persisted to {STATUS_PATH})")


if __name__ == "__main__":
    main()
