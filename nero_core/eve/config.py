"""Kill switch for the entire Eve engine.

Eve is a sibling system to nero_core.research_agent ("Adam"), built in total
isolation from it -- see test_eve_no_auto_wire.py. This module mirrors
nero_core.research_agent.config's own EVE_ENABLED/is_enabled convention
exactly (same env-var pattern, same default-False, same injectable `env` for
tests) rather than inventing a new one: this codebase already has exactly one
established convention for an optional/secret-gated pipeline's kill switch,
and Eve should not diverge from it for no reason.

Every entrypoint in nero_core.eve (session, pipeline) MUST check is_enabled()
first and no-op when it's False.
"""
from __future__ import annotations

import os

from nero_core.config import load_dotenv

load_dotenv()  # populates os.environ from a repo-root .env if present

_ENV_VAR = "EVE_ENABLED"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_enabled(env: "os._Environ | dict[str, str] | None" = None) -> bool:
    """False unless EVE_ENABLED is explicitly set to a truthy value ("1",
    "true", "yes", "on", case-insensitive). Unset, empty, or any other value
    -> disabled. `env` is injectable for tests; defaults to the real process
    environment."""
    source = env if env is not None else os.environ
    return str(source.get(_ENV_VAR, "")).strip().lower() in _TRUE_VALUES
