"""CC-1 Factory Loop directive, item 6: TEST -> GRAVEYARD, with distillation.

Before this, `docs/site_data/graveyard.json` (21 entries) and
`docs/site_data/failure_patterns.json` (22 entries) were both 100%
hand-curated -- no code anywhere wrote either file (see
docs/investigations/factory_loop_specification.md's own item 0c/B2). This
module is the first automated writer for either, and it deliberately keeps
the same discipline the hand-curated process already had: an LLM drafts an
entry from AGGREGATE STATS (never raw per-trade data it wasn't shown -- the
same "diagnosis sees aggregate stats, never raw data" rule
nero_core.research_agent.repair_lab's own diagnosis step already enforces),
and a human approves it via auto_tester.py's existing REVIEW_PENDING
convention before anything is actually written.

TRIGGER: per mechanism FAMILY (graveyard.json's own `family` field, e.g.
"Fair Value Gap" spans multiple named variants), once that family's DIED
count reaches DIED_COUNT_TRIGGER (3 -- see docs/investigations/
factory_loop_specification.md's own B2 recommendation, a starting point for
the human running the loop to adjust, not a principled bound).

FAMILY ASSIGNMENT -- deliberately scoped, not a new clustering system: a
DIED hypothesis is assigned to an EXISTING family only, via the SAME
overlap-based check_graveyard_match function hypothesis_gen.py already uses
at generation time (Adam's own records already carry this as
graveyard_check.matched_pattern_name, computed once at generation; Eve's
records carry no such field, so it is computed fresh here, on demand, using
the identical function). A DIED hypothesis with no strong match to any
existing family is NOT auto-clustered into a new one -- this project's own
established discipline (hypothesis_gen.py's own module docstring, tag_
derivative's own docstring) is to keep lexical-overlap matching deliberately
coarse and auditable rather than build an unproven grouping heuristic; a
genuinely novel failure mode still needs a human to look at it and decide
its family the first time, same as today.

TWO-FILE WRITE (item 6a, locked -- do not merge the files): every commit
writes to BOTH graveyard.json (the uncapped full record) and
failure_patterns.json (the capped, distilled reading surface Adam/Eve
actually consume) in one operation, or neither. See
tests/test_graveyard_failure_pattern_sync.py's own coverage-based sync
check (item 6c) for the invariant this maintains."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from nero_core.research_agent import repair_lab
from nero_core.research_agent.hypothesis_gen import (
    DEFAULT_HYPOTHESES_PATH,
    DEFAULT_PARAMETERS,
    ApiKeyRejectedError,
    HypothesisGenParameters,
    NoTextBlockError,
    check_graveyard_match,
    validate_api_key,
)
from nero_core.research_agent.storage import read_json_list

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"
DEFAULT_GRAVEYARD_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard.json"
DEFAULT_FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"
DEFAULT_EVE_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"
# item 4/5's Trial store -- read here for item 6d's success-feedback loop.
# Does not exist yet at the moment this module was written (item 4 lands
# after this one in some run orders); load_survived_trial_context handles a
# missing file the same way _load_failure_patterns always has: [], no error.
DEFAULT_FORWARD_TRIAL_PATH = REPO_ROOT / "docs" / "site_data" / "forward_trial.json"

VERDICT_DIED = "DIED"

# item 6b: real counts at the time this was written (2026-08-05, re-derived
# directly from committed data, not the stale "13" docs/investigations/
# factory_loop_specification.md carried forward from before commit
# a55059a's 9-entry backfill): graveyard.json=21 entries, failure_patterns.
# json=22 entries. See docs/investigations/factory_loop_implementation_
# report.md for the measured per-entry size and the resulting Eve
# context-read cost at this cap.
DIED_COUNT_TRIGGER = 3
FAILURE_PATTERNS_CAP = 30

# Same value/convention as nero_core.research_agent.auto_tester.REVIEW_PENDING
# ("pending_human_approval") -- a conceptually distinct kind of pending
# review (a draft graveyard/failure-pattern entry, not a promising
# hypothesis), reusing the same string rather than inventing a second
# "needs human review" vocabulary.
REVIEW_PENDING = "pending_human_approval"

# Mirrors website/lib/types.ts's closed FailurePattern union -- the SAME
# closed vocabulary tests/test_graveyard_failure_pattern_sync.py already
# enforces. Reused, not redefined independently, so the two can never drift.
ALLOWED_FAILURE_PATTERN_VALUES = frozenset({
    "regime-filter-only", "grid-shift-artifact", "edge-over-random-negative",
    "sample-too-thin", "data-blocked", "mechanism-doesn't-transfer",
})


@dataclass(frozen=True)
class DiedRecord:
    hypothesis_name: str
    mechanism: str
    origin_agent: str  # "adam" | "eve"
    matched_family: str | None
    p_value_oos: float | None
    source_ref: dict = field(default_factory=dict)
    # item 5d: populated only for a DIED repair attempt (see
    # load_died_repair_records below) -- {repair_chain_id, attempt_id} so a
    # future distillation can distinguish a re-death (a repair that still
    # failed) from a first death, per item 2's own origin_chain field.
    origin_chain: dict | None = None


def _family_for_name(pattern_name: str | None, failure_patterns: list[dict]) -> str | None:
    if not pattern_name:
        return None
    for entry in failure_patterns:
        if entry.get("name") == pattern_name:
            return entry.get("family")
    return None


def load_died_records(
    test_results_path: Path = DEFAULT_TEST_RESULTS_PATH,
    hypotheses_path: Path = DEFAULT_HYPOTHESES_PATH,
    eve_hypotheses_path: Path = DEFAULT_EVE_HYPOTHESES_PATH,
    failure_patterns: list[dict] | None = None,
) -> list[DiedRecord]:
    """Every DIED-verdict hypothesis across BOTH agents, normalized to one
    shape -- Adam's own graveyard_check.matched_pattern_name (already
    computed at generation time, see hypothesis_gen._build_record) is reused
    directly for her records; Eve's records carry no such field (her own
    schema has no graveyard_check -- confirmed, nero_core/eve/ has zero
    references to it), so it is computed fresh here via the SAME
    check_graveyard_match function, on demand, never a second matching
    method."""
    failure_patterns = failure_patterns if failure_patterns is not None else read_json_list(DEFAULT_FAILURE_PATTERNS_PATH)
    died: list[DiedRecord] = []

    test_results = read_json_list(test_results_path)
    hypotheses_by_name = {}
    for h in read_json_list(hypotheses_path):
        if isinstance(h, dict) and h.get("hypothesis_name"):
            hypotheses_by_name.setdefault(h["hypothesis_name"], h)
    for result in test_results:
        if not isinstance(result, dict) or result.get("verdict") != VERDICT_DIED:
            continue
        name = result.get("hypothesis_name", "")
        hyp = hypotheses_by_name.get(name, {})
        matched_name = (hyp.get("graveyard_check") or {}).get("matched_pattern_name")
        p_oos = ((result.get("test") or {}).get("bootstrap_ci") or {}).get("mean_r") if isinstance(result.get("test"), dict) else None
        died.append(DiedRecord(
            hypothesis_name=name,
            mechanism=str(hyp.get("mechanism", "")),
            origin_agent=hyp.get("origin_agent", "adam"),
            matched_family=_family_for_name(matched_name, failure_patterns),
            p_value_oos=p_oos,
            source_ref={"run_id": hyp.get("run_id"), "discovery_channel": hyp.get("discovery_channel")},
        ))

    for record in read_json_list(eve_hypotheses_path):
        if not isinstance(record, dict) or record.get("verdict_combined") != VERDICT_DIED:
            continue
        raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
        name = str(raw.get("hypothesis_name", ""))
        mechanism = str(raw.get("mechanism", ""))
        match = check_graveyard_match(name, mechanism, failure_patterns)
        died.append(DiedRecord(
            hypothesis_name=name,
            mechanism=mechanism,
            origin_agent=record.get("origin_agent", "eve"),
            matched_family=_family_for_name(match.matched_pattern_name, failure_patterns),
            p_value_oos=record.get("p_value_oos"),
            source_ref={"session_id": record.get("session_id")},
        ))

    return died


def load_died_repair_records(
    events: list[dict] | None = None,
    repair_events_path: Path = repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH,
    failure_patterns: list[dict] | None = None,
) -> list[DiedRecord]:
    """item 5d: 'a repair that still fails stays in the Graveyard -- wire
    that arrow too.' Scans every repair chain's reconstructed state (see
    repair_lab.reconstruct_chain_state) for attempts that resolved to DIED,
    tagging each with origin_chain={repair_chain_id, attempt_id} so a
    future distillation can distinguish a re-death (a repair that already
    tried once and still failed) from a first death. origin_agent is
    inherited from the chain's own launch event when present (a real
    caller's EVENT_ATTEMPT_LAUNCHED should carry it -- see nero_core.
    research_agent.repair_to_trial's own docstring on what a launch event
    must carry), defaulting to 'adam' (repair attempts are launched via
    Adam's own hypothesis_gen LLM-call pattern, per repair_lab.py's own
    module docstring) only when genuinely absent, never guessed otherwise."""
    events = events if events is not None else repair_lab.load_repair_events(repair_events_path)
    failure_patterns = failure_patterns if failure_patterns is not None else read_json_list(DEFAULT_FAILURE_PATTERNS_PATH)

    chain_ids = sorted({e.get("repair_chain_id") for e in events if e.get("repair_chain_id")})
    died: list[DiedRecord] = []
    for chain_id in chain_ids:
        state = repair_lab.reconstruct_chain_state(chain_id, events)
        for attempt in state["attempts"]:
            if attempt.get("status") != repair_lab.ATTEMPT_DIED:
                continue
            mechanism = str(attempt.get("mechanism", "")) or str(state.get("original_hypothesis_name", ""))
            match = check_graveyard_match(
                f"{state.get('original_hypothesis_name', '')}__REPAIR_{attempt.get('attempt_id')}", mechanism, failure_patterns,
            )
            result = attempt.get("result") if isinstance(attempt.get("result"), dict) else None
            died.append(DiedRecord(
                hypothesis_name=f"{state.get('original_hypothesis_name', '')}__REPAIR_{attempt.get('attempt_id')}",
                mechanism=mechanism,
                origin_agent=attempt.get("origin_agent", "adam"),
                matched_family=_family_for_name(match.matched_pattern_name, failure_patterns),
                p_value_oos=(result or {}).get("p_value_oos"),
                source_ref={"repair_chain_id": chain_id, "attempt_id": attempt.get("attempt_id")},
                origin_chain={"repair_chain_id": chain_id, "attempt_id": attempt.get("attempt_id")},
            ))
    return died


def group_died_by_family(died_records: list[DiedRecord]) -> dict[str, list[DiedRecord]]:
    """Only records with a real matched_family (an EXISTING failure_patterns
    family -- see module docstring's FAMILY ASSIGNMENT section) are grouped;
    unmatched DIED records are deliberately excluded here, not silently
    dropped from the caller's view -- see find_unmatched_died_records."""
    grouped: dict[str, list[DiedRecord]] = {}
    for record in died_records:
        if record.matched_family:
            grouped.setdefault(record.matched_family, []).append(record)
    return grouped


def find_unmatched_died_records(died_records: list[DiedRecord]) -> list[DiedRecord]:
    """DIED records with no strong match to any existing family -- surfaced
    for a human to triage (a genuinely new failure mode's first occurrence),
    never silently auto-clustered. Callers/reports should show this list
    alongside find_families_ready_for_distillation's output so a human can
    see BOTH "known families accumulating enough DIED evidence to distill"
    and "novel failures nothing existing describes yet.\""""
    return [r for r in died_records if not r.matched_family]


def find_families_ready_for_distillation(died_records: list[DiedRecord], threshold: int = DIED_COUNT_TRIGGER) -> dict[str, list[DiedRecord]]:
    grouped = group_died_by_family(died_records)
    return {family: members for family, members in grouped.items() if len(members) >= threshold}


def _extract_text(content: object) -> str:
    """Re-inlined from hypothesis_gen._extract_text -- see repair_lab.py's
    own identical re-inline and its docstring for why (an underscore-
    prefixed helper in another module is that module's own implementation
    detail, not a shared API to import across modules)."""
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


def _call_cost_usd(usage: dict, params: HypothesisGenParameters) -> float:
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    return (input_tokens / 1_000_000.0) * params.input_cost_per_mtok + (output_tokens / 1_000_000.0) * params.output_cost_per_mtok


def build_distillation_prompt(family: str, members: list[DiedRecord]) -> str:
    """AGGREGATE STATS ONLY -- names, mechanisms (short prose already on
    each hypothesis record, not a raw trade-by-trade dump), origin_agent,
    p-values. Mirrors repair_lab.build_diagnosis_prompt's own "diagnosis
    sees aggregate stats it was actually shown" discipline."""
    lines = [
        f"You are drafting a graveyard distillation entry for the mechanism family {family!r}.",
        f"{len(members)} hypotheses in this family have now DIED. Their details:",
    ]
    for m in members:
        p = f"{m.p_value_oos:.4f}" if isinstance(m.p_value_oos, (int, float)) else "n/a"
        lines.append(f"- {m.hypothesis_name} (origin: {m.origin_agent}, p_value_oos: {p}): {m.mechanism}")
    lines.append(
        "\nWrite a JSON object with EXACTLY these keys: "
        '{"name": a short SCREAMING_SNAKE_CASE identifier for this distilled entry, '
        '"failure_pattern": one of ' + ", ".join(sorted(ALLOWED_FAILURE_PATTERN_VALUES)) + ", "
        '"why_it_died": one or two sentences synthesizing WHY this family of mechanisms fails, in plain '
        'language, from the aggregate evidence above (not a template -- explain the real mechanism), '
        '"fixable": true or false, whether a repair (a bounded, single modification) could plausibly address this, '
        '"source_doc": a short human-readable reference string for where this diagnosis came from}. '
        "Return ONLY the JSON object, no other text."
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class DistillationDraftResult:
    entry: dict | None
    usage: dict
    cost_usd: float
    error: str | None = None


def draft_distillation_entry(
    family: str, members: list[DiedRecord], api_key: str, params: HypothesisGenParameters = DEFAULT_PARAMETERS,
) -> DistillationDraftResult:
    """ONE call, ONE drafted entry -- same anti-p-hacking-adjacent discipline
    as repair_lab.propose_modification (no re-rolling). The structural
    bookkeeping fields (`covers`, `origin_agent_breakdown`, `family`) are
    computed HERE from `members` directly, never trusted from the LLM's own
    JSON response -- the LLM only supplies the narrative/classification
    fields (name, failure_pattern, why_it_died synthesis, fixable,
    source_doc). Sits at review_status=REVIEW_PENDING; commit_graveyard_
    entry refuses to write anything still at that status (item 6's human
    approval gate)."""
    if not api_key.strip():
        return DistillationDraftResult(None, {}, 0.0, "no Claude API key configured -- no call made")

    preflight_note = validate_api_key(api_key, params)  # raises ApiKeyRejectedError on 401
    prompt = build_distillation_prompt(family, members)
    body = {
        "model": params.claude_model,
        "max_tokens": params.claude_max_tokens,
        "thinking": params.claude_thinking,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
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
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage") or {}
        cost = _call_cost_usd(usage, params)
        text = _extract_text(payload.get("content")).strip()
        data = json.loads(_strip_markdown_json(text))
    except requests.RequestException as exc:
        return DistillationDraftResult(None, {}, 0.0, f"{exc.__class__.__name__}: {exc}")
    except (NoTextBlockError, json.JSONDecodeError) as exc:
        return DistillationDraftResult(None, {}, 0.0, f"{exc.__class__.__name__}: {exc}")

    failure_pattern = str(data.get("failure_pattern", ""))
    if failure_pattern not in ALLOWED_FAILURE_PATTERN_VALUES:
        return DistillationDraftResult(
            None, usage, cost,
            f"LLM returned failure_pattern={failure_pattern!r}, outside the closed vocabulary "
            f"{sorted(ALLOWED_FAILURE_PATTERN_VALUES)} -- draft rejected, call WAS billed (${cost:.6f}).",
        )

    origin_breakdown: dict[str, int] = {}
    for m in members:
        origin_breakdown[m.origin_agent] = origin_breakdown.get(m.origin_agent, 0) + 1

    entry = {
        "name": str(data.get("name", "")).strip(),
        "family": family,
        "failure_pattern": failure_pattern,
        "why_it_died": str(data.get("why_it_died", "")).strip(),
        "fixable": bool(data.get("fixable", False)),
        "source_doc": str(data.get("source_doc", "")).strip(),
        "covers": [m.hypothesis_name for m in members],
        "origin_agent_breakdown": origin_breakdown,
        # item 2a: tag every graveyard entry this produces with its OWN
        # origin_agent, not just the family-level aggregate above --
        # consumed by commit_graveyard_entry when building each new
        # graveyard.json row, so a future distillation can honestly report
        # "died 4 times under Adam, 1 under Eve" per-name, not just
        # per-family (spec B5's own recommendation).
        "origin_agent_by_name": {m.hypothesis_name: m.origin_agent for m in members},
        "review_status": REVIEW_PENDING,
        "drafted_at": datetime.now(timezone.utc).isoformat(),
    }
    note = f" (preflight note: {preflight_note})" if preflight_note else None
    return DistillationDraftResult(entry, usage, cost, note)


class EntryNotApprovedError(Exception):
    """Raised by commit_graveyard_entry when asked to write an entry still
    at review_status=REVIEW_PENDING -- item 6's human-approval gate, the
    same discipline auto_tester.py's own REVIEW_PENDING convention already
    enforces by process (never structurally, until now -- this is the FIRST
    place in this codebase that actually refuses a write, not just labels
    one pending)."""


def _write_json_list(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2) + "\n")


def commit_graveyard_entry(
    entry: dict,
    graveyard_path: Path = DEFAULT_GRAVEYARD_PATH,
    failure_patterns_path: Path = DEFAULT_FAILURE_PATTERNS_PATH,
    cap: int = FAILURE_PATTERNS_CAP,
) -> dict:
    """Writes to BOTH files in one operation (item 6a) -- both computed in
    memory first, both written only if both succeed, never one without the
    other. `entry` must have review_status set to something OTHER than
    REVIEW_PENDING (a human has approved it) -- raises EntryNotApprovedError
    otherwise, never silently writes an unapproved draft.

    CAP AND MERGE (item 6b): if failure_patterns.json is already at or over
    `cap` entries, this entry is MERGED into the best-matching existing
    entry (same `family`) instead of appended -- that existing entry's
    `covers` list is extended with `entry`'s own covers, `origin_agent_
    breakdown` counts are summed. If no existing failure_patterns entry
    shares this family, the cap is enforced strictly: raises rather than
    silently appending past the cap or guessing an unrelated merge target.

    graveyard.json ALWAYS gets one new entry per name in `entry["covers"]`
    that doesn't already exist there (graveyard.json is the uncapped full
    record, per item 6c's own division of the two files) -- never merged,
    never capped."""
    if entry.get("review_status") == REVIEW_PENDING:
        raise EntryNotApprovedError(
            f"entry {entry.get('name')!r} is still review_status={REVIEW_PENDING!r} -- "
            f"a human must approve it (change review_status) before commit_graveyard_entry may write it."
        )

    graveyard = read_json_list(graveyard_path)
    failure_patterns = read_json_list(failure_patterns_path)
    existing_graveyard_names = {g.get("name") for g in graveyard}

    # item 2a: origin_agent is set per-name from origin_agent_by_name when
    # draft_distillation_entry supplied it; None (never guessed) for an
    # entry built by another path that didn't (e.g. a hand-authored commit).
    covers = entry.get("covers") or [entry.get("name")]
    origin_agent_by_name = entry.get("origin_agent_by_name") or {}
    new_graveyard_entries = [
        {
            "name": name,
            "family": entry["family"],
            "what_was_tested": name,
            "why_it_died": entry.get("why_it_died", ""),
            "source_doc": entry.get("source_doc", ""),
            "origin_agent": origin_agent_by_name.get(name),
        }
        for name in covers
        if name not in existing_graveyard_names
    ]

    if len(failure_patterns) < cap:
        failure_patterns_updated = failure_patterns + [_public_failure_pattern_fields(entry)]
    else:
        merge_target = next((fp for fp in failure_patterns if fp.get("family") == entry["family"]), None)
        if merge_target is None:
            raise ValueError(
                f"failure_patterns.json is at its cap ({cap} entries) and no existing entry shares family "
                f"{entry['family']!r} to merge into -- refusing to append past the cap or guess an unrelated "
                f"merge target. A human must choose a merge target manually."
            )
        merge_target.setdefault("covers", [merge_target["name"]])
        merge_target["covers"] = sorted(set(merge_target["covers"]) | set(covers))
        merged_breakdown = dict(merge_target.get("origin_agent_breakdown") or {})
        for agent, count in (entry.get("origin_agent_breakdown") or {}).items():
            merged_breakdown[agent] = merged_breakdown.get(agent, 0) + count
        merge_target["origin_agent_breakdown"] = merged_breakdown
        failure_patterns_updated = failure_patterns

    _write_json_list(graveyard_path, graveyard + new_graveyard_entries)
    _write_json_list(failure_patterns_path, failure_patterns_updated)
    return {"graveyard_entries_added": len(new_graveyard_entries), "failure_patterns_merged": len(failure_patterns) >= cap}


def _public_failure_pattern_fields(entry: dict) -> dict:
    """failure_patterns.json's real committed shape (name, family,
    failure_pattern, fixable, source_doc -- the 5 fields tests/
    test_graveyard_failure_pattern_sync.py's REQUIRED_FAILURE_PATTERN_FIELDS
    already enforces) plus item 6's additions (covers, origin_agent_
    breakdown) -- drops the review-workflow-only fields (review_status,
    drafted_at) that have no reason to persist in the committed file once
    approved."""
    return {
        "name": entry["name"],
        "family": entry["family"],
        "failure_pattern": entry["failure_pattern"],
        "fixable": entry["fixable"],
        "source_doc": entry.get("source_doc", ""),
        "covers": entry.get("covers", [entry["name"]]),
        "origin_agent_breakdown": entry.get("origin_agent_breakdown", {}),
    }


def load_survived_trial_context(path: Path = DEFAULT_FORWARD_TRIAL_PATH) -> list[dict]:
    """Item 6d: success feedback -- read fresh every session, the SAME
    discipline failure_patterns.json already gets (see hypothesis_gen.
    _load_failure_patterns), just for SURVIVED_TRIAL entries in item 4/5's
    Trial store instead of DIED ones. Built now even though it returns []
    today (nothing has ever reached SURVIVED_TRIAL) -- retrofitting this
    later, once real data exists, would be strictly more work than reading
    an agreed shape that doesn't exist yet. Missing file -> [], same
    convention as _load_failure_patterns, never an error."""
    records = read_json_list(path)
    return [r for r in records if isinstance(r, dict) and r.get("status") == "SURVIVED_TRIAL"]
