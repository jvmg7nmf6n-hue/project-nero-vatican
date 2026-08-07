"""CC-1 directive (path-leak fix, 2026-08-07): one-time, idempotent removal
of `forward_tracking_db_ref` from every already-committed record in
docs/site_data/forward_trial.json.

The leak, confirmed exactly: every one of the 10 real records committed to
this public file carries the identical value
`C:\\Users\\<local-username>\\...\\data\\repair_lab_forward_tracking.db` --
an absolute local filesystem path (leaking the machine's username and
directory layout), embedded by `nero_core.research_agent.trial.TrialRecord.
to_dict()` (the field itself, and the `admit_to_trial` parameter that fed
it, were both removed in the same directive -- see trial.py's own updated
docstring). This script only touches the FIXED, already-written file that
predates that code change; `admit_to_trial` no longer produces this field
for any NEW record going forward.

Idempotent: running this twice is a no-op the second time (checks each
record for the key's presence before rewriting)."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORWARD_TRIAL_PATH = REPO_ROOT / "docs" / "site_data" / "forward_trial.json"
LEAKED_FIELD = "forward_tracking_db_ref"


def strip_leak(path: Path = FORWARD_TRIAL_PATH) -> int:
    """Returns the number of records actually changed (0 if already clean --
    the idempotent no-op case)."""
    if not path.exists():
        print(f"{path} does not exist -- nothing to strip.")
        return 0

    records = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for record in records:
        if LEAKED_FIELD in record:
            del record[LEAKED_FIELD]
            changed += 1

    if changed == 0:
        print(f"{path}: no records carry {LEAKED_FIELD!r} -- no-op.")
        return 0

    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"{path}: stripped {LEAKED_FIELD!r} from {changed} record(s).")
    return changed


if __name__ == "__main__":
    strip_leak()
