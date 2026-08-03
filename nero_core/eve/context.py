"""Read-only context supply for Eve's sessions (spec 2.2): tracked
(asset, timeframe) pairs, the graveyard (failure_patterns.json), and Adam's
own hypothesis history -- VERDICT-STRIPPED.

VERDICT-STRIPPING, PRECISELY: this module reads ONLY
docs/site_data/agent_hypotheses.json (via nero_core.eve.storage.read_json_list,
a generic READ helper with no write-path restriction -- reading Adam's own
exports is explicitly allowed by spec 2.2; only WRITING outside Eve's own
three paths is forbidden, see storage.py). It NEVER reads
docs/site_data/agent_test_results.json -- the export that actually carries
verdicts (SURVIVED/DIED/PROMISING-WATCHLIST/UNTESTABLE/SKIPPED), keyed by
hypothesis_name, is a completely separate file Adam's own auto_tester.py
writes; this module has no function that even constructs that path,
confirmed directly by test_eve_context_verdict_stripped.py rather than
merely asserted here.

Even though today's agent_hypotheses.json schema happens to carry no verdict
field on the hypothesis record itself (confirmed by reading hypothesis_gen.
py's own _build_record/_build_web_record), this module additionally
WHITELISTS (rather than blacklists) which fields are ever copied into what
Eve sees -- the safer direction if that schema ever grows a verdict-like
field later: an unrecognized new field is silently EXCLUDED, never silently
included.

ALL OF THIS IS REFERENCE, NEVER A CONSTRAINT (spec 2.2's own words) -- see
EveContext.as_prompt_text's own framing, and nero_core.eve.session's system
prompt, which repeats this explicitly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from nero_core.eve import storage

REPO_ROOT = storage.REPO_ROOT
DEFAULT_QUANT_METRICS_PATH = REPO_ROOT / "docs" / "site_data" / "quant_metrics.json"
DEFAULT_FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"
DEFAULT_ADAM_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"

# Whitelisted fields copied from each Adam hypothesis record -- see module
# docstring on why this is a whitelist, not a blacklist. Every one of these
# is a TEXT/mechanism-describing field; none is a verdict, review_status, or
# anything derived from a backtest result (those live only in
# agent_test_results.json, never read by this module).
_ADAM_HISTORY_FIELDS = (
    "hypothesis_name", "mechanism", "entry_rule", "exit_rule", "stop_rule",
    "asset", "timeframe", "differs_from_graveyard", "discovery_channel",
)


def load_tracked_asset_timeframes(path: Path = DEFAULT_QUANT_METRICS_PATH) -> list[tuple[str, str]]:
    """Every (asset, timeframe) pair this project currently has real candle
    data for -- reinlines nero_core.research_agent.hypothesis_gen.
    load_tracked_asset_timeframes's own logic (same source file, same
    "never a guessed/hardcoded list" discipline) rather than importing it,
    per this branch's own isolation rule (nero_core/eve/ never imports from
    nero_core/research_agent/)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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


def load_graveyard(path: Path = DEFAULT_FAILURE_PATTERNS_PATH) -> list[dict]:
    return storage.read_json_list(path)


def load_adam_history_verdict_stripped(path: Path = DEFAULT_ADAM_HYPOTHESES_PATH) -> list[dict]:
    """Adam's own past hypotheses, whitelisted down to text/mechanism fields
    only (see module docstring). NEVER reads agent_test_results.json -- no
    function in this module constructs that path at all."""
    raw = storage.read_json_list(path)
    stripped = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        stripped.append({key: record.get(key) for key in _ADAM_HISTORY_FIELDS if key in record})
    return stripped


def format_tracked_pairs(pairs: list[tuple[str, str]]) -> str:
    return ", ".join(f"{asset}/{timeframe}" for asset, timeframe in pairs) or "(none currently tracked)"


def format_graveyard(patterns: list[dict]) -> str:
    if not patterns:
        return "(none on file)"
    lines = []
    for p in patterns:
        line = f"- {p.get('name')} ({p.get('family')}): failure_pattern={p.get('failure_pattern')}"
        if p.get("fix_rationale"):
            line += f"; fix_rationale={p['fix_rationale']}"
        lines.append(line)
    return "\n".join(lines)


def format_adam_history(history: list[dict]) -> str:
    if not history:
        return "(no prior Adam-generated hypotheses on file yet)"
    lines = []
    for h in history:
        name = h.get("hypothesis_name") or "(unnamed)"
        mechanism = h.get("mechanism") or ""
        asset = h.get("asset") or "?"
        timeframe = h.get("timeframe") or "?"
        lines.append(f"- {name} ({asset}/{timeframe}): {mechanism}")
    return "\n".join(lines)


@dataclass(frozen=True)
class EveContext:
    tracked_pairs: list[tuple[str, str]]
    graveyard: list[dict]
    adam_history: list[dict]

    def as_prompt_text(self) -> str:
        return (
            "CURRENTLY TRACKED (asset, timeframe) PAIRS (real candle data exists for these -- a "
            "hypothesis for an untracked pair can never be measured or tested):\n"
            f"{format_tracked_pairs(self.tracked_pairs)}\n\n"
            "KNOWN DEAD MECHANISMS (the graveyard -- these have already been tested on this "
            "platform and failed; you are NOT required to avoid them, but repeating one exactly "
            "will very likely fail the same way):\n"
            f"{format_graveyard(self.graveyard)}\n\n"
            "PRIOR HYPOTHESES FROM ADAM (this platform's other, constrained hypothesis-generation "
            "system) -- text/mechanism only. Their outcomes are DELIBERATELY WITHHELD from you so "
            "your own proposals aren't contaminated by seeing which ones already succeeded on this "
            "same historical data:\n"
            f"{format_adam_history(self.adam_history)}\n\n"
            "ALL OF THE ABOVE IS REFERENCE ONLY. You may use any of it, ignore all of it, or "
            "propose something with no relationship to any of it -- none of it constrains what "
            "you are allowed to propose."
        )


def load_context() -> EveContext:
    return EveContext(
        tracked_pairs=load_tracked_asset_timeframes(),
        graveyard=load_graveyard(),
        adam_history=load_adam_history_verdict_stripped(),
    )
