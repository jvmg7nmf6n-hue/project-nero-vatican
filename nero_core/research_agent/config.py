"""Kill switch for the entire Research Agent pipeline (Task 5).

`research_agent.enabled` defaults to FALSE. There is no settings-file system in
this project (nero_core.config is just a .env loader), so this follows the
same convention every other optional/secret-gated behavior in this codebase
uses: an environment variable, read fresh on every call rather than cached at
import time, so a flag flip never needs a code change or a redeploy -- only a
process restart (or, in a test, an explicit `env=` override).

Every entrypoint in nero_core.research_agent (scanner, frequency_gate,
hypothesis_gen, auto_tester, the orchestrating pipeline) MUST check
`is_enabled()` first and no-op when it's False. See test_research_agent_kill_
switch.py for the proof that nothing runs when disabled.
"""
from __future__ import annotations

import os

from nero_core.config import load_dotenv

load_dotenv()  # populates os.environ from a repo-root .env if present

_ENV_VAR = "RESEARCH_AGENT_ENABLED"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_enabled(env: "os._Environ | dict[str, str] | None" = None) -> bool:
    """False unless RESEARCH_AGENT_ENABLED is explicitly set to a truthy value
    ("1", "true", "yes", "on", case-insensitive). Unset, empty, or any other
    value -> disabled. `env` is injectable for tests; defaults to the real
    process environment."""
    source = env if env is not None else os.environ
    return str(source.get(_ENV_VAR, "")).strip().lower() in _TRUE_VALUES
