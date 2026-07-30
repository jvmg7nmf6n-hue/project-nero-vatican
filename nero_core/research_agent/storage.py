"""Shared append-only JSON list read/write helpers for the Research Agent's
docs/site_data/*.json exports (agent_hypotheses.json, agent_test_results.json).

Every write reads the current file (or starts from an empty list), appends
the new items, and writes back the whole list -- matching every other
docs/site_data/*.json export in this codebase (a plain json.dumps(..., indent=2)
of the full current state, e.g. nero_core.execution.export_quant_metrics).
True database-style atomic append isn't warranted at this project's scale (a
handful of hypotheses per run)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def read_json_list(path: Path) -> list[dict]:
    """[] (never an error) if the file is missing or unparseable -- a fresh
    deployment or a corrupted export must never crash the pipeline, matching
    this project's fail-independent convention elsewhere (e.g.
    export_quant_metrics's per-file try/except). A CORRUPTED file (as opposed
    to a merely-missing one) still degrades to [] -- crashing the whole run
    over one bad file would be worse -- but does so LOUDLY: this silently
    returning [] previously meant a corrupted agent_hypotheses.json looked
    identical to "no history yet," defeating duplicate detection (every
    finding re-proposed) with zero trace, and a corrupted file passed to
    append_json_list gets its entire prior content silently overwritten by
    just the new items on the next write."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: {path} is corrupted (JSONDecodeError: {exc}) -- treating as empty. "
            f"Restore it from git history before the next run, or its prior content will be "
            f"permanently lost on the next write.",
            file=sys.stderr,
        )
        return []
    return data if isinstance(data, list) else []


def append_json_list(path: Path, new_items: list[dict]) -> None:
    """No-op on an empty `new_items` -- never rewrites the file (and never
    bumps its mtime) when there is nothing new to record."""
    if not new_items:
        return
    existing = read_json_list(path)
    existing.extend(new_items)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n")
