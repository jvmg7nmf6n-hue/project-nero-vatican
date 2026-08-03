"""Eve's own output-file I/O -- the ONLY module in nero_core/eve/ that ever
touches the filesystem for Eve's persistent records.

THREE allowlisted output paths, matching the branch's own architecture spec:
  docs/site_data/eve_hypotheses.json
  docs/site_data/eve_budget_ledger.json
  docs/site_data/eve_sessions/<session_id>.json
Every write function below REFUSES (raises DisallowedWritePathError) a path
outside this allowlist -- a structural guarantee, not just a convention, so
the runtime write-path isolation test (test_eve_write_path_isolation.py) is
proving something this module itself already enforces, not merely hoping
every caller behaves.

ATOMIC WRITES (temp file + rename), always: nero_core.research_agent.storage's
own append_json_list does a plain whole-file `path.write_text(...)` -- fine at
that module's own scale/criticality, but Eve's budget ledger is the one thing
in this branch a crash MUST NOT corrupt (see nero_core.eve.budget_ledger's
reserve-then-reconcile discipline), so every write here goes through a
temp-file-in-the-same-directory + os.replace (atomic on both POSIX and
Windows) instead. This is Eve-side hardening on top of the existing
convention, not a modification to Adam's own storage.py, which is untouched.

NOT an import from nero_core.research_agent -- Eve reinlines its own
read/append list logic (same behavior as research_agent.storage.read_json_list/
append_json_list) rather than importing it, per this branch's own isolation
requirement (nero_core/eve/ never imports from nero_core/research_agent/).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"
DEFAULT_BUDGET_LEDGER_PATH = REPO_ROOT / "docs" / "site_data" / "eve_budget_ledger.json"
EVE_SESSIONS_DIR = REPO_ROOT / "docs" / "site_data" / "eve_sessions"

SCHEMA_VERSION = 1


class DisallowedWritePathError(Exception):
    """Raised when a write is attempted to a path outside Eve's three-path
    allowlist. This must be structurally unreachable in real use -- every
    write call site in nero_core/eve/ passes one of DEFAULT_HYPOTHESES_PATH,
    DEFAULT_BUDGET_LEDGER_PATH, or session_record_path(...)."""


def session_record_path(session_id: str) -> Path:
    return EVE_SESSIONS_DIR / f"{session_id}.json"


def _is_allowed_write_path(path: Path) -> bool:
    resolved = Path(path).resolve()
    if resolved == DEFAULT_HYPOTHESES_PATH.resolve():
        return True
    if resolved == DEFAULT_BUDGET_LEDGER_PATH.resolve():
        return True
    sessions_dir_resolved = EVE_SESSIONS_DIR.resolve()
    return resolved.parent == sessions_dir_resolved and resolved.suffix == ".json"


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    if not _is_allowed_write_path(path):
        raise DisallowedWritePathError(
            f"{path} is not one of Eve's allowlisted output paths "
            f"({DEFAULT_HYPOTHESES_PATH}, {DEFAULT_BUDGET_LEDGER_PATH}, {EVE_SESSIONS_DIR}/<session_id>.json)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)  # atomic on POSIX and Windows (both same-volume, same dir)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json_list(path: Path) -> list[dict]:
    """[] if missing or unparseable -- same fail-independent contract as
    nero_core.research_agent.storage.read_json_list (reinlined, not imported;
    see module docstring). A corrupted (not merely missing) file logs a loud
    stderr ERROR before degrading to []."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: {path} is corrupted (JSONDecodeError: {exc}) -- treating as empty. "
            f"Restore it from git history before the next write, or its prior content will be "
            f"permanently lost.",
            file=sys.stderr,
        )
        return []
    return data if isinstance(data, list) else []


def atomic_write_json_list(path: Path, items: list[dict]) -> None:
    _atomic_write_text(path, json.dumps(items, indent=2) + "\n")


def append_json_list(path: Path, new_items: list[dict]) -> None:
    """No-op on empty new_items (never rewrites/bumps mtime), otherwise an
    atomic read-modify-write of the whole list -- see module docstring for
    why this is atomic where research_agent.storage's own version isn't."""
    if not new_items:
        return
    existing = read_json_list(path)
    existing.extend(new_items)
    atomic_write_json_list(path, existing)


def read_json_dict(path: Path) -> dict | None:
    """None if missing or unparseable. Used for the per-session record file
    (a single JSON object, not an append-only list)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} is corrupted (JSONDecodeError: {exc}) -- treating as absent.", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def atomic_write_json_dict(path: Path, data: dict) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")
