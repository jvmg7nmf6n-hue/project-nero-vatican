"""CC-1 directive, item B0b: one-time, idempotent backfill of a `regime`
field onto every real, already-committed Eve session record under
docs/site_data/eve_sessions/ -- all three predate the inheritance-regime
change (see docs/site_data/eve_session_registry.json's own pre_
registration.inheritance_regime_provenance, item B0a), so all three are
tagged pre_inheritance, not just the one that counts toward the
pre-registered 8 (eve-20260804T020749Z-4cf6e4c9) -- the two crashed/
non-countable sessions also ran under the pre-inheritance system and
must not be left untagged.

nero_core.eve.session.run_session stamps every NEW session record with
CURRENT_SESSION_REGIME (currently post_inheritance) automatically as of
this same directive -- this script only ever touches the fixed, already-
written files that predate that code existing.

Idempotent: running this twice is a no-op the second time (checks each
file's existing `regime` value before rewriting)."""
from __future__ import annotations

import json
from pathlib import Path

from nero_core.eve.session import SESSION_REGIME_PRE_INHERITANCE

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_DIR = REPO_ROOT / "docs" / "site_data" / "eve_sessions"


def backfill() -> list[str]:
    """Returns the list of session_ids actually changed (empty if already
    all tagged -- the idempotent no-op case)."""
    if not SESSIONS_DIR.exists():
        print(f"{SESSIONS_DIR} does not exist -- nothing to backfill.")
        return []

    changed: list[str] = []
    for path in sorted(SESSIONS_DIR.glob("eve-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("regime") == SESSION_REGIME_PRE_INHERITANCE:
            print(f"{path.name}: already tagged {SESSION_REGIME_PRE_INHERITANCE!r} -- no-op.")
            continue
        record["regime"] = SESSION_REGIME_PRE_INHERITANCE
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        changed.append(record.get("session_id", path.stem))
        print(f"{path.name}: tagged regime={SESSION_REGIME_PRE_INHERITANCE!r}.")
    return changed


if __name__ == "__main__":
    backfill()
