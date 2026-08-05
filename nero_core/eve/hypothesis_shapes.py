"""Eve's free-form hypothesis record shape (spec 2.7): whatever JSON shape
Eve proposes via the propose_hypothesis tool (nero_core.eve.tools_defs) is
recorded AS-IS under `raw_hypothesis`, never forced into Adam's schema --
with exactly ONE deliberate, narrow exception: `generated_at` is always
stamped/overridden server-side (see _inject_generated_at below), never left
to Eve to supply.

Testability classification and scoring happen in nero_core.eve.scoring
(Phase 3) -- deliberately NOT here. That module is this branch's one
documented, narrow exception to "nero_core/eve/ never imports from
nero_core/research_agent/" (it must reuse rule_dsl/auto_tester unmodified to
score a DSL-expressible hypothesis against real history -- see its own
module docstring for the full reasoning). This module has no such need and
stays fully isolated: it only knows how to shape a raw LLM tool-call payload
into a storable record, nothing about whether that payload is backtestable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from nero_core.eve import storage
from nero_core.eve.llm_client import extract_tool_uses
from nero_core.eve.tools_defs import PROPOSE_HYPOTHESIS_TOOL_NAME

# Set on every fresh record; nero_core.eve.scoring overwrites this once it
# has actually run the hypothesis through testability classification --
# never faked as TESTABLE/UNTESTABLE_BY_DSL before scoring has run.
TESTABILITY_UNSCORED = "UNSCORED"


def _inject_generated_at(raw_hypothesis: dict, now: datetime) -> dict:
    """Added after Session 0-B's own follow-up finding (docs/investigations/
    eve_engine_v1_report.md): Eve has no reason to know an internal
    `generated_at` field exists at all -- nero_core.research_agent.
    auto_tester._parse_generated_at requires it (it's the frequency gate's
    own no-lookahead cutoff, see frequency_gate.py's docstring), and before
    this fix nothing ever supplied it for a real Eve hypothesis, so a
    hypothesis that cleared both the DSL check and the asset-universe check
    would still silently fail one level deeper with no way for Eve to have
    prevented it (auto_tester.test_hypothesis returns VERDICT_UNTESTABLE --
    see scoring.py's own reconciliation of that against `testability`).

    ALWAYS overrides any `generated_at` Eve might happen to include herself
    -- there is no legitimate reason for her to supply one, and trusting a
    self-reported value here would reopen exactly the lookahead-cutoff
    manipulation risk auto_tester.py's own no-lookahead guarantee exists to
    close (a hypothesis "generated" earlier than it really was would widen
    the pool of pre-cutoff candles a search result could have leaked
    information from). The platform's own real proposal-time clock (`now`,
    threaded through from nero_core.eve.session's turn loop) is the only
    trustworthy source for "when was this hypothesis generated." Returns a
    NEW dict -- never mutates `raw_hypothesis` in place.

    FAILS LOUDLY, NEVER SILENTLY (explicit design requirement): raises
    TypeError immediately if `raw_hypothesis` isn't actually a dict, rather
    than silently building a broken record (every real caller already
    guards this before calling build_hypothesis_record, but this function
    does not trust that indirectly). The injected value is asserted to
    round-trip through datetime.fromisoformat -- the exact parser auto_
    tester._parse_generated_at uses -- so a future refactor that breaks this
    can never again surface as a silent, confusing downstream UNTESTABLE
    verdict; it crashes here instead, which nero_core.eve.pipeline.
    run_pipeline's own except-Exception path already notifies and
    re-raises rather than swallowing (see that module's own docstring)."""
    if not isinstance(raw_hypothesis, dict):
        raise TypeError(f"generated_at injection requires a dict, got {type(raw_hypothesis).__name__}")
    generated_at_iso = now.isoformat()
    datetime.fromisoformat(generated_at_iso)  # must round-trip; raises ValueError otherwise -- see docstring
    return {**raw_hypothesis, "generated_at": generated_at_iso}


def _extract_supporting_source_urls(raw_hypothesis: dict) -> list[str]:
    """CC-1 directive item 1: the record's own top-level, ALWAYS-PRESENT copy
    of whatever `supporting_source_urls` Eve included inside her free-form
    `hypothesis` object (nero_core.eve.tools_defs.PROPOSE_HYPOTHESIS_TOOL's
    own description instructs her to, optionally). Deliberately NOT injected
    into raw_hypothesis itself -- this module's own docstring already
    documents generated_at as the ONE deliberate exception to "recorded
    AS-IS," and a second silent exception there would quietly break that
    guarantee (see test_eve_hypothesis_shapes.py's own verbatim-preservation
    test). Normalizes Eve's omission of the key entirely (a hypothesis
    derived purely from indicator/pattern reasoning cites nothing -- a
    legitimate, common answer, not an error) to an empty list, and drops any
    non-string entry rather than trusting an LLM-authored list's element
    types blindly. Validating these URLs against this session's own real
    search results (a hard requirement, not a suggestion) needs the WHOLE
    session's search log, which isn't available at this per-turn,
    per-hypothesis point -- see nero_core.eve.scoring.classify_citation_
    status, run later as a separate pass, same convention as testability/
    verdict_is below."""
    urls = raw_hypothesis.get("supporting_source_urls")
    if not isinstance(urls, list):
        return []
    return [u for u in urls if isinstance(u, str)]


def build_hypothesis_record(raw_hypothesis: dict, session_id: str, turn_index: int, tool_use_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": storage.SCHEMA_VERSION,
        "session_id": session_id,
        "turn_index": turn_index,
        "tool_use_id": tool_use_id,
        "proposed_at": now.isoformat(),
        "raw_hypothesis": _inject_generated_at(raw_hypothesis, now),
        "testability": TESTABILITY_UNSCORED,
        "verdict_is": None,
        "verdict_oos": None,
        "verdict_combined": None,
        "contamination_tags": [],
        # CC-1 directive items 1+2: Eve's own claimed sources (always a
        # list, see _extract_supporting_source_urls above) plus the
        # citation-validation/freshness-attribution fields that
        # nero_core.eve.scoring fills in later, once this session's full
        # search log is available -- start null/UNSCORED here, exactly like
        # testability/verdict_is above, never faked before scoring runs.
        "supporting_source_urls": _extract_supporting_source_urls(raw_hypothesis),
        "citation_status": None,
        "supporting_source_urls_validated": None,
        "supporting_source_urls_invalid": None,
        "per_hypothesis_freshness": None,
        # CC-1 directive, items 1+2: origin_agent is a fixed literal (Eve's
        # own records are never Adam-sourced) -- Adam's counterpart is
        # nero_core.research_agent.hypothesis_gen._build_record. origin_chain
        # stays None here; only a repair-lab-sourced Trial admission (item 5)
        # ever populates it, and Eve's session loop never calls repair_lab
        # (see test_eve_no_auto_wire.py).
        "origin_agent": "eve",
        "origin_chain": None,
    }


def extract_proposed_hypotheses(content_blocks: list[dict], session_id: str, turn_index: int, now: datetime | None = None) -> list[dict]:
    """Every propose_hypothesis tool_use block found in one turn's content
    blocks -> one record each (spec 3.4's own n_proposed is exactly
    `len()` of this across a whole session -- see nero_core.eve.session).
    A tool call whose `hypothesis` input isn't itself a JSON object is
    skipped (never fabricated into one) -- this should be structurally rare
    since PROPOSE_HYPOTHESIS_TOOL's own input_schema requires an object, but
    is not itself proof the API always honors that."""
    records = []
    for block in extract_tool_uses(content_blocks, PROPOSE_HYPOTHESIS_TOOL_NAME):
        raw = (block.get("input") or {}).get("hypothesis")
        if not isinstance(raw, dict):
            continue
        records.append(build_hypothesis_record(raw, session_id, turn_index, block.get("id", ""), now=now))
    return records
