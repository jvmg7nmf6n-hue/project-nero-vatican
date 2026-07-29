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

DEFAULT_MAX_CALLS_PER_RUN = 10

# Pricing effective 2026-07-29 (introductory rate through 2026-08-31): $2.00
# input / $10.00 output per MTok for claude-sonnet-5. Reverts to the standard
# $3.00/$15.00 per MTok after that date -- update these two constants then.
# Source: the Claude API pricing reference, cached 2026-06-24.
INPUT_COST_PER_MTOK = 2.00
OUTPUT_COST_PER_MTOK = 10.00


@dataclass(frozen=True)
class HypothesisGenParameters:
    claude_model: str = "claude-sonnet-5"
    claude_api_url: str = "https://api.anthropic.com/v1/messages"
    claude_api_version: str = "2023-06-01"
    claude_max_tokens: int = 1500
    claude_timeout_seconds: int = 30
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
  atr14, ret_1, volume. Allowed ops: gt, gte, lt, lte, eq, cross_above, cross_below. If
  the entry condition genuinely cannot be expressed with these fields/ops, set
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


def _call_claude(prompt: str, api_key: str, params: HypothesisGenParameters) -> tuple[dict, dict]:
    """Returns (parsed_json_data, usage_dict). Raises on any transport/parse
    failure -- the caller (generate_hypotheses) is responsible for catching
    and recording the error, matching this project's existing per-call error
    handling convention (news_sentiment_llm.analyze_headline)."""
    response = requests.post(
        params.claude_api_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": params.claude_api_version,
            "content-type": "application/json",
        },
        json={
            "model": params.claude_model,
            "max_tokens": params.claude_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=params.claude_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    text = _extract_text(payload.get("content")).strip()
    data = json.loads(_strip_markdown_json(text))
    usage = payload.get("usage") or {}
    return data, usage


def _call_cost_usd(usage: dict, params: HypothesisGenParameters) -> float:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return (input_tokens / 1_000_000.0) * params.input_cost_per_mtok + (output_tokens / 1_000_000.0) * params.output_cost_per_mtok


def _build_record(finding: ScanFinding, data: dict, cost_usd: float, now: datetime) -> dict:
    return {
        "scan_finding": finding.description,
        "scan_finding_type": finding.finding_type,
        "hypothesis_name": str(data.get("hypothesis_name", "")).strip(),
        "mechanism": str(data.get("mechanism", "")).strip(),
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
    }


@dataclass(frozen=True)
class GenerationRunResult:
    hypotheses: list[dict] = field(default_factory=list)
    duplicates_skipped: list[dict] = field(default_factory=list)
    llm_calls_made: int = 0
    total_cost_usd: float = 0.0
    cost_limit_hit: bool = False
    errors: list[dict] = field(default_factory=list)


def generate_hypotheses(
    scan_findings: list[ScanFinding],
    failure_patterns: list[dict],
    api_key: str,
    existing_hypotheses: list[dict] | None = None,
    max_calls_per_run: int = DEFAULT_MAX_CALLS_PER_RUN,
    now: datetime | None = None,
    params: HypothesisGenParameters = DEFAULT_PARAMETERS,
) -> GenerationRunResult:
    """One hypothesis per scan finding, in order, skipping duplicates and
    stopping at `max_calls_per_run`. `existing_hypotheses` seeds duplicate
    detection against prior runs; hypotheses generated earlier in THIS run are
    also added to that same pool as they're produced, so a run never
    duplicates itself internally either."""
    now = now or datetime.now(timezone.utc)
    known = list(existing_hypotheses or [])
    hypotheses: list[dict] = []
    duplicates: list[dict] = []
    errors: list[dict] = []
    calls_made = 0
    total_cost = 0.0
    cost_limit_hit = False

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
        except (requests.RequestException, NoTextBlockError, KeyError, ValueError, json.JSONDecodeError) as exc:
            calls_made += 1  # the attempt still consumed this run's call budget
            errors.append({"scan_finding": finding.description, "message": f"{exc.__class__.__name__}: {exc}"})
            continue

        calls_made += 1
        cost = _call_cost_usd(usage, params)
        total_cost += cost
        record = _build_record(finding, data, cost, now)
        hypotheses.append(record)
        known.append(record)

    return GenerationRunResult(hypotheses, duplicates, calls_made, total_cost, cost_limit_hit, errors)


def persist_hypotheses(hypotheses: list[dict], path: Path = DEFAULT_HYPOTHESES_PATH) -> None:
    """Append-only write to docs/site_data/agent_hypotheses.json."""
    append_json_list(path, hypotheses)


def load_existing_hypotheses(path: Path = DEFAULT_HYPOTHESES_PATH) -> list[dict]:
    return read_json_list(path)
