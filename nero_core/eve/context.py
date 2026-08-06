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
from dataclasses import dataclass, field
from pathlib import Path

from nero_core.eve import storage

REPO_ROOT = storage.REPO_ROOT
DEFAULT_QUANT_METRICS_PATH = REPO_ROOT / "docs" / "site_data" / "quant_metrics.json"
DEFAULT_FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"
DEFAULT_ADAM_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"
# CC-1 directive, item B2 (2026-08-06): near-misses are a DELIBERATE,
# narrowly-scoped exception to this module's own verdict-stripping
# principle above -- see load_near_misses's own docstring for exactly what
# gets shown and why it's safe/intentional, not a silent contradiction of
# the "outcomes deliberately withheld" framing used for Adam's history.
DEFAULT_EVE_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"
# Real per-entry size measured against the one real near-miss on file
# (BTC_MOMENTUM_IGNITION): mechanism text alone is 772 chars (~193 tokens
# at ~4 chars/token), plus name/p-values/verdict framing -- call it ~250-
# 300 tokens/entry realistically. 10 entries is a real, generous multiple
# of the current real count (1) while keeping the whole block a modest
# fraction of the system prompt (~2500-3000 tokens worst case) -- smaller
# than failure_patterns.json's own FAILURE_PATTERNS_CAP=30 (graveyard_
# distillation.py), which is the right direction: a near-miss entry
# carries a FULL mechanism paragraph, a graveyard entry a condensed
# why_it_died synthesis, so more of them fit before the same budget bites.
NEAR_MISS_CAP = 10

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


# CC-1 directive, item B2 (2026-08-06): the two REAL shapes of near-miss
# found by inspecting docs/site_data/eve_hypotheses.json directly, not
# guessed. Half 1 (the directive's own canonical example, BTC_MOMENTUM_
# IGNITION): the IS p-value clears FDR significance but OOS does not --
# checked via fdr_survives_is/fdr_survives_oos, NOT verdict_is/verdict_oos
# (a record's overall verdict can be DIED even when its own p_value_is is
# FDR-significant -- confirmed real, BTC_MOMENTUM_IGNITION's own
# verdict_is is "DIED" despite fdr_survives_is=True; verdict
# classification and FDR significance are computed by different logic and
# can disagree). Half 2, REFINED from the directive's own literal wording
# ("IS produced a real verdict"): requires IS to be a genuinely POSITIVE
# verdict (PROMISING_WATCHLIST or SURVIVED), not merely non-null -- the
# literal wording alone would also match a record whose verdict_is is
# DIED (real, confirmed data: PAXG_PEG_REVERSION, verdict_is=DIED,
# verdict_oos=INSUFFICIENT_SAMPLE) -- feeding a DIED-IS-half hypothesis
# back as an "invitation to refine" would misrepresent a genuinely dead
# idea as promising material, undermining the whole point of this channel.
_NEAR_MISS_POSITIVE_VERDICTS = ("PROMISING_WATCHLIST", "SURVIVED")


def _is_near_miss(record: dict) -> bool:
    fdr_is, fdr_oos = record.get("fdr_survives_is"), record.get("fdr_survives_oos")
    if fdr_is is True and fdr_oos is not True:
        return True
    verdict_is, verdict_oos = record.get("verdict_is"), record.get("verdict_oos")
    return verdict_is in _NEAR_MISS_POSITIVE_VERDICTS and verdict_oos == "INSUFFICIENT_SAMPLE"


def load_near_misses(path: Path = DEFAULT_EVE_HYPOTHESES_PATH, cap: int = NEAR_MISS_CAP) -> list[dict]:
    """A NEAR_MISS is real information this platform currently discards
    entirely once a hypothesis's verdict_combined is DIED -- see _is_near_
    miss above for the exact, real-data-derived definition. Deliberately
    NOT gated on graveyard membership or on which agent proposed it
    originally: today this can only surface Eve's own past hypotheses
    (eve_hypotheses.json is the only file that carries per-half p_value_is/
    p_value_oos/fdr_survives_is/fdr_survives_oos at all -- Adam's own
    harness, tools.backtest_statistics's bootstrap-CI-based
    classify_verdict, computes significance differently and has no
    directly equivalent per-hypothesis field; extending this same
    definition to Adam's data is a real, separate future decision, not
    made here).

    Returns only the fields Eve actually needs to understand WHAT happened
    without also being handed a verdict framing -- name, mechanism, and
    the real IS/OOS p-values, capped at `cap` entries (oldest N by
    proposed_at, matching failure_patterns.json's own no-particular-
    reordering convention -- see format_near_misses for the "invitation
    to refine, not a verdict" framing applied at display time, not here)."""
    records = storage.read_json_list(path)
    near_misses = []
    for record in records:
        if not isinstance(record, dict) or not _is_near_miss(record):
            continue
        raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
        near_misses.append({
            "hypothesis_name": raw.get("hypothesis_name"),
            "mechanism": raw.get("mechanism"),
            "session_id": record.get("session_id"),
            "p_value_is": record.get("p_value_is"),
            "p_value_oos": record.get("p_value_oos"),
            "verdict_is": record.get("verdict_is"),
            "verdict_oos": record.get("verdict_oos"),
        })
    return near_misses[:cap]


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


def format_near_misses(near_misses: list[dict]) -> str:
    if not near_misses:
        return "(none on file)"
    lines = []
    for m in near_misses:
        name = m.get("hypothesis_name") or "(unnamed)"
        mechanism = m.get("mechanism") or ""
        p_is, p_oos = m.get("p_value_is"), m.get("p_value_oos")
        p_is_text = f"{p_is:.4f}" if isinstance(p_is, (int, float)) else "n/a"
        p_oos_text = f"{p_oos:.4f}" if isinstance(p_oos, (int, float)) else "n/a"
        lines.append(f"- {name}: {mechanism} (in-sample p={p_is_text}, out-of-sample p={p_oos_text})")
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
    near_misses: list[dict] = field(default_factory=list)

    def as_prompt_text(self) -> str:
        return (
            "CURRENTLY TRACKED (asset, timeframe) PAIRS (real candle data exists for these -- a "
            "hypothesis for an untracked pair can never be measured or tested):\n"
            f"{format_tracked_pairs(self.tracked_pairs)}\n\n"
            "KNOWN DEAD MECHANISMS (the graveyard -- these have already been tested on this "
            "platform and failed; you are NOT required to avoid them, but repeating one exactly "
            "will very likely fail the same way):\n"
            f"{format_graveyard(self.graveyard)}\n\n"
            "NEAR-MISSES (a DIFFERENT thing from the graveyard above -- these are NOT dead; a "
            "near-miss is a hypothesis whose in-sample half showed a real, statistically "
            "significant signal that its out-of-sample half could not yet confirm (either the "
            "out-of-sample p-value failed significance, or there wasn't enough out-of-sample data "
            "to measure at all). This is an INVITATION TO REFINE, not a verdict and not a "
            "recommendation -- the in-sample signal might be real and just needs a fuller "
            "out-of-sample sample, or it might not replicate at all; you don't know which yet, and "
            "neither do we. If you choose to build on one of these, declare it explicitly via "
            "derived_from (see the DSL vocabulary section) so it's credited as a deliberate "
            "refinement, not flagged as an undeclared near-duplicate:\n"
            f"{format_near_misses(self.near_misses)}\n\n"
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
        near_misses=load_near_misses(),
    )
