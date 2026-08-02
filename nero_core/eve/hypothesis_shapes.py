"""Eve's free-form hypothesis record shape (spec 2.7): whatever JSON shape
Eve proposes via the propose_hypothesis tool (nero_core.eve.tools_defs) is
recorded AS-IS under `raw_hypothesis`, never forced into Adam's schema.

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


def build_hypothesis_record(raw_hypothesis: dict, session_id: str, turn_index: int, tool_use_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "schema_version": storage.SCHEMA_VERSION,
        "session_id": session_id,
        "turn_index": turn_index,
        "tool_use_id": tool_use_id,
        "proposed_at": now.isoformat(),
        "raw_hypothesis": raw_hypothesis,
        "testability": TESTABILITY_UNSCORED,
        "verdict_is": None,
        "verdict_oos": None,
        "verdict_combined": None,
        "contamination_tags": [],
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
