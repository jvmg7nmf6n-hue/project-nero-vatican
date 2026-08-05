"""Task 3 -- Hypothesis Generator (LLM).

Turns one Task-1 scan finding into one candidate trading hypothesis via the
Claude Messages API, following nero_core.strategies.news_sentiment_llm's own
working pattern (the project's existing "ChatBot" reference: raw `requests`
POST to the Messages API, x-api-key header, strip markdown fences, scan the
`content` array by block `type` rather than assuming position -- claude-
sonnet-5 can prepend a `thinking` block before its text reply). The text-
extraction helpers below are a deliberate RE-INLINE of that module's own
`_extract_text`/`_strip_markdown_json`, not an import -- this codebase's own
precedent (nero_core.quant.cross_asset re-inlining quant_intelligence's
private `_safe_corr` rather than importing it) is that an underscore-prefixed
helper in another module is that module's own implementation detail, not a
shared API to import across modules.

DUPLICATE DETECTION (before any LLM call, so a duplicate never costs a call):
`check_duplicate` matches on the EXACT (scan_finding_type, asset, timeframe)
tuple against every already-recorded hypothesis (including ones generated
earlier in the SAME run). Deliberately coarse -- no fuzzy text similarity, no
embeddings -- so the method is fully auditable from the reported reason
string alone. A false negative here just costs one avoidable LLM call (or,
worse, a near-duplicate hypothesis that Task 4's own harness will kill on
its statistical merits anyway); a false positive would silently suppress a
genuinely new angle on the same market, which this coarseness avoids.

COST CONTROL: `max_calls_per_run` (default DEFAULT_MAX_CALLS_PER_RUN) caps how
many LLM calls a single run may make; the run stops and reports
`cost_limit_hit=True` rather than continuing. Every call's cost is computed
from the response's own `usage.input_tokens`/`usage.output_tokens` (never
estimated) at CLAUDE_PRICING's per-MTok rates and summed into
`total_cost_usd`.

PREFLIGHT KEY VALIDATION (added 2026-07-29, after a real run made 3 doomed
calls before this existed): before the per-finding loop, one minimal call
confirms the key is actually accepted. A 401 stops the run immediately with
ONE recorded error instead of repeating the same failure once per finding --
see validate_api_key/ApiKeyRejectedError.

Output schema per hypothesis (docs/site_data/agent_hypotheses.json, append-
only): scan_finding, scan_finding_type (added -- needed for duplicate
detection and for Task 7's UI to group/filter), hypothesis_name, mechanism,
entry_rule (human-readable), structured_entry_rule (machine-checkable form
consumed by frequency_gate.py/auto_tester.py via nero_core.research_agent.
rule_dsl -- null if the LLM says the rule can't be expressed that way, NEVER
force-mapped), exit_rule, stop_rule, structured_exit_plan (added -- a
hypothesis's entry_rule alone isn't enough to run a real backtest; auto_tester.py
(Task 4) also needs a machine-checkable exit/stop shape to compute R-multiples
at all, so this asks for the same {"stop_atr_multiple", "target_r_multiple",
"max_holding_hours"} shape rule_dsl.parse_exit_plan expects, null if
inexpressible -- same "never guess" principle as structured_entry_rule, just
applied to the other half of a testable trade definition), asset, timeframe,
differs_from_graveyard, expected_frequency_claim (the LLM's own guess --
recorded for reference only; this project never asks the LLM for a frequency
and never trusts this number for a gating decision, see frequency_gate.py),
generated_at, cost_usd, source.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from nero_core.research_agent.scanner import ScanFinding
from nero_core.research_agent.storage import append_json_list, read_json_list

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"
# Same file scanner.py's own low_strategy_coverage check already reads as the
# tracked-universe source of truth -- reused here (not re-globbed from
# docs/site_data/candles/ directly) so web-sourced generation and the scanner
# agree on what "currently tracked" means from the exact same export.
DEFAULT_QUANT_METRICS_PATH = REPO_ROOT / "docs" / "site_data" / "quant_metrics.json"

DEFAULT_MAX_CALLS_PER_RUN = 10

# Web-sourced discovery (added 2026-07-31): a SEPARATE, independent channel and
# budget from the scanner path above -- Part 1 of this investigation confirmed
# the Research Agent's own GitHub Actions workflow (research_agent_manual.yml)
# is workflow_dispatch-ONLY (no `schedule:` block), so run frequency is already
# human-gated; the two channels are kept on separate caps so neither silently
# starves the other of the same fixed budget, not because of a scheduling risk.
# Deliberately conservative for the first real run (10x smaller than the
# scanner path's own cap) given the higher per-hypothesis cost below -- raise
# once real cost data from actual use justifies it.
DEFAULT_WEB_MAX_CALLS_PER_RUN = 3

# Pricing effective 2026-07-29 (introductory rate through 2026-08-31): $2.00
# input / $10.00 output per MTok for claude-sonnet-5. Reverts to the standard
# $3.00/$15.00 per MTok after that date -- update these two constants then.
# Source: the Claude API pricing reference, cached 2026-06-24.
# Phase 2 Fix F (docs/investigations/phase2_pending_cleanup_report.md):
# _pricing_staleness_warning below fires a non-fatal, ledger-visible warning
# if INTRODUCTORY_RATE_EXPIRY passes and these two are still un-updated.
INPUT_COST_PER_MTOK = 2.00
OUTPUT_COST_PER_MTOK = 10.00

INTRODUCTORY_RATE_EXPIRY = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _pricing_staleness_warning(now: datetime) -> str | None:
    """Non-fatal, ledger-visible warning if the introductory rate has expired
    but INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK were never updated to the
    reverted standard rate -- follows the SAME "surface without halting"
    convention validate_api_key's own non-401 preflight note already uses
    (see that function's docstring): appended to `errors` as one more entry,
    never raised, since a wrong per-MTok constant doesn't invalidate any
    single call the way a rejected key does -- it just means every cost
    recorded from here on quietly understates real spend, which is exactly
    the kind of silent drift this project's own discipline treats as a bug
    worth a permanent, queryable trace rather than a crash."""
    if now < INTRODUCTORY_RATE_EXPIRY:
        return None
    if INPUT_COST_PER_MTOK != 2.00 or OUTPUT_COST_PER_MTOK != 10.00:
        return None
    return (
        f"INTRODUCTORY_RATE_EXPIRY ({INTRODUCTORY_RATE_EXPIRY.date().isoformat()}) has passed but "
        f"INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK still hold the introductory rate "
        f"(${INPUT_COST_PER_MTOK:.2f}/${OUTPUT_COST_PER_MTOK:.2f}) -- update to the standard "
        f"$3.00/$15.00 rate; every cost recorded since expiry has under-reported real spend."
    )

# Anthropic's server-side web_search tool: $10 per 1,000 searches ($0.01/search),
# billed ON TOP OF normal token costs for the search results injected into
# context -- confirmed via the pricing note in this task's own approval, not
# guessed. A web-sourced hypothesis's real cost is token cost (see
# INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK above) PLUS this per-search fee --
# see _web_search_count/_web_call_cost_usd below for how the two are combined.
WEB_SEARCH_COST_PER_SEARCH = 0.01

# web_search_20260209 is the dynamic-filtering tool variant (code execution
# runs under the hood for result filtering -- do NOT also declare a standalone
# code_execution tool alongside it, per the Claude API's own guidance, since a
# second execution environment would confuse the model). Confirmed compatible
# with claude-sonnet-5 (this module's own claude_model default) -- the
# _20260209 variants require Opus 5/4.8/4.7/4.6, Sonnet 5, or Sonnet 4.6.
# max_uses caps search calls WITHIN one hypothesis-generation request -- a
# cost safety net independent of DEFAULT_WEB_MAX_CALLS_PER_RUN, which caps how
# many separate hypothesis-generation REQUESTS a run makes.
WEB_SEARCH_TOOL: dict = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

# Rule 2 (source quality must be recorded, not just the idea): recorded for
# transparency/audit, never used to skip, weight, or soften the frequency gate
# or auto_tester -- see check_graveyard_match's own docstring and
# test_research_agent_web_hypothesis_gen.py's no-special-treatment test.
#
# Expanded from 4 to 6 tiers (2026-07-31): the original "trading_forum_social_media"
# tier merged Reddit-style threaded discussion with Twitter/X-style short posts --
# two sources with different verifiability -- into one bucket, and had no tier at
# all for an independent blog/newsletter, which fell into unknown_unverifiable
# indistinguishable from a genuinely unclassifiable source. source_tier is assigned
# once at generation time and never re-derivable later, so a coarse schema
# permanently loses "which source types actually produce SURVIVED hypotheses" --
# this expansion exists purely for that future analysis; it does not change how
# any tier is used today (still metadata only, see the docstring above).
SOURCE_TIERS = (
    "peer_reviewed_academic",
    "established_financial_publication",
    "independent_blog_or_newsletter",
    "forum_discussion",
    "social_media_post",
    "unknown_unverifiable",
)


@dataclass(frozen=True)
class HypothesisGenParameters:
    claude_model: str = "claude-sonnet-5"
    claude_api_url: str = "https://api.anthropic.com/v1/messages"
    claude_api_version: str = "2023-06-01"
    # Diagnostics finding (2026-07-30): a real Actions run billed $0.021354 for
    # a response whose ENTIRE content array was one thinking block with
    # thinking="" and zero text blocks -- claude-sonnet-5 runs adaptive
    # thinking by default when `thinking` is omitted (confirmed against the
    # Claude API's own current model reference), and that thinking exhausted
    # the old max_tokens=1500 budget before any JSON could be written.
    #
    # Two changes, not either/or:
    # 1. `claude_thinking` (below) explicitly disables thinking --
    #    `{"type": "disabled"}` is documented as cleanly supported on
    #    claude-sonnet-5, unlike claude-fable-5 where it 400s. With thinking
    #    off, this failure mode -- adaptive thinking silently consuming the
    #    whole budget -- is structurally impossible, not just less likely.
    # 2. max_tokens is still raised, sized off the ACTUAL 11-key JSON schema
    #    this call asks for (hypothesis_name, mechanism, entry_rule,
    #    structured_entry_rule {conditions:[...]}, exit_rule, stop_rule,
    #    structured_exit_plan {stop_atr_multiple, target_r_multiple,
    #    max_holding_hours}, asset, timeframe, differs_from_graveyard,
    #    expected_frequency_claim), not copied from news_sentiment_llm's
    #    single-field classification (800) or the ChatBot's conversational
    #    reply (1024) -- both answer a much smaller shape than this one.
    #    A representative filled-in instance of this schema (2-3 sentence
    #    mechanism, 3-condition structured_entry_rule, full exit plan,
    #    2-sentence differs_from_graveyard) serializes to ~450 tokens
    #    (measured via json.dumps char-count / 3.5 chars-per-token). Tripling
    #    that for verbosity variance (longer prose fields, more entry
    #    conditions) gives ~1350 tokens; 2048 leaves ~700 tokens of margin
    #    above that -- comfortable without being an arbitrary round number.
    #    Since thinking is now disabled, none of this budget is spent on
    #    thinking (that was the old failure's entire mechanism) -- it is
    #    pure output headroom.
    claude_max_tokens: int = 2048
    claude_thinking: dict = field(default_factory=lambda: {"type": "disabled"})
    # 180s (was 30s, then 90s via the CC-1 review's own item A2, which
    # itself proved insufficient on the very next real manual run -- 3/3
    # web-search calls hit ReadTimeout again at 90s on 2026-08-04). The
    # web-search channel (generate_web_hypotheses, tools=[WEB_SEARCH_TOOL])
    # waits on Anthropic's own server-side search execution before any byte
    # returns, the same "coldest/largest call, non-streaming requests.post"
    # shape that made Eve's own claude_timeout_seconds insufficient at 60s,
    # then 120s, before landing at 180s (see nero_core.eve.llm_client.
    # LlmParameters's own docstring) -- matching that already-proven value
    # here rather than guessing at a third intermediate number.
    claude_timeout_seconds: int = 180
    input_cost_per_mtok: float = INPUT_COST_PER_MTOK
    output_cost_per_mtok: float = OUTPUT_COST_PER_MTOK


DEFAULT_PARAMETERS = HypothesisGenParameters()

HYPOTHESIS_JSON_KEYS = (
    "hypothesis_name", "mechanism", "entry_rule", "structured_entry_rule",
    "exit_rule", "stop_rule", "structured_exit_plan", "asset", "timeframe",
    "differs_from_graveyard", "expected_frequency_claim",
)


class NoTextBlockError(ValueError):
    """Raised when a Claude Messages API response has no usable text content
    block -- see nero_core.strategies.news_sentiment_llm's own class of the
    same name/purpose (re-inlined here, not imported -- see module docstring)."""


def _extract_text(content: object) -> str:
    """Scans a Messages API `content` array by block `type` (never assumes
    content[0] is the text block -- claude-sonnet-5 can prepend one or more
    `thinking` blocks first). Concatenates every text block found, in order."""
    blocks = content if isinstance(content, list) else []
    text_parts = [
        block["text"]
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    if not text_parts:
        raise NoTextBlockError(f"No text content block in Claude response; content={content!r:.500}")
    return "".join(text_parts)


def _strip_markdown_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    if stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    return match.group(0) if match else stripped.strip()


@dataclass(frozen=True)
class DuplicateCheckResult:
    is_duplicate: bool
    method: str
    matched_hypothesis_name: str | None = None


def _mechanism_family_key(finding_type: str, asset: str, timeframe: str | None) -> str:
    return f"{finding_type}|{asset}|{timeframe or ''}"


def check_duplicate(finding: ScanFinding, existing_hypotheses: list[dict]) -> DuplicateCheckResult:
    """Similarity method (reported verbatim in the returned `method` string,
    per this task's own "similarity ka tareeqa report karein" requirement):
    exact match on (scan_finding_type, asset, timeframe) against every already-
    recorded hypothesis. See module docstring for why this coarse method was
    chosen over fuzzy text/embedding similarity."""
    key = _mechanism_family_key(finding.finding_type, finding.asset, finding.timeframe)
    for existing in existing_hypotheses:
        existing_key = _mechanism_family_key(
            existing.get("scan_finding_type", ""), existing.get("asset", ""), existing.get("timeframe")
        )
        if existing_key == key:
            return DuplicateCheckResult(
                True,
                f"exact match on (scan_finding_type, asset, timeframe)=({finding.finding_type!r}, "
                f"{finding.asset!r}, {finding.timeframe!r}) against an existing hypothesis",
                existing.get("hypothesis_name"),
            )
    return DuplicateCheckResult(
        False, f"no existing hypothesis shares (scan_finding_type, asset, timeframe)=({finding.finding_type!r}, "
        f"{finding.asset!r}, {finding.timeframe!r})",
    )


def _format_failure_patterns(failure_patterns: list[dict]) -> str:
    if not failure_patterns:
        return "(none on file)"
    lines = []
    for p in failure_patterns:
        line = f"- {p.get('name')} ({p.get('family')}): failure_pattern={p.get('failure_pattern')}"
        if p.get("fix_rationale"):
            line += f"; fix_rationale={p['fix_rationale']}"
        lines.append(line)
    return "\n".join(lines)


def _build_prompt(finding: ScanFinding, failure_patterns: list[dict]) -> str:
    freq_line = (
        f"Historically, this exact condition has measured {finding.measured_frequency_per_year:.1f} "
        f"occurrences/year on this asset/timeframe ({finding.measurement_note})"
        if finding.measured_frequency_per_year is not None
        else f"No reliable historical frequency is available for this exact condition yet ({finding.measurement_note})."
    )

    return f"""You are a quantitative research assistant for Project Vatican, a paper-trading
research platform (never real-money execution) for gold, crypto, forex, and stocks.
You are given ONE factual market scan finding and must propose ONE new trading
hypothesis to test.

SCAN FINDING: {finding.description}
{freq_line}

KNOWN DEAD MECHANISMS (never propose a hypothesis whose core mechanism matches one of
these -- they have already been tested on this platform and failed):
{_format_failure_patterns(failure_patterns)}

CRITICAL REQUIREMENT: Vatican needs hypotheses that generate AT LEAST 20-30 trades per
year. A mechanism that only fires 2-3 times per year is USELESS for this platform no
matter how sound the reasoning is, because it would take years to accumulate enough
resolved trades to know whether it actually works. Design the entry condition to be
FREQUENT, not rare.

Return STRICT JSON only, with exactly these keys and no others:
- hypothesis_name: a short unique identifier, e.g. "ZSCORE_REVERSION_BTC_1H"
- mechanism: 2-3 sentences on WHY this should work
- entry_rule: a precise, human-readable entry condition
- structured_entry_rule: a machine-checkable version of entry_rule, shaped exactly as
  {{"conditions": [{{"field": <field>, "op": <op>, "value": <number>}}, ...]}} (multiple
  conditions are ANDed together). Allowed fields: close, ma20, ma50, ma200, zscore20,
  atr14, rsi14, ret_1, volume. Allowed ops: gt, gte, lt, lte, eq, cross_above, cross_below.
  Each condition's right-hand side is EITHER a fixed "value" (a number) OR a
  "compare_to_field" naming another one of the allowed fields above -- exactly one of
  the two, never both. Use "compare_to_field" for a moving-average crossover or any
  other relationship BETWEEN two of these fields, e.g. a golden cross is
  {{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}}; use "value" for a
  comparison against a fixed level, e.g. {{"field": "rsi14", "op": "lt", "value": 30}}.
  If the entry condition genuinely cannot be expressed with these fields/ops, set
  structured_entry_rule to null -- do NOT force an approximate mapping.
- exit_rule: a precise exit condition
- stop_rule: a precise stop-loss condition
- structured_exit_plan: a machine-checkable exit/stop shape, shaped exactly as
  {{"stop_atr_multiple": <number>, "target_r_multiple": <number>, "max_holding_hours":
  <number>}} -- stop_atr_multiple is the ATR-multiple distance from entry to stop,
  target_r_multiple is the reward target expressed as a multiple of that same risk
  distance (e.g. 2.0 means a 2R target), max_holding_hours is a maximum holding period
  before a time-based exit. All three must be positive numbers. If exit_rule/stop_rule
  genuinely cannot be expressed this way, set structured_exit_plan to null -- do NOT
  force an approximate mapping.
- asset: the asset this applies to (default to the scan finding's own asset if unsure)
- timeframe: the timeframe this applies to
- differs_from_graveyard: 1-2 sentences on how this differs from every dead mechanism
  listed above
- expected_frequency_claim: your own numeric estimate of trades/year (a float) -- this
  is recorded for reference ONLY. Vatican independently MEASURES the real historical
  frequency from candle data and will reject this hypothesis if the measured number
  doesn't clear the 20-30/year bar above, regardless of what you estimate here.

Do not include any field other than these ten."""


class ResponseParseError(Exception):
    """Raised when a Claude Messages API response comes back 2xx -- meaning
    Anthropic PROCESSED and BILLED the request -- but this module can't
    extract a usable hypothesis from it (no text block, or the text isn't
    valid JSON). Carries `usage` (the response's own token counts, read
    BEFORE either parsing step that can raise) so the caller can still
    record the real cost of a billed-but-unusable call, instead of silently
    reporting $0.00 for a call Anthropic charged for. Without this, a 200
    response with malformed output looked identical -- in cost terms -- to a
    call that never reached Anthropic at all (see this module's own TIER 4
    diagnostics finding: total_llm_cost_usd is only ever incremented on a
    fully successful parse)."""

    def __init__(self, message: str, usage: dict):
        super().__init__(message)
        self.usage = usage


# CC-1 review, item A3 -- confirmed gap: 3 real ReadTimeout calls previously
# fell into the same generic `except requests.RequestException` branch as
# every other transport failure and were recorded as "nothing billed" --
# literally $0.000000 in total_llm_cost_usd, indistinguishable from a call
# that never reached Anthropic's servers at all. A ReadTimeout means the
# CONNECTION succeeded and the request was sent -- Anthropic's server may
# have already started (and billed) processing before the response timed
# out client-side; the real cost is UNKNOWN, not confirmed zero. Mirrors
# nero_core.eve.llm_client.RejectedBeforeTokenProcessingError's own
# confirmed-vs-unknown distinction exactly (401/403/429 = rejected before
# any token was processed = a REAL, confirmed $0, never billed) --
# reinlined here rather than imported, since Adam and Eve stay two fully
# independent systems with no cross-import between them (see this module's
# own DataSourceRefusedError precedent in pipeline.py).
REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES = frozenset({401, 403, 429})


class RejectedBeforeTokenProcessingError(Exception):
    """Raised by _call_claude ONLY for a response whose status code is in
    REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES -- every one of these is
    rejected by an auth/rate-limit layer before the model ever sees the
    request, so the real cost is confirmed $0, not an estimate. Any OTHER
    failure (ReadTimeout, ConnectionError, a 5xx, a malformed 400) is left
    to propagate as the original requests.exceptions.RequestException,
    since those could plausibly have reached the model (and been billed)
    before failing -- callers must count those as UNKNOWN cost, never a
    confirmed $0."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _call_claude(
    prompt: str, api_key: str, params: HypothesisGenParameters, tools: list[dict] | None = None
) -> tuple[dict, dict]:
    """Returns (parsed_json_data, usage_dict). Raises requests.RequestException
    on a transport/HTTP-status failure (nothing billed, no usage available) or
    ResponseParseError on a 2xx response this module can't parse (billed --
    carries `usage`) -- the caller (generate_hypotheses) is responsible for
    catching and recording either, matching this project's existing per-call
    error handling convention (news_sentiment_llm.analyze_headline).

    `tools` (added for web-sourced generation -- see generate_web_hypotheses):
    when given, added to the request body as-is (e.g. [WEB_SEARCH_TOOL]) --
    the scanner path's own calls never pass this, so its request body is
    byte-for-byte unchanged from before this parameter existed."""
    body = {
        "model": params.claude_model,
        "max_tokens": params.claude_max_tokens,
        "thinking": params.claude_thinking,
        "messages": [{"role": "user", "content": prompt}],
    }
    if tools:
        body["tools"] = tools
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
        raise
    payload = response.json()
    usage = payload.get("usage") or {}
    try:
        text = _extract_text(payload.get("content")).strip()
        data = json.loads(_strip_markdown_json(text))
    except (NoTextBlockError, json.JSONDecodeError) as exc:
        raise ResponseParseError(f"{exc.__class__.__name__}: {exc}", usage) from exc
    return data, usage


class ApiKeyRejectedError(Exception):
    """Raised by validate_api_key when a preflight call to the Claude API
    returns 401 Unauthorized -- the key is PRESENT but not accepted. Distinct
    from an empty api_key (handled separately, before any call is ever made,
    per-finding) and from a transient per-hypothesis failure (network blip,
    malformed response): a 401 is structural -- every subsequent call in this
    run would fail the exact same way, so generate_hypotheses stops here
    rather than spending the rest of the run's call budget finding that out N
    times. Added 2026-07-29 after a real run made 3 doomed calls (one per
    scan finding, $0 spent since 401s aren't billed) before this check
    existed. The message never carries the api_key value."""


def validate_api_key(api_key: str, params: HypothesisGenParameters = DEFAULT_PARAMETERS) -> str | None:
    """One minimal (max_tokens=1) preflight call. Raises ApiKeyRejectedError
    ONLY on a 401 response -- that failure mode is guaranteed to repeat on
    every subsequent call, so it's worth stopping the whole run for; every
    other failure surfaces normally, per-hypothesis, in generate_hypotheses's
    own main loop, and is NOT treated as fatal here.

    Returns None on a normal/inconclusive outcome (200, or a non-401 status).
    Returns a short descriptive message (never raises) when the preflight
    request itself couldn't complete (network/timeout/DNS/SSL) -- previously
    a bare `return`, this failure left ZERO trace anywhere; the caller now
    records the returned message as a non-fatal note before proceeding to
    the real per-finding calls."""
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
                "thinking": params.claude_thinking,
                "messages": [{"role": "user", "content": "Hi"}],
            },
            timeout=params.claude_timeout_seconds,
        )
    except requests.RequestException as exc:
        return f"preflight key check did not complete: {exc.__class__.__name__}: {exc}"
    if response.status_code == 401:
        raise ApiKeyRejectedError(
            "ANTHROPIC_API_KEY is present but was rejected (401 Unauthorized) by the Claude API. "
            "No further calls were attempted this run -- check the key's validity before retrying."
        )
    return None


def _call_cost_usd(usage: dict, params: HypothesisGenParameters) -> float:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return (input_tokens / 1_000_000.0) * params.input_cost_per_mtok + (output_tokens / 1_000_000.0) * params.output_cost_per_mtok


def _web_search_count(usage: dict) -> int:
    """Real search-call count from Anthropic's own reported usage, NEVER
    guessed or estimated: the Messages API reports server-tool invocation
    counts under usage.server_tool_use.web_search_requests. Returns 0 (not a
    fabricated default) if that key is absent -- e.g. a response that never
    reached the tool-use step, or a provider/response shape this hasn't been
    observed against yet."""
    server_tool_use = usage.get("server_tool_use") or {}
    return int(server_tool_use.get("web_search_requests", 0) or 0)


def _web_call_cost_usd(usage: dict, params: HypothesisGenParameters) -> float:
    """Token cost (identical formula to _call_cost_usd) PLUS the real
    per-search fee ($0.01/search, WEB_SEARCH_COST_PER_SEARCH) for however many
    searches Anthropic's own usage reports actually ran -- see the pricing
    note in this module's WEB_SEARCH_COST_PER_SEARCH docstring. Never assumes
    a search occurred that isn't reflected in `usage` itself."""
    return _call_cost_usd(usage, params) + _web_search_count(usage) * WEB_SEARCH_COST_PER_SEARCH


# --- Graveyard check (Rule 4: applies equally regardless of web vs scanner
# origin -- see this module's own docstring update below and
# test_research_agent_hypothesis_gen.py's cross-origin test) ------------------

# Deliberately small and generic -- filtered out before the overlap check so a
# real repeat isn't masked by two mechanisms merely sharing common English
# connective words, not the substance of the mechanism itself.
_GRAVEYARD_STOPWORDS = frozenset({
    "this", "that", "these", "those", "with", "from", "into", "than", "then",
    "each", "both", "near", "real", "only", "over", "such", "less", "more",
    "will", "have", "been", "were", "when", "what", "which", "while", "does",
    "would", "could", "should", "about", "after", "before", "under", "above",
})

# Overlap coefficient (intersection / smaller-set size), not Jaccard (which
# would dilute against a long fix_rationale paragraph): a short hypothesis
# mechanism sharing most of its distinctive words with EITHER a short `name`+
# `family` pair OR a long `fix_rationale` should count as a real match either
# way -- Jaccard's union-based denominator would silently under-flag the
# long-text case. Threshold chosen to require substantial, not incidental,
# overlap -- see test_research_agent_hypothesis_gen.py for the calibration
# checks (a real near-repeat clears it; an unrelated mechanism does not).
GRAVEYARD_OVERLAP_THRESHOLD = 0.35


@dataclass(frozen=True)
class GraveyardCheckResult:
    is_likely_repeat: bool
    method: str  # human-readable, always names the matched pattern + overlap when True
    matched_pattern_name: str | None = None


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 4 and w not in _GRAVEYARD_STOPWORDS}


def check_graveyard_match(hypothesis_name: str, mechanism: str, failure_patterns: list[dict]) -> GraveyardCheckResult:
    """Coarse, deliberately auditable word-overlap check against every entry
    in failure_patterns.json -- same "no fuzzy text similarity, no embeddings"
    discipline as check_duplicate above, applied to a DIFFERENT question
    (does this mechanism resemble one that already DIED, not "is this the
    exact same scan finding"). Applies identically regardless of whether the
    hypothesis came from the scanner or from web search -- neither path calls
    this with different logic or a different threshold; see
    test_research_agent_hypothesis_gen.py's cross-origin test.

    Advisory only: a likely-repeat is FLAGGED (recorded on the hypothesis
    record for a human/downstream reader to see), never used to silently
    reject or skip a hypothesis -- that decision stays with frequency_gate/
    auto_tester's own measured-frequency verdict, untouched by this check."""
    hyp_words = _significant_words(f"{hypothesis_name} {mechanism}")
    if not hyp_words:
        return GraveyardCheckResult(False, "hypothesis text has no significant words to compare")

    best_name: str | None = None
    best_overlap = 0.0
    for pattern in failure_patterns:
        pattern_text = " ".join(
            str(pattern.get(key, "")) for key in ("name", "family", "fix_rationale")
        )
        pattern_words = _significant_words(pattern_text)
        if not pattern_words:
            continue
        shared = hyp_words & pattern_words
        overlap = len(shared) / min(len(hyp_words), len(pattern_words))
        if overlap > best_overlap:
            best_overlap = overlap
            best_name = str(pattern.get("name", ""))

    if best_overlap >= GRAVEYARD_OVERLAP_THRESHOLD:
        return GraveyardCheckResult(
            True,
            f"overlap={best_overlap:.2f} (>= threshold {GRAVEYARD_OVERLAP_THRESHOLD}) with "
            f"failure_patterns.json entry {best_name!r}",
            best_name,
        )
    return GraveyardCheckResult(
        False,
        f"no failure_patterns.json entry cleared the overlap threshold "
        f"(best={best_overlap:.2f} < {GRAVEYARD_OVERLAP_THRESHOLD})",
    )


def _build_record(
    finding: ScanFinding, data: dict, cost_usd: float, now: datetime, failure_patterns: list[dict],
    run_id: str | None = None,
) -> dict:
    hypothesis_name = str(data.get("hypothesis_name", "")).strip()
    mechanism = str(data.get("mechanism", "")).strip()
    graveyard_check = check_graveyard_match(hypothesis_name, mechanism, failure_patterns)
    return {
        "scan_finding": finding.description,
        "scan_finding_type": finding.finding_type,
        "hypothesis_name": hypothesis_name,
        "mechanism": mechanism,
        "entry_rule": str(data.get("entry_rule", "")).strip(),
        "structured_entry_rule": data.get("structured_entry_rule"),
        "exit_rule": str(data.get("exit_rule", "")).strip(),
        "stop_rule": str(data.get("stop_rule", "")).strip(),
        "structured_exit_plan": data.get("structured_exit_plan"),
        "asset": str(data.get("asset") or finding.asset).strip(),
        "timeframe": str(data.get("timeframe") or (finding.timeframe or "")).strip(),
        "differs_from_graveyard": str(data.get("differs_from_graveyard", "")).strip(),
        "expected_frequency_claim": data.get("expected_frequency_claim"),
        "generated_at": now.isoformat(),
        "cost_usd": cost_usd,
        "source": "claude",
        "discovery_channel": "scanner",
        # CC-1 directive, items 1+2: run_id ties this record back to the
        # specific run_pipeline() invocation that produced it (minted once per
        # call, see pipeline.py) -- Eve's own records have carried the
        # analogous session_id since inception; Adam's never did until now.
        # origin_agent is a fixed literal here, not inferred -- see
        # nero_core.eve.hypothesis_shapes's "eve" counterpart.
        "run_id": run_id,
        "origin_agent": "adam",
        "origin_chain": None,
        "graveyard_check": {
            "is_likely_repeat": graveyard_check.is_likely_repeat,
            "method": graveyard_check.method,
            "matched_pattern_name": graveyard_check.matched_pattern_name,
        },
    }


@dataclass(frozen=True)
class GenerationRunResult:
    hypotheses: list[dict] = field(default_factory=list)
    duplicates_skipped: list[dict] = field(default_factory=list)
    llm_calls_made: int = 0
    total_cost_usd: float = 0.0
    # CC-1 review, item A3 -- explained, not a bug: despite the name, this is
    # a CALL-COUNT limit (calls_made >= max_calls_per_run), never a dollar
    # threshold -- there is no such thing as a cost-in-dollars limit anywhere
    # in this module. It is set independently of total_cost_usd and can
    # therefore be True on a run that spent (or, per calls_with_unknown_cost
    # above, may have spent) $0.00 -- that combination is expected, not a
    # sign either field is wrong. Kept under its original name (a rename
    # would touch every caller/test for a clarity-only change); this comment
    # exists so the next reader doesn't have to re-derive that.
    cost_limit_hit: bool = False
    errors: list[dict] = field(default_factory=list)
    # CC-1 review, item A3: calls that failed with an error OTHER than a
    # confirmed-$0 401/403/429 rejection (e.g. ReadTimeout, ConnectionError,
    # a 5xx) -- the connection may have reached Anthropic's servers before
    # failing, so the real cost is UNKNOWN, never silently folded into
    # total_cost_usd as if it were a confirmed zero. Included in
    # llm_calls_made (the attempt still consumed the run's call budget) but
    # broken out here so a reader can see total_cost_usd is a FLOOR, not a
    # confirmed total, whenever this is nonzero.
    calls_with_unknown_cost: int = 0


def generate_hypotheses(
    scan_findings: list[ScanFinding],
    failure_patterns: list[dict],
    api_key: str,
    existing_hypotheses: list[dict] | None = None,
    max_calls_per_run: int = DEFAULT_MAX_CALLS_PER_RUN,
    now: datetime | None = None,
    params: HypothesisGenParameters = DEFAULT_PARAMETERS,
    run_id: str | None = None,
) -> GenerationRunResult:
    """One hypothesis per scan finding, in order, skipping duplicates and
    stopping at `max_calls_per_run`. `existing_hypotheses` seeds duplicate
    detection against prior runs; hypotheses generated earlier in THIS run are
    also added to that same pool as they're produced, so a run never
    duplicates itself internally either. `run_id` (CC-1 directive items 1+2,
    added 2026-08-05): the UUID pipeline.run_pipeline mints once per call,
    stamped on every record this call produces -- None for any direct caller
    that doesn't supply one (e.g. an existing test), never fabricated here."""
    now = now or datetime.now(timezone.utc)
    known = list(existing_hypotheses or [])
    hypotheses: list[dict] = []
    duplicates: list[dict] = []
    errors: list[dict] = []
    calls_made = 0
    total_cost = 0.0
    cost_limit_hit = False
    calls_with_unknown_cost = 0

    pricing_warning = _pricing_staleness_warning(now)
    if pricing_warning:
        errors.append({"scan_finding": "(pricing staleness check)", "message": pricing_warning})

    # Preflight: one cheap call to confirm the key is accepted BEFORE spending
    # the real per-finding call budget -- skip entirely if there's nothing that
    # would actually need a call anyway (empty key, or every finding already a
    # known duplicate), so this never burns a call for no reason.
    non_duplicate_findings_exist = any(not check_duplicate(f, known).is_duplicate for f in scan_findings)
    if api_key.strip() and non_duplicate_findings_exist:
        try:
            preflight_note = validate_api_key(api_key, params)
        except ApiKeyRejectedError as exc:
            errors.append({"scan_finding": "(preflight key validation)", "message": str(exc)})
            return GenerationRunResult(hypotheses, duplicates, 1, total_cost, cost_limit_hit, errors, calls_with_unknown_cost)
        if preflight_note:
            # Non-fatal (see validate_api_key's own docstring -- only a 401 stops
            # the run here) but no longer silent: previously this note vanished
            # with zero trace anywhere.
            errors.append({"scan_finding": "(preflight key validation)", "message": preflight_note})

    for finding in scan_findings:
        if calls_made >= max_calls_per_run:
            cost_limit_hit = True
            break

        dup = check_duplicate(finding, known)
        if dup.is_duplicate:
            duplicates.append(
                {"scan_finding": finding.description, "reason": dup.method, "matched_hypothesis_name": dup.matched_hypothesis_name}
            )
            continue

        if not api_key.strip():
            errors.append({"scan_finding": finding.description, "message": "no Claude API key configured -- no call made"})
            continue

        try:
            data, usage = _call_claude(_build_prompt(finding, failure_patterns), api_key, params)
        except ResponseParseError as exc:
            # Item #4/TIER 4: this response WAS billed by Anthropic (2xx,
            # processed) even though it couldn't be used -- record the real
            # cost instead of letting it silently disappear as $0.00.
            calls_made += 1
            billed_cost = _call_cost_usd(exc.usage, params)
            total_cost += billed_cost
            errors.append({
                "scan_finding": finding.description,
                "message": f"{exc} (call WAS billed: ${billed_cost:.6f} -- Anthropic processed "
                           f"this request even though the response couldn't be used)",
            })
            continue
        except RejectedBeforeTokenProcessingError as exc:
            # Confirmed $0 -- rejected before the model ever saw a token
            # (401/403/429). See the exception's own docstring.
            calls_made += 1
            errors.append({"scan_finding": finding.description, "message": f"HTTP {exc.status_code}: {exc} (confirmed $0.00 -- rejected before any token was processed)"})
            continue
        except (requests.RequestException, KeyError, ValueError) as exc:
            # CC-1 review, item A3: the attempt still consumed this run's
            # call budget, but "nothing billed" is no longer assumed -- a
            # ReadTimeout/ConnectionError/5xx means the request may have
            # reached Anthropic's servers before failing, so the real cost
            # is UNKNOWN, tracked separately rather than silently folded
            # into total_cost as a confirmed zero.
            calls_made += 1
            calls_with_unknown_cost += 1
            errors.append({"scan_finding": finding.description, "message": f"{exc.__class__.__name__}: {exc} (cost UNKNOWN, not confirmed $0 -- request may have reached Anthropic's servers before failing)"})
            continue

        calls_made += 1
        cost = _call_cost_usd(usage, params)
        total_cost += cost
        record = _build_record(finding, data, cost, now, failure_patterns, run_id=run_id)
        hypotheses.append(record)
        known.append(record)

    return GenerationRunResult(hypotheses, duplicates, calls_made, total_cost, cost_limit_hit, errors, calls_with_unknown_cost)


def persist_hypotheses(hypotheses: list[dict], path: Path = DEFAULT_HYPOTHESES_PATH) -> None:
    """Append-only write to docs/site_data/agent_hypotheses.json."""
    append_json_list(path, hypotheses)


def load_existing_hypotheses(path: Path = DEFAULT_HYPOTHESES_PATH) -> list[dict]:
    return read_json_list(path)


def load_tracked_asset_timeframes(path: Path = DEFAULT_QUANT_METRICS_PATH) -> list[tuple[str, str]]:
    """Every (asset, timeframe) pair this project currently has real candle
    data for, derived from quant_metrics.json (the same per-file export
    scanner.py's own low_strategy_coverage check reads) -- NEVER a guessed or
    hardcoded list. This exists specifically so a web-sourced hypothesis is
    constrained to a pair that can actually be tested: without it, an LLM
    asked to "pick an asset" has no way to know which of its own training-data
    knowledge of tickers actually has a candle file on this platform, which is
    exactly the USD/JPY-4h class of defect this project's own prior
    investigation found in the scanner-sourced path (a hypothesis for an
    untracked pair silently becomes no_candles_available, never reaching the
    gate). Returns an empty list (never a fabricated fallback) if the export
    is missing or unparseable."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, list):
        return []
    pairs = {
        (str(m["asset"]), str(m["timeframe"]))
        for m in metrics
        if isinstance(m, dict) and "asset" in m and "timeframe" in m
    }
    return sorted(pairs)


WEB_HYPOTHESIS_JSON_KEYS = (
    "hypothesis_name", "mechanism", "source_url", "source_description", "source_tier",
    "paraphrase_confirmed", "entry_rule", "structured_entry_rule", "exit_rule", "stop_rule",
    "structured_exit_plan", "asset", "timeframe", "differs_from_graveyard", "expected_frequency_claim",
)


def _build_web_search_prompt(
    tracked_pairs: list[tuple[str, str]], known_hypothesis_names: list[str], failure_patterns: list[dict]
) -> str:
    pairs_line = ", ".join(f"{asset}/{timeframe}" for asset, timeframe in tracked_pairs) or "(none currently tracked)"
    known_line = ", ".join(n for n in known_hypothesis_names if n) or "(none yet)"

    return f"""You are a quantitative research assistant for Project Vatican, a paper-trading
research platform (never real-money execution) for gold, crypto, forex, and stocks.

Use web search to find a real, documented trading strategy idea from ANY of: an academic
paper, published quantitative-finance research, a well-known technical pattern, or a
strategy writeup. Then propose ONE new trading hypothesis adapting that idea to one of
this project's own currently-tracked (asset, timeframe) pairs, listed below -- do NOT
invent an untracked asset or timeframe; a hypothesis for a pair with no real candle data
on this platform can never be measured or tested, no matter how sound the idea is.

APPROVED RESEARCH PAIRS -- the only (asset, timeframe) pairs with a real backtest history
export AND a computed random-hypothesis baseline behind them; anything else cannot be
scored no matter how sound the idea is -- pick exactly one of these:
{pairs_line}

ALREADY-PROPOSED HYPOTHESES (avoid a near-duplicate of any of these):
{known_line}

KNOWN DEAD MECHANISMS (never propose a hypothesis whose core mechanism matches one of
these -- they have already been tested on this platform and failed):
{_format_failure_patterns(failure_patterns)}

CRITICAL SOURCING RULES -- read carefully, these are non-negotiable:
1. Web provenance is NOT a credibility shortcut. This hypothesis will go through the exact
   same measured-frequency gate and statistical harness as every other hypothesis on this
   platform -- being "from a paper" or "from a well-known pattern" earns it no special
   trust, no skipped checks, no softened bar.
2. You MUST record where the idea came from: a URL if you found one via search (source_url),
   AND the specific publication/platform/paper name (source_description) -- a URL alone is
   not a durable citation. Also classify the source into exactly one tier: source_tier must
   be exactly one of "peer_reviewed_academic", "established_financial_publication",
   "independent_blog_or_newsletter", "forum_discussion", "social_media_post",
   "unknown_unverifiable" -- see the tier definitions below.
3. NEVER reproduce a source's exact rule text, code, or proprietary wording verbatim.
   Describe the mechanism ENTIRELY in your own words. If you genuinely cannot paraphrase
   the source's exact rules without copying them (e.g. a paid course's specific numeric
   thresholds presented as its proprietary system), do NOT fabricate a paraphrase and do
   NOT propose a hypothesis from that source -- instead return EXACTLY this JSON and
   nothing else: {{"skipped": true, "skip_reason": "<why this source could not be safely
   paraphrased>"}}.

CRITICAL REQUIREMENT: Vatican needs hypotheses that generate AT LEAST 20-30 trades per
year. A mechanism that only fires 2-3 times per year is USELESS for this platform no
matter how sound the reasoning is, because it would take years to accumulate enough
resolved trades to know whether it actually works. Design the entry condition to be
FREQUENT, not rare.

If you are proceeding (not skipping), return STRICT JSON only, with exactly these keys
and no others:
- hypothesis_name: a short unique identifier, e.g. "TURN_OF_MONTH_BTC_24H"
- mechanism: 2-3 sentences on WHY this should work, described entirely in your own words
- source_url: the URL you found this at, or "" if the citation is better expressed as a
  publication/platform name (put that in source_description instead)
- source_description: the publication, platform, paper title, or author (e.g. "Journal of
  Finance, Smith & Jones 2019" or "r/algotrading community writeup") -- required even when
  source_url is present
- source_tier: exactly one of the six tiers below -- pick the one that actually matches;
  do NOT default to unknown_unverifiable just because you're unsure between two close
  tiers, but DO use it when the source genuinely doesn't fit any other definition:
  - peer_reviewed_academic: a paper published in or under review at an academic journal
    or conference
  - established_financial_publication: a recognized financial/quant publication, research
    desk, or institutional report (not a single author's personal site)
  - independent_blog_or_newsletter: a single author's or small independent outlet's blog,
    newsletter, or Substack -- not affiliated with an established financial publication
  - forum_discussion: a threaded, multi-participant discussion board (e.g. Reddit,
    dedicated trading forums)
  - social_media_post: a short-form, single-author post (e.g. Twitter/X, a single
    Discord/Telegram message) -- not a threaded discussion
  - unknown_unverifiable: the source doesn't fit any tier above, or you cannot determine
    what kind of source it is
- paraphrase_confirmed: true (only ever true in a non-skipped response -- if you could not
  confirm this, you should have returned the skip JSON above instead)
- entry_rule: a precise, human-readable entry condition
- structured_entry_rule: a machine-checkable version of entry_rule, shaped exactly as
  {{"conditions": [{{"field": <field>, "op": <op>, "value": <number>}}, ...]}} (multiple
  conditions are ANDed together). Allowed fields: close, ma20, ma50, ma200, zscore20,
  atr14, rsi14, adx14, ret_1, volume. Allowed ops: gt, gte, lt, lte, eq, cross_above,
  cross_below. Each condition's right-hand side is EITHER a fixed "value" (a number) OR a
  "compare_to_field" naming another one of the allowed fields above -- exactly one of the
  two, never both. If the entry condition genuinely cannot be expressed with these
  fields/ops, set structured_entry_rule to null -- do NOT force an approximate mapping.
- exit_rule: a precise exit condition
- stop_rule: a precise stop-loss condition
- structured_exit_plan: a machine-checkable exit/stop shape, shaped exactly as
  {{"stop_atr_multiple": <number>, "target_r_multiple": <number>, "max_holding_hours":
  <number>}}. All three must be positive numbers. If exit_rule/stop_rule genuinely cannot
  be expressed this way, set structured_exit_plan to null -- do NOT force an approximate
  mapping.
- asset: exactly one asset string from the tracked pairs list above
- timeframe: exactly one timeframe string from the tracked pairs list above, matching the
  asset you chose
- differs_from_graveyard: 1-2 sentences on how this differs from every dead mechanism
  listed above
- expected_frequency_claim: your own numeric estimate of trades/year (a float) -- recorded
  for reference ONLY. Vatican independently MEASURES the real historical frequency from
  candle data and will reject this hypothesis if the measured number doesn't clear the
  20-30/year bar above, regardless of what you estimate here.

Do not include any field other than these fourteen (or, if skipping, exactly the two
skip fields and nothing else)."""


@dataclass(frozen=True)
class WebHypothesisResult:
    record: dict | None  # None when the LLM returned a skip
    skipped: bool
    skip_reason: str | None = None


def _build_web_record(
    data: dict, cost_usd: float, now: datetime, failure_patterns: list[dict], run_id: str | None = None,
) -> WebHypothesisResult:
    """Mirrors _build_record's field-building discipline, but for the
    web-sourced schema (Rule 2/3 fields added, no ScanFinding to fall back to
    for asset/timeframe -- an LLM that omits them gets an empty string, which
    honestly fails no_candles_available downstream rather than fabricating a
    default asset). `run_id`: see _build_record's own docstring -- same
    per-pipeline-call UUID, threaded through this channel too so a
    web-sourced hypothesis is equally traceable to the run that produced it."""
    if data.get("skipped"):
        return WebHypothesisResult(None, True, str(data.get("skip_reason", "")).strip() or "no reason given")

    source_tier = str(data.get("source_tier", "")).strip()
    if source_tier not in SOURCE_TIERS:
        # Never silently upgrade an unrecognized/missing tier -- the most
        # conservative tier is the honest default, not a guess in either
        # direction.
        source_tier = "unknown_unverifiable"

    hypothesis_name = str(data.get("hypothesis_name", "")).strip()
    mechanism = str(data.get("mechanism", "")).strip()
    graveyard_check = check_graveyard_match(hypothesis_name, mechanism, failure_patterns)

    record = {
        "hypothesis_name": hypothesis_name,
        "mechanism": mechanism,
        "entry_rule": str(data.get("entry_rule", "")).strip(),
        "structured_entry_rule": data.get("structured_entry_rule"),
        "exit_rule": str(data.get("exit_rule", "")).strip(),
        "stop_rule": str(data.get("stop_rule", "")).strip(),
        "structured_exit_plan": data.get("structured_exit_plan"),
        "asset": str(data.get("asset", "")).strip(),
        "timeframe": str(data.get("timeframe", "")).strip(),
        "differs_from_graveyard": str(data.get("differs_from_graveyard", "")).strip(),
        "expected_frequency_claim": data.get("expected_frequency_claim"),
        "generated_at": now.isoformat(),
        "cost_usd": cost_usd,
        "source": "claude",
        "discovery_channel": "web_search",
        "source_url": str(data.get("source_url", "")).strip(),
        "source_description": str(data.get("source_description", "")).strip(),
        "source_tier": source_tier,
        "paraphrase_confirmed": bool(data.get("paraphrase_confirmed", False)),
        "run_id": run_id,
        "origin_agent": "adam",
        "origin_chain": None,
        "graveyard_check": {
            "is_likely_repeat": graveyard_check.is_likely_repeat,
            "method": graveyard_check.method,
            "matched_pattern_name": graveyard_check.matched_pattern_name,
        },
    }
    return WebHypothesisResult(record, False)


def generate_web_hypotheses(
    existing_hypotheses: list[dict],
    failure_patterns: list[dict],
    api_key: str,
    tracked_pairs: list[tuple[str, str]],
    max_calls_per_run: int = DEFAULT_WEB_MAX_CALLS_PER_RUN,
    now: datetime | None = None,
    params: HypothesisGenParameters = DEFAULT_PARAMETERS,
    run_id: str | None = None,
) -> GenerationRunResult:
    """Web-search-based discovery -- an INDEPENDENT, parallel channel from
    generate_hypotheses (the scanner path), per this project's own approved
    design: not gated on the scanner finding nothing (that would bias
    web-sourced ideas toward the least-informative runs), own separate call
    budget (max_calls_per_run, default DEFAULT_WEB_MAX_CALLS_PER_RUN=3 --
    deliberately smaller than the scanner path's 10, given the higher
    per-call cost: token cost plus Anthropic's real $0.01/search server fee,
    see WEB_SEARCH_COST_PER_SEARCH).

    RULE 1 (no special trust): every non-skipped record returned here has the
    EXACT SAME core fields (hypothesis_name/entry_rule/structured_entry_rule/
    exit_rule/stop_rule/structured_exit_plan/asset/timeframe/generated_at)
    that frequency_gate.py and auto_tester.py already consume from the
    scanner path. Neither of those two modules was changed to add this
    function, and neither reads discovery_channel/source_url/source_tier/
    paraphrase_confirmed/graveyard_check at all -- confirmed directly in
    test_research_agent_web_hypothesis_gen.py's own no-special-treatment
    test, not just asserted here.

    RULE 3 (no copyrighted reproduction): a source the LLM flags as
    un-paraphraseable returns {"skipped": true, "skip_reason": ...} instead of
    a hypothesis -- the call is still counted against calls_made/total_cost
    (it was real and billed) but produces no hypothesis record, logged in
    `errors` rather than silently discarded.

    RULE 4 (graveyard check applies equally): every record is built via
    _build_web_record, which calls the SAME check_graveyard_match function
    (same threshold, same code path) generate_hypotheses already calls for
    scanner-sourced records.

    RULE 5 (lookahead protection applies equally): unaffected by this
    function entirely -- frequency_gate.measure_entry_frequency enforces its
    own generated_at cutoff internally regardless of which function produced
    the hypothesis dict it's given."""
    now = now or datetime.now(timezone.utc)
    known_names = [str(h.get("hypothesis_name", "")) for h in existing_hypotheses if h.get("hypothesis_name")]
    hypotheses: list[dict] = []
    errors: list[dict] = []
    calls_made = 0
    total_cost = 0.0
    cost_limit_hit = False
    calls_with_unknown_cost = 0

    pricing_warning = _pricing_staleness_warning(now)
    if pricing_warning:
        errors.append({"scan_finding": "(pricing staleness check)", "message": pricing_warning})

    if not api_key.strip():
        return GenerationRunResult(
            hypotheses, [], 0, 0.0, False,
            errors + [{"scan_finding": "(web search)", "message": "no Claude API key configured -- no call made"}],
        )
    if not tracked_pairs:
        return GenerationRunResult(
            hypotheses, [], 0, 0.0, False,
            errors + [{"scan_finding": "(web search)", "message": "no tracked (asset, timeframe) pairs available -- "
                                                           "no call made (nothing to test a hypothesis against)"}],
        )

    try:
        preflight_note = validate_api_key(api_key, params)
    except ApiKeyRejectedError as exc:
        return GenerationRunResult(hypotheses, [], 1, 0.0, False, errors + [{"scan_finding": "(preflight key validation)", "message": str(exc)}])
    if preflight_note:
        errors.append({"scan_finding": "(preflight key validation)", "message": preflight_note})

    for _ in range(max_calls_per_run):
        prompt = _build_web_search_prompt(tracked_pairs, known_names, failure_patterns)
        try:
            data, usage = _call_claude(prompt, api_key, params, tools=[WEB_SEARCH_TOOL])
        except ResponseParseError as exc:
            calls_made += 1
            billed_cost = _web_call_cost_usd(exc.usage, params)
            total_cost += billed_cost
            errors.append({
                "scan_finding": "(web search)",
                "message": f"{exc} (call WAS billed: ${billed_cost:.6f} -- Anthropic processed "
                           f"this request even though the response couldn't be used)",
            })
            continue
        except RejectedBeforeTokenProcessingError as exc:
            # Confirmed $0 -- rejected before the model ever saw a token.
            calls_made += 1
            errors.append({"scan_finding": "(web search)", "message": f"HTTP {exc.status_code}: {exc} (confirmed $0.00 -- rejected before any token was processed)"})
            continue
        except (requests.RequestException, KeyError, ValueError) as exc:
            # CC-1 review, item A3: real ReadTimeout incident this fixes --
            # 3 web-search calls timed out and were recorded as "nothing
            # billed." The connection succeeded and Anthropic may have
            # already started (and billed) processing a tool-using call
            # before the response timed out client-side -- the real cost is
            # UNKNOWN, tracked separately, never silently folded into
            # total_cost as a confirmed zero.
            calls_made += 1
            calls_with_unknown_cost += 1
            errors.append({"scan_finding": "(web search)", "message": f"{exc.__class__.__name__}: {exc} (cost UNKNOWN, not confirmed $0 -- request may have reached Anthropic's servers before failing)"})
            continue

        calls_made += 1
        cost = _web_call_cost_usd(usage, params)
        total_cost += cost
        result = _build_web_record(data, cost, now, failure_patterns, run_id=run_id)
        if result.skipped:
            errors.append({
                "scan_finding": "(web search)",
                "message": f"source skipped -- could not be safely paraphrased (call WAS billed: "
                           f"${cost:.6f}): {result.skip_reason}",
            })
            continue
        hypotheses.append(result.record)
        known_names.append(result.record["hypothesis_name"])

    if calls_made >= max_calls_per_run:
        cost_limit_hit = True

    return GenerationRunResult(hypotheses, [], calls_made, total_cost, cost_limit_hit, errors, calls_with_unknown_cost)
