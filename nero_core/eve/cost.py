"""Four-field usage cost accounting for Eve's LLM calls.

Reinlines and EXTENDS nero_core.research_agent.hypothesis_gen's own
`_call_cost_usd`/`_web_call_cost_usd` pattern (same pricing constants, same
non-fatal staleness guard) rather than importing it -- matching this
codebase's own established convention (see hypothesis_gen.py's module
docstring: "an underscore-prefixed helper in another module is that module's
own implementation detail, not a shared API to import across modules").

THE EXTENSION (why this module exists rather than just importing Adam's):
usage.input_tokens + usage.output_tokens alone UNDERSTATES the bill whenever
prompt caching is active. Eve resends full conversation history every turn
(see nero_core.eve.session) -- exactly the case where caching should be on,
via `cache_control` breakpoints on the system prompt and the static context
block (see nero_core.eve.llm_client). The Messages API bills all FOUR usage
fields at different multipliers:
  input_tokens                  -- base input rate
  cache_creation_input_tokens   -- 1.25x base rate (writing to the cache)
  cache_read_input_tokens       -- 0.1x base rate (reading from the cache)
  output_tokens                 -- output rate
Under-counting is the one direction the budget ledger must never drift in
(see nero_core.eve.budget_ledger's own module docstring) -- so every field is
summed here, always, even on a call where caching happens to be inactive
(the cache fields are simply absent/zero on Anthropic's own response in that
case, costing nothing extra to always look for).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# Same pricing snapshot as nero_core.research_agent.hypothesis_gen (introductory
# rate through 2026-08-31, source: the Claude API pricing reference, cached
# 2026-06-24) -- kept as an independent copy per this module's own docstring
# above, NOT imported, so a future rate change in one module doesn't need to
# be threaded through the other's private constant.
INPUT_COST_PER_MTOK = 2.00
OUTPUT_COST_PER_MTOK = 10.00
INTRODUCTORY_RATE_EXPIRY = datetime(2026, 8, 31, tzinfo=timezone.utc)

# Anthropic's standard prompt-caching multipliers (Claude API pricing
# reference): writing a NEW cache entry costs 1.25x the base input rate;
# reading an existing (unexpired) one costs 0.1x -- both relative to
# INPUT_COST_PER_MTOK, never a separately-tracked absolute rate, so they stay
# correct automatically if/when the base rate is updated.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

# Same real per-search fee as hypothesis_gen.WEB_SEARCH_COST_PER_SEARCH.
WEB_SEARCH_COST_PER_SEARCH = 0.01


@dataclass(frozen=True)
class CostParameters:
    input_cost_per_mtok: float = INPUT_COST_PER_MTOK
    output_cost_per_mtok: float = OUTPUT_COST_PER_MTOK
    cache_write_multiplier: float = CACHE_WRITE_MULTIPLIER
    cache_read_multiplier: float = CACHE_READ_MULTIPLIER
    web_search_cost_per_search: float = WEB_SEARCH_COST_PER_SEARCH


DEFAULT_COST_PARAMETERS = CostParameters()


def pricing_staleness_warning(now: datetime, params: CostParameters = DEFAULT_COST_PARAMETERS) -> str | None:
    """Non-fatal warning (never raises) if the introductory rate has expired
    but the pricing constants were never updated -- same "surface without
    halting" convention as hypothesis_gen._pricing_staleness_warning. Callers
    append this to the session's own error/notes log, never let it interrupt
    a call."""
    if now < INTRODUCTORY_RATE_EXPIRY:
        return None
    if params.input_cost_per_mtok != INPUT_COST_PER_MTOK or params.output_cost_per_mtok != OUTPUT_COST_PER_MTOK:
        return None
    return (
        f"INTRODUCTORY_RATE_EXPIRY ({INTRODUCTORY_RATE_EXPIRY.date().isoformat()}) has passed but "
        f"nero_core.eve.cost's INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK still hold the introductory "
        f"rate (${INPUT_COST_PER_MTOK:.2f}/${OUTPUT_COST_PER_MTOK:.2f}) -- update to the standard "
        f"$3.00/$15.00 rate; every cost recorded since expiry has under-reported real spend."
    )


def usage_token_breakdown(usage: dict) -> dict:
    """Extracts all four usage fields as ints, defaulting missing/None/absent
    fields to 0 -- NEVER a fabricated non-zero default, so a call that
    genuinely used no caching reports exactly 0 cache tokens, not a guess."""
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
    }


def call_cost_usd(usage: dict, params: CostParameters = DEFAULT_COST_PARAMETERS) -> float:
    """Token-only cost (excludes web-search fees -- see call_cost_usd_with_tools)
    from all four usage fields at their correct multipliers. This is the ONE
    place Eve computes a dollar amount from a Messages API `usage` block --
    every ledger entry (nero_core.eve.budget_ledger) and every session-log
    cost figure (nero_core.eve.session) MUST route through this function, not
    re-derive its own formula."""
    tokens = usage_token_breakdown(usage)
    return (
        (tokens["input_tokens"] / 1_000_000.0) * params.input_cost_per_mtok
        + (tokens["cache_creation_input_tokens"] / 1_000_000.0) * params.input_cost_per_mtok * params.cache_write_multiplier
        + (tokens["cache_read_input_tokens"] / 1_000_000.0) * params.input_cost_per_mtok * params.cache_read_multiplier
        + (tokens["output_tokens"] / 1_000_000.0) * params.output_cost_per_mtok
    )


def web_search_count(usage: dict) -> int:
    """Real search-call count from Anthropic's own reported usage -- see
    hypothesis_gen._web_search_count's identical reasoning (never guessed;
    0 if the key is absent)."""
    server_tool_use = usage.get("server_tool_use") or {}
    return int(server_tool_use.get("web_search_requests", 0) or 0)


def call_cost_usd_with_tools(usage: dict, params: CostParameters = DEFAULT_COST_PARAMETERS) -> float:
    """Token cost (call_cost_usd) PLUS the real per-search fee for however
    many searches Anthropic's own usage reports actually ran this call."""
    return call_cost_usd(usage, params) + web_search_count(usage) * params.web_search_cost_per_search
