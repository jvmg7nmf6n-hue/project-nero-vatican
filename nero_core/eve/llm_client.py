"""Eve's multi-turn Claude Messages API client.

MECHANICS REUSED FROM ADAM (values/conventions, not imports -- see module
docstrings throughout nero_core/eve/ on why): raw `requests.post` to the
Messages API (no `anthropic` SDK anywhere in this codebase -- see
nero_core.research_agent.hypothesis_gen._call_claude), model id
"claude-sonnet-5", x-api-key/anthropic-version headers, thinking disabled by
default (same rationale as HypothesisGenParameters.claude_thinking: keeps
cost predictable and structurally rules out the "adaptive thinking silently
eats the whole output budget" failure mode Adam's own diagnostics found).

WHAT'S GENUINELY NEW HERE (not in Adam's client at all, because Adam never
needed it): MULTI-TURN history (a `messages` list built up turn over turn --
see nero_core.eve.session, which owns the loop; this module only issues one
turn at a time) and PROMPT CACHING (`cache_control: {"type": "ephemeral"}`
breakpoints on the system prompt and the static read-only context block --
see build_system_blocks/build_context_user_message). Caching is exactly why
nero_core.eve.cost accounts for all four usage fields instead of Adam's
input+output-only formula: resending full history every turn is expected
behavior here, and caching is what keeps that affordable.

WEB_SEARCH_TOOL is a SERVER-executed tool (Anthropic runs the search and
folds results into the response's own `content` array as `server_tool_use`/
`web_search_tool_result` blocks) -- unlike END_SESSION_TOOL/
PROPOSE_HYPOTHESIS_TOOL (client-defined tools), a web search never pauses the
turn waiting for a client-supplied tool_result. This is why Eve's loop
doesn't need the usual tool_use -> tool_result round trip for search: the
model's own turn simply continues (or ends normally, stop_reason="end_turn")
with the search results already visible to it.

STUB MODE (EVE_STUB_MODE=1, Phase 0): call_turn returns a canned, fully
deterministic 3-turn script instead of making a network call -- the entire
loop/ledger/session-logging/scoring path must run end-to-end against this
before a single real dollar is spent (see test_eve_stub_session_dry_run.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import requests

from nero_core.eve.tools_defs import END_SESSION_TOOL_NAME, PROPOSE_HYPOTHESIS_TOOL_NAME

STUB_MODE_ENV_VAR = "EVE_STUB_MODE"
_TRUE_VALUES = {"1", "true", "yes", "on"}

# Status codes that mean "rejected before any token was ever processed" --
# Anthropic never bills these (confirmed real $0 cost, not an inference from
# usage fields the response never carried). Deliberately narrow: a 500/502/503
# or a network-level failure (timeout, connection error) is NOT included here
# -- those genuinely could have reached the model before failing, so they must
# stay in the conservative "outcome unknown, count the reservation" bucket
# (see budget_ledger's own RESERVE-THEN-RECONCILE section). Widening this set
# to any other status code is a deliberate, reviewed code change, not
# something to infer from a new status code showing up.
REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES = frozenset({401, 403, 429})


class RejectedBeforeTokenProcessingError(Exception):
    """Raised by call_turn instead of letting requests.HTTPError propagate,
    ONLY for a response whose status code is in
    REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES (401 Unauthorized, 403
    Forbidden, 429 Too Many Requests) -- every one of these is rejected by
    an auth/rate-limit layer before the model ever sees the request, so the
    real cost is $0 by construction, never an estimate. nero_core.eve.session
    catches this specifically to RELEASE (not reconcile-as-spent) the
    pre-call budget reservation for this turn -- see budget_ledger.
    release_entry. Any other HTTP error (5xx, a malformed 400, ...) is left
    to propagate as the original requests.exceptions.HTTPError, since those
    could plausibly have reached the model before failing."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_stub_mode(env: "os._Environ | dict[str, str] | None" = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get(STUB_MODE_ENV_VAR, "")).strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class LlmParameters:
    claude_model: str = "claude-sonnet-5"
    claude_api_url: str = "https://api.anthropic.com/v1/messages"
    claude_api_version: str = "2023-06-01"
    claude_max_tokens: int = 4096
    claude_thinking: dict = field(default_factory=lambda: {"type": "disabled"})
    # 180s (was 120s until 2026-08-04, 60s until 2026-08-03): call_turn is a
    # plain, non-streaming requests.post -- the entire response (up to
    # claude_max_tokens, with a full system prompt, context block, and 3 tool
    # definitions on the very first, coldest/largest call) must be generated
    # server-side before any byte returns. Two real, consecutive first-turn
    # sessions hit the old 60s ceiling with a plain ReadTimeout (2026-08-03);
    # a third real attempt (eve-20260804T015806Z-243d095f) hit the SAME
    # failure mode again at the (by-then-current) 120s ceiling on 2026-08-04
    # -- confirming 120s is not consistently sufficient either, not a one-off
    # fluke of the first fix. No HTTP status at all in any of the three
    # cases -- the connection succeeded, the server just hadn't finished by
    # then -- losing the entire session (and a real, conservatively-counted
    # ledger reservation each time -- see budget_ledger.py's own RESERVE-
    # THEN-RECONCILE section) to a margin that was simply too tight, not a
    # connectivity problem (confirmed separately, both times: github.com and
    # api.anthropic.com's own root both responded in under a second at the
    # same time these calls were timing out).
    claude_timeout_seconds: int = 180


DEFAULT_LLM_PARAMETERS = LlmParameters()


@dataclass(frozen=True)
class LlmTurnResult:
    content_blocks: list[dict]
    usage: dict
    stop_reason: str
    raw_response: dict  # full, unparsed -- auditability (spec 2.5)


def build_system_blocks(system_prompt: str) -> list[dict]:
    """The system prompt as a cache-eligible content block -- it is
    identical across every turn of a session, so caching it after the first
    turn means every subsequent turn re-reads it at 0.1x the base input
    rate instead of paying full price for it again."""
    return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]


def build_context_user_message(context_text: str, task_text: str) -> dict:
    """The FIRST user message: a cache-eligible, static read-only context
    block (tracked pairs / graveyard / Adam's verdict-stripped history --
    see nero_core.eve.context) followed by a non-cached task-instructions
    block. Only the context block gets its own cache_control breakpoint --
    it's the large, static part; the task instructions are small and don't
    need one."""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": context_text, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": task_text},
        ],
    }


def build_continue_user_message(text: str = "Continue your research, or call end_session when finished.") -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def build_next_user_message(
    pending_tool_use_blocks: list[dict],
    tool_result_text: "dict[str, str] | str",
    continue_text: str = "Continue your research, or call end_session when finished.",
) -> dict:
    """The message that must follow an assistant turn containing CLIENT-defined
    tool_use blocks (e.g. propose_hypothesis) that aren't end_session (a session
    that called end_session never sends another message at all -- see
    nero_core.eve.session's own loop). Real incident, 2026-08-03: this
    project's first-ever real (non-stub) multi-turn session crashed with a 400
    ("tool_use ids were found without tool_result blocks immediately after")
    because the loop previously just appended a plain continue-text message,
    unconditionally, regardless of whether the prior assistant turn left any
    tool_use call needing a reply. Per the Messages API's own protocol, ONE
    tool_result block is required per pending tool_use id, in the VERY NEXT
    message -- server-executed tools (web_search) never need this (Anthropic
    resolves those within the same assistant turn), only client-defined ones.
    A single combined user message (tool_results first, then the continue
    text) -- not two consecutive user messages, which the API does not expect.

    `tool_result_text` is either ONE string applied to every pending block
    (the original shape -- a plain acknowledgement, same text for all) or a
    dict of tool_use_id -> text, for when different pending calls need
    different replies. Added 2026-08-03 for nero_core.eve.session's DSL
    pre-submit validator (see PROPOSE_HYPOTHESIS_ACK_TEXT / MAX_DSL_RETRIES):
    a propose_hypothesis call that fails the rule-DSL parser must get the
    parser's OWN error message back, not the generic "recorded" ack every
    OTHER pending call in the same turn still gets."""
    if isinstance(tool_result_text, str):
        tool_result_text = {block["id"]: tool_result_text for block in pending_tool_use_blocks}
    content: list[dict] = [
        {"type": "tool_result", "tool_use_id": block["id"], "content": tool_result_text[block["id"]]}
        for block in pending_tool_use_blocks
    ]
    content.append({"type": "text", "text": continue_text})
    return {"role": "user", "content": content}


def assistant_message_from_result(result: LlmTurnResult) -> dict:
    """The literal content blocks Claude returned, re-wrapped as the next
    `assistant` turn in the growing `messages` history -- verbatim, never
    filtered or summarized, so the full reasoning trail is preserved exactly
    as Anthropic returned it (spec 2.5)."""
    return {"role": "assistant", "content": result.content_blocks}


def extract_text(content_blocks: list[dict]) -> str:
    return "".join(b.get("text", "") for b in content_blocks if isinstance(b, dict) and b.get("type") == "text")


def extract_tool_uses(content_blocks: list[dict], tool_name: str | None = None) -> list[dict]:
    """Every client-defined tool_use block (end_session, propose_hypothesis)
    in `content_blocks` -- NOT server_tool_use blocks (web_search), which
    are Anthropic's own server-side invocations, not something Eve's loop
    ever needs to respond to with a tool_result."""
    uses = [b for b in content_blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    if tool_name is not None:
        uses = [b for b in uses if b.get("name") == tool_name]
    return uses


def estimate_tokens_from_chars(text: str) -> int:
    """Conservative char/3.5 estimate -- no tokenizer library is in this
    project's requirements.txt (see nero_core.eve.cost's own "reinline
    rather than add a dependency" discipline); this is the documented
    fallback method (spec 1.3)."""
    return int(len(text) / 3.5)


def estimate_next_call_input_tokens(last_usage: dict | None, new_turn_text: str) -> tuple[int, str]:
    """Returns (estimate, method_label) for the pre-call budget bound (spec
    1.3): 'use the last response's own input_tokens plus the new turn's
    characters/3.5'. `last_usage` is None on the session's first call (no
    prior response to read from) -- falls back to estimating the whole new
    turn from its own character count. On later calls, the estimate is the
    FULL context size the model actually read last time (input_tokens +
    cache_read_input_tokens + cache_creation_input_tokens -- cache-served
    tokens are still real context, just billed at a discount, not tokens
    that didn't exist) plus this new turn's own text -- since the next call
    resends everything the last one saw, plus new content."""
    if last_usage is None:
        return estimate_tokens_from_chars(new_turn_text), "char-fallback (first turn, no prior usage)"
    prior_input = int(last_usage.get("input_tokens", 0) or 0)
    prior_cache_read = int(last_usage.get("cache_read_input_tokens", 0) or 0)
    prior_cache_creation = int(last_usage.get("cache_creation_input_tokens", 0) or 0)
    prior_total_context = prior_input + prior_cache_read + prior_cache_creation
    return prior_total_context + estimate_tokens_from_chars(new_turn_text), "char-fallback (prior total context + new_turn_chars/3.5)"


def _stub_script() -> list[dict]:
    """Canned, fully deterministic 3-turn conversation: one web search, one
    propose_hypothesis call (a DSL-expressible stub hypothesis), one
    end_session call. Every usage block populates all four cost fields at
    least once across the script (turn 0 has no cache fields -- nothing to
    read from cache on the very first call; turns 1-2 have
    cache_read_input_tokens, simulating the system prompt/context cache
    hitting on repeat turns)."""
    return [
        {
            "content": [
                {"type": "text", "text": "I'll start by searching for documented mean-reversion research on the tracked pairs I have access to."},
                {"type": "server_tool_use", "id": "srvtoolu_stub_1", "name": "web_search", "input": {"query": "z-score mean reversion crypto research"}},
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_stub_1",
                    "content": [{"type": "web_search_result", "url": "https://example.com/stub-paper", "title": "Stub mean-reversion paper", "page_age": "2020-01-01"}],
                },
                {"type": "text", "text": "Found a plausible mechanism. I'll formalize it as a hypothesis next turn."},
            ],
            "usage": {"input_tokens": 1200, "output_tokens": 180, "server_tool_use": {"web_search_requests": 1}},
            "stop_reason": "end_turn",
        },
        {
            "content": [
                {"type": "text", "text": "Proposing a DSL-expressible hypothesis based on the stub search result."},
                {
                    "type": "tool_use",
                    "id": "toolu_stub_propose_1",
                    "name": PROPOSE_HYPOTHESIS_TOOL_NAME,
                    "input": {
                        "hypothesis": {
                            "hypothesis_name": "EVE_STUB_ZSCORE_REVERSION",
                            "mechanism": "Stub mechanism for dry-run testing only -- not a real research claim.",
                            "asset": "BTC",
                            "timeframe": "1h",
                            "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
                            "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 48.0},
                        }
                    },
                },
            ],
            "usage": {"input_tokens": 1400, "cache_read_input_tokens": 1100, "output_tokens": 220},
            "stop_reason": "tool_use",
        },
        {
            "content": [
                {"type": "text", "text": "That's my one proposal for this stub run."},
                {
                    "type": "tool_use",
                    "id": "toolu_stub_end_1",
                    "name": END_SESSION_TOOL_NAME,
                    "input": {"summary": "Stub dry-run session: proposed one DSL-expressible hypothesis.", "n_hypotheses_proposed": 1},
                },
            ],
            "usage": {"input_tokens": 1600, "cache_read_input_tokens": 1300, "output_tokens": 90},
            "stop_reason": "tool_use",
        },
    ]


def _stub_call_turn(call_index: int) -> LlmTurnResult:
    script = _stub_script()
    turn = script[min(call_index, len(script) - 1)]
    return LlmTurnResult(
        content_blocks=turn["content"],
        usage=turn["usage"],
        stop_reason=turn["stop_reason"],
        raw_response={"stub": True, "call_index": call_index, **turn},
    )


def call_turn(
    messages: list[dict],
    system_blocks: list[dict],
    tools: list[dict],
    api_key: str,
    params: LlmParameters = DEFAULT_LLM_PARAMETERS,
    stub: bool | None = None,
    call_index: int = 0,
) -> LlmTurnResult:
    """One turn of the conversation: `messages` is the FULL history so far
    (this function does not track state -- nero_core.eve.session owns the
    growing list and appends this call's own result before the next call).
    `stub` overrides EVE_STUB_MODE for tests; None (the default) reads the
    real env var via is_stub_mode()."""
    use_stub = is_stub_mode() if stub is None else stub
    if use_stub:
        return _stub_call_turn(call_index)

    body = {
        "model": params.claude_model,
        "max_tokens": params.claude_max_tokens,
        "thinking": params.claude_thinking,
        "system": system_blocks,
        "messages": messages,
        "tools": tools,
    }
    response = requests.post(
        params.claude_api_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": params.claude_api_version,
            "content-type": "application/json",
        },
        json=body,
        timeout=params.claude_timeout_seconds,
    )
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if response.status_code in REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES:
            raise RejectedBeforeTokenProcessingError(response.status_code, str(exc)) from exc
        # Diagnostic gap found 2026-08-03: a bare `raise` here discarded the
        # response body -- Anthropic's actual validation-error message (the
        # one piece of information that would explain a 400, vs. a generic
        # "400 Client Error" with no detail) was never surfaced anywhere,
        # including in this module's own real-run logs. Re-raised with the
        # body attached, original exception preserved as the cause.
        raise requests.exceptions.HTTPError(f"{exc} -- response body: {response.text[:2000]}", response=response) from exc
    payload = response.json()
    return LlmTurnResult(
        content_blocks=payload.get("content") or [],
        usage=payload.get("usage") or {},
        stop_reason=payload.get("stop_reason") or "",
        raw_response=payload,
    )
