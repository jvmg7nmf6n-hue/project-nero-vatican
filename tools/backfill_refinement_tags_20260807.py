"""CC-1 directive, "Fix the REFINEMENT tagging mechanism gap" (2026-08-07),
item 2d: one-time, idempotent backfill applying the fixed
nero_core.eve.scoring.apply_declared_refinement_tags logic to every
already-committed record in docs/site_data/eve_hypotheses.json.

Only ONE real record is affected today: CHANNEL_BREAKOUT_HIGH20_BTC_4H
(session eve-20260806T180819Z-e777cdef), which validly declares
VOL_CONFIRMED_CHANNEL_BREAKOUT_BTC_4H (same session) as its parent but
carried zero contamination tags before this fix -- see scoring.py's own
docstring on apply_declared_refinement_tags for the full root-cause.

nero_core.eve.pipeline.run_pipeline calls the fixed logic automatically
for every NEW session as of this same directive -- this script only ever
touches the fixed, already-written records that predate that code
existing.

known_hypothesis_names here is the GLOBAL set of every hypothesis_name
already present in the file -- safe for a backfill (broader than any
single session's own live known-names universe could ever have been,
since names present today are a superset of whatever existed at any
past session's own proposal time; this can only ever agree with or be
MORE permissive than -- never less permissive than -- what live
validation would have allowed, so it cannot manufacture a validation
that would not also have been real at proposal time).

Idempotent: re-running is a no-op once every record already carries the
REFINEMENT tag its own valid derived_from declaration earns."""
from __future__ import annotations

import json
from pathlib import Path

from nero_core.eve.scoring import apply_declared_refinement_tags

REPO_ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"


def backfill() -> list[str]:
    """Returns the list of hypothesis_names actually changed (empty if
    already all correctly tagged -- the idempotent no-op case)."""
    if not HYPOTHESES_PATH.exists():
        print(f"{HYPOTHESES_PATH} does not exist -- nothing to backfill.")
        return []

    records = json.loads(HYPOTHESES_PATH.read_text(encoding="utf-8"))
    known_hypothesis_names = {
        r["raw_hypothesis"].get("hypothesis_name")
        for r in records
        if isinstance(r.get("raw_hypothesis"), dict) and r["raw_hypothesis"].get("hypothesis_name")
    }

    updated = apply_declared_refinement_tags(records, known_hypothesis_names)

    changed = []
    for before, after in zip(records, updated):
        if before.get("contamination_tags") != after.get("contamination_tags"):
            name = (after.get("raw_hypothesis") or {}).get("hypothesis_name", after.get("tool_use_id"))
            changed.append(name)
            print(f"{name} ({after.get('session_id')}): contamination_tags {before.get('contamination_tags')} -> {after.get('contamination_tags')}")

    if not changed:
        print("Every record already carries the tags its own derived_from declaration earns -- no-op.")
        return []

    HYPOTHESES_PATH.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print(f"Backfilled {len(changed)} record(s): {changed}")
    return changed


if __name__ == "__main__":
    backfill()
