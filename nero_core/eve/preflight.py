"""Preflight API-key validation -- runs BEFORE any real Eve session starts,
so a stale/invalid/misconfigured ANTHROPIC_API_KEY is caught immediately and
loudly, never silently.

WHY THIS EXISTS: nero_core.research_agent ("Adam") went stale-key-401 twice
without anyone noticing for weeks -- nothing validated the key before
spending real turns against it, so the first real signal of the failure was
an empty pipeline, indistinguishable from "found nothing this run." Eve must
not repeat that failure class: this check runs first, and its result gates
whether nero_core.eve.session.run_session is ever called at all.

A minimal, near-zero-cost real Messages API call (max_tokens=1, no tools, no
system prompt, no history) -- NOT a session turn, so it is never ledgered
against the month/session budget (nero_core.eve.budget_ledger). Its real
dollar cost is a few input tokens plus 1 output token, negligible enough
that tracking it as spend would be more noise than signal; what matters here
is PASS/FAIL, not cost. Never a no-op / key-format check -- only an actual
2xx response from Anthropic counts as ok=True.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

from nero_core.eve.llm_client import (
    DEFAULT_LLM_PARAMETERS,
    REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES,
    LlmParameters,
)

PREFLIGHT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    reason: str


def check_api_key(
    api_key: str,
    params: LlmParameters = DEFAULT_LLM_PARAMETERS,
    timeout_seconds: int = PREFLIGHT_TIMEOUT_SECONDS,
) -> PreflightResult:
    """Real, minimal API call to confirm `api_key` is currently valid. An
    empty key fails fast with no network call at all (same $0 cost, same
    loud failure, just faster). Every non-2xx outcome (401/403/429, a 5xx,
    a network error/timeout) is ok=False with a specific reason -- never
    silently treated as "probably fine". Reuses
    REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES from llm_client so this
    check's own notion of "clearly an auth/rate-limit rejection" can never
    silently drift from the one the real session loop uses."""
    if not api_key:
        return PreflightResult(False, "ANTHROPIC_API_KEY is empty/unset")

    try:
        response = requests.post(
            params.claude_api_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": params.claude_api_version,
                "content-type": "application/json",
            },
            json={
                "model": params.claude_model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        return PreflightResult(False, f"network error during preflight check: {exc.__class__.__name__}: {exc}")

    if response.status_code in REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES:
        return PreflightResult(
            False,
            f"HTTP {response.status_code}: key rejected before any token was processed -- likely stale/invalid/rate-limited",
        )
    if not response.ok:
        return PreflightResult(False, f"HTTP {response.status_code}: unexpected preflight failure -- {response.text[:300]}")
    return PreflightResult(True, "ok")
