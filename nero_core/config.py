"""Minimal `.env` loader — no external dependency, never logs or returns values.

Populates `os.environ` from a `.env` file at the repo root (`KEY=VALUE` per line,
blank lines and `#` comments skipped). Real process/deployment environment
variables always win: this only fills in a key that isn't already set, so CI or
production secrets injected the normal way are never overridden by a stray local
`.env`.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load `KEY=VALUE` pairs from `path` into `os.environ`, skipping keys that are
    already set. Silently does nothing if `path` doesn't exist — `.env` is optional
    (real deployments use real environment variables instead)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
