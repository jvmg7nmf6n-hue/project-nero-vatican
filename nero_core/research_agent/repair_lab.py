"""Repair Lab v1 -- a closed loop for DIED hypotheses only. Implements exactly
what docs/repair_lab_investigation_report.md scoped and recommended: a DIED
hypothesis's aggregate failure stats are diagnosed, an LLM proposes ONE
modification within an approved repair-scope boundary, and the modification
is retested on genuinely fresh data (historical reservation or forward
paper-tracking) -- capped at 4 LAUNCHED attempts per hypothesis, full chain
transparency, never silently reusing data any attempt (or the original run)
already touched.

SCOPE LOCK (Task 1): only VERDICT_DIED hypotheses are eligible. TOO_SLOW,
UNMEASURABLE, UNTESTABLE, SURVIVED, and PROMISING-WATCHLIST are all
explicitly out of scope for v1 -- see check_eligibility below and the
investigation report's own Task 3 reasoning (TOO_SLOW's only data-supported
repair lever is a threshold change on the same gate that rejected it, the
exact gate-gaming behavior frequency_gate.py exists to prevent).

CRITICAL SAFETY: this module (and nero_core.research_agent.repair_forward_
tracker, nero_core.research_agent.repair_historical_reservation) writes ONLY
to docs/site_data/repair_attempts.json and its own dedicated SQLite file
(data/repair_lab_forward_tracking.db -- see repair_forward_tracker.py's own
docstring). It imports nothing from nero_core.execution.live_scheduler and
never references nero_core.strategies.registry's default_registry -- see
test_research_agent_no_auto_wire.py's HARD TEST, extended by
test_repair_lab_no_auto_wire.py to cover every new file this feature adds.
A SURVIVED or PROMISING-WATCHLIST repair result only ever reaches the same
human-review queue any other research-agent output does (review_status=
"pending_human_approval", per auto_tester.py's own existing convention) --
nothing here, regardless of how many attempts succeed, ever registers a
strategy variant or schedules anything.

ANTI-P-HACKING (the investigation's own critical constraint, restated here
because every function below exists to enforce it): the LLM proposes exactly
ONE modification per repair attempt, decided from the DIAGNOSIS (aggregate,
already-computed statistics about the failed run) alone, before any retest
data is seen. The diagnosis step may see aggregate stats; a retest may never
run against data any prior attempt (or the original run) in the same chain
already touched -- enforced structurally by repair_historical_reservation's
non-overlap check and by forward-testing's own by-construction freshness
(the data didn't exist before the attempt was launched). No re-rolling, no
trying multiple modifications and keeping the best -- one attempt in this
module is one committed proposal, evaluated once.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from nero_core.research_agent.auto_tester import VERDICT_SKIPPED, VERDICT_UNTESTABLE
from nero_core.research_agent.hypothesis_gen import (
    DEFAULT_PARAMETERS as LLM_DEFAULT_PARAMETERS,
    ApiKeyRejectedError,
    HypothesisGenParameters,
    NoTextBlockError,
    validate_api_key,
)
from nero_core.research_agent.rule_dsl import (
    ExitPlan,
    RuleAmbiguousError,
    StructuredRule,
    mirror_condition,
    parse_exit_plan,
    parse_structured_rule,
)
from tools.backtest_statistics import MIN_SAMPLE_SIZE, VERDICT_DIED, VERDICT_PROMISING_WATCHLIST, VERDICT_SURVIVED

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPAIR_ATTEMPTS_PATH = REPO_ROOT / "docs" / "site_data" / "repair_attempts.json"
DEFAULT_REPAIR_CANDIDATES_PATH = REPO_ROOT / "docs" / "site_data" / "repair_candidates.json"

MAX_ATTEMPTS_PER_CHAIN = 4

# Attempt-level statuses. PENDING_FORWARD_DATA is deliberately its own value,
# never conflated with any of the resolved verdicts below -- see Task 4's
# forward-testing docstring and every test in test_repair_lab_chain_record.py
# asserting this distinction holds everywhere the chain is read.
ATTEMPT_REJECTED = "REJECTED"  # proposal never launched -- duplicate or out-of-boundary
ATTEMPT_PENDING_FORWARD_DATA = "PENDING_FORWARD_DATA"
ATTEMPT_DIED = VERDICT_DIED
ATTEMPT_SURVIVED = VERDICT_SURVIVED
ATTEMPT_PROMISING_WATCHLIST = VERDICT_PROMISING_WATCHLIST

RESOLVED_ATTEMPT_STATUSES = (ATTEMPT_DIED, ATTEMPT_SURVIVED, ATTEMPT_PROMISING_WATCHLIST)
TERMINAL_FAILURE_STATUSES = (ATTEMPT_DIED,)  # a resolved-but-failed attempt; PENDING_FORWARD_DATA is NOT terminal

# Chain-level statuses.
CHAIN_OPEN = "OPEN"
CHAIN_RESOLVED = "RESOLVED"  # an attempt reached SURVIVED or PROMISING-WATCHLIST; chain stops here
CHAIN_PERMANENTLY_DIED = "PERMANENTLY_DIED"


# ---------------------------------------------------------------------------
# TASK 1 -- ELIGIBILITY GATE
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str


def check_eligibility(original_result: dict) -> EligibilityResult:
    """The FIRST check anything calling into Repair Lab must pass. Returns a
    clear, explicit EligibilityResult either way -- NEVER silently no-ops and
    NEVER silently accepts an out-of-scope hypothesis. `original_result` is
    the exact dict shape auto_tester.TestResult.to_dict() (or run_hypothesis_
    live's own "result" key) produces: at minimum "verdict" and, when verdict
    is SKIPPED, "frequency_classification".

    Only VERDICT_DIED is eligible. Every other verdict is rejected with a
    reason naming the ACTUAL classification that disqualified it (not a
    generic "not DIED") -- SKIPPED hypotheses report their frequency_
    classification (TOO_SLOW or UNMEASURABLE) specifically, since "SKIPPED"
    alone would hide which of the two distinct frequency-gate rejections this
    was. See docs/repair_lab_investigation_report.md Task 3 for the full
    reasoning on why TOO_SLOW is excluded from v1: its only data-supported
    repair lever (loosen the entry gate) is the exact gate-gaming behavior
    frequency_gate.py exists to prevent."""
    verdict = original_result.get("verdict")

    if verdict == VERDICT_DIED:
        return EligibilityResult(True, "eligible: DIED verdict clears Repair Lab v1's scope")

    if verdict == VERDICT_SKIPPED:
        freq = original_result.get("frequency_classification", "UNKNOWN")
        return EligibilityResult(
            False,
            f"not_eligible: {freq} hypotheses are out of scope for Repair Lab v1 "
            f"(see repair-lab-investigation report, Task 3)",
        )

    if verdict == VERDICT_UNTESTABLE:
        return EligibilityResult(
            False,
            "not_eligible: UNTESTABLE hypotheses are out of scope for Repair Lab v1 "
            "(see repair-lab-investigation report, Task 3) -- the entry_rule/exit_plan "
            "isn't machine-checkable at all, which is a different problem than a tested "
            "mechanism with no edge",
        )

    if verdict in (VERDICT_SURVIVED, VERDICT_PROMISING_WATCHLIST):
        return EligibilityResult(
            False,
            f"not_eligible: {verdict} hypotheses don't need repair -- Repair Lab v1 only "
            f"handles DIED hypotheses (see repair-lab-investigation report, Task 3)",
        )

    return EligibilityResult(
        False,
        f"not_eligible: unrecognized verdict {verdict!r} -- Repair Lab v1 only accepts a "
        f"result whose verdict is exactly {VERDICT_DIED!r}",
    )


# ---------------------------------------------------------------------------
# TASK 2 -- DIAGNOSIS STEP + MODIFICATION BOUNDARY ENFORCEMENT
# ---------------------------------------------------------------------------

# The 4 approved repair-scope modification types -- see docs/repair_lab_
# investigation_report.md Task 3 for the full reasoning behind this exact
# boundary. Anything outside these 4 is a new hypothesis wearing a repair
# label, not a repair, and is rejected by validate_modification below.
MODIFICATION_ENTRY_THRESHOLD = "entry_threshold"
MODIFICATION_EXIT_STRUCTURE = "exit_structure"
MODIFICATION_DIRECTION_ADD_MIRROR = "direction_add_mirror"
MODIFICATION_ASSET_TIMEFRAME_CHANGE = "asset_timeframe_change"
MODIFICATION_TYPES = (
    MODIFICATION_ENTRY_THRESHOLD, MODIFICATION_EXIT_STRUCTURE,
    MODIFICATION_DIRECTION_ADD_MIRROR, MODIFICATION_ASSET_TIMEFRAME_CHANGE,
)

FAILURE_ATTRIBUTION_SAMPLE_THINNESS = "sample_thinness"
FAILURE_ATTRIBUTION_MECHANISM = "mechanism"


def _half_trade_count(half: dict | None) -> int:
    return int(half.get("trades", 0)) if half else 0


def is_sample_thin(original_result: dict) -> bool:
    """True if EITHER half of the original DIED run fell short of MIN_SAMPLE_
    SIZE (tools.backtest_statistics's own SURVIVED/PROMISING-WATCHLIST
    adequacy bar, reused here as the same honest line for "was this a thin
    result"). Drives allowed_modification_types below -- asset_timeframe_
    change is only ever offered to the LLM when this is True, per the
    investigation's own 2-stage gate design (a pre-LLM check on data already
    in hand, never deferred entirely to the LLM's own self-report)."""
    train_n = _half_trade_count(original_result.get("train"))
    test_n = _half_trade_count(original_result.get("test"))
    return train_n < MIN_SAMPLE_SIZE or test_n < MIN_SAMPLE_SIZE


def allowed_modification_types(original_result: dict) -> tuple[str, ...]:
    """The modification types this specific DIED result is permitted to
    offer the LLM. asset_timeframe_change is EXCLUDED unless the original
    result's own sample is thin -- an adequate-sample DIED result cannot
    honestly be attributed to sample thinness, so offering the LLM that
    option at all would invite exactly the kind of asset-shopping the
    investigation's Task 3 boundary forbids."""
    base = (MODIFICATION_ENTRY_THRESHOLD, MODIFICATION_EXIT_STRUCTURE, MODIFICATION_DIRECTION_ADD_MIRROR)
    if is_sample_thin(original_result):
        return base + (MODIFICATION_ASSET_TIMEFRAME_CHANGE,)
    return base


def _format_half_stats(label: str, half: dict | None) -> str:
    if half is None or half.get("trades", 0) == 0:
        return f"{label}: no trades"
    ci = half.get("bootstrap_ci")
    if ci is None:
        ci_text = "no bootstrap CI available"
    else:
        crosses = "crosses zero" if ci.get("crosses_zero") else "does NOT cross zero"
        ci_text = f"95% CI=[{ci['lower_2_5']:.3f}, {ci['upper_97_5']:.3f}] ({crosses})"
    adequacy = "adequate sample" if half["trades"] >= MIN_SAMPLE_SIZE else "THIN sample (below MIN_SAMPLE_SIZE)"
    return f"{label}: N={half['trades']} ({adequacy}) ExpR={half['expectancy_r']:.3f}, {ci_text}"


def _format_grid_shift_consistency(grid_shift: dict | None) -> str:
    """Summarizes whether every grid-shift offset agreed with the base
    verdict -- one of the diagnostic dimensions the investigation's Task 1
    audit found genuinely informative (a disagreement flags a bar-alignment
    artifact, per LEADLAG_FOLLOW's own real graveyard precedent)."""
    if not grid_shift:
        return "no grid-shift data available for this hypothesis"
    verdicts = {label: result.get("verdict") for label, result in grid_shift.items()}
    distinct = set(verdicts.values())
    if len(distinct) <= 1:
        return f"grid-shift agrees across all {len(verdicts)} offsets tested (verdict: {next(iter(distinct), 'n/a')})"
    return f"grid-shift DISAGREES across offsets: {verdicts} -- possible bar-alignment artifact, not a clean signal"


def build_diagnosis_prompt(
    original_hypothesis: dict, original_result: dict, repair_candidates: list[dict], grid_shift: dict | None = None,
) -> str:
    """Builds the diagnosis prompt fed to the LLM, per the "good prompt" shape
    validated in docs/repair_lab_investigation_report.md's Task 1 audit:
    explicit sample-adequacy context, named CI/grid-shift dimensions, and an
    explicit, closed list of the modification types this SPECIFIC result may
    propose (never a broader "fix it" invitation)."""
    allowed = allowed_modification_types(original_result)
    thin = is_sample_thin(original_result)

    repair_candidates_text = "(none on file)"
    if MODIFICATION_ASSET_TIMEFRAME_CHANGE in allowed and repair_candidates:
        lines = [
            f"- {c.get('hypothesis_name')}: parent_strategy={c.get('parent_strategy')}, "
            f"diagnosis={c.get('diagnosis')}, proposed_fix={c.get('proposed_fix')}"
            for c in repair_candidates
        ]
        repair_candidates_text = "\n".join(lines)

    return f"""You are diagnosing a DIED trading hypothesis for Project Vatican's Repair Lab v1, a
paper-trading research platform (never real-money execution). This hypothesis already
ran through the full verification harness and DIED -- your job is to propose EXACTLY
ONE modification that targets the diagnosed weakness, not a cosmetic retune.

HYPOTHESIS: {original_hypothesis.get('hypothesis_name')} on {original_hypothesis.get('asset')}/{original_hypothesis.get('timeframe')}
ENTRY RULE: {json.dumps(original_hypothesis.get('structured_entry_rule'))}
EXIT PLAN: {json.dumps(original_hypothesis.get('structured_exit_plan'))}

RESULT: {original_result.get('reason', '')}
{_format_half_stats('TRAIN', original_result.get('train'))}
{_format_half_stats('TEST', original_result.get('test'))}
{_format_grid_shift_consistency(grid_shift)}
SAMPLE THINNESS: {"THIN -- at least one half fell below the trustworthiness floor" if thin else "ADEQUATE on both halves -- this is a real, informative negative result, not noise"}

You may propose EXACTLY ONE modification, of EXACTLY ONE of these approved types:
{"".join(f'- {t}' + chr(10) for t in allowed)}
- entry_threshold: retune the NUMERIC VALUES in structured_entry_rule only -- same fields,
  same ops, same compare_to_field as the original, never a different rule shape. Justify the
  new value(s) from the diagnosis above, never from data you have not been shown.
- exit_structure: restructure structured_exit_plan (e.g. switch from a fixed target_r_multiple
  to a dynamic_target_condition) -- structured_entry_rule must stay byte-identical to the
  original.
- direction_add_mirror: ADD a structured_entry_rule_short that is the exact mirror of the
  original structured_entry_rule (same fields/thresholds, comparison operators flipped) --
  structured_entry_rule and structured_exit_plan both stay byte-identical to the original.
  This tests the opposite direction ALONGSIDE the original rule, never replacing it.
{"""- asset_timeframe_change: move the UNCHANGED mechanism (structured_entry_rule and
  structured_exit_plan byte-identical to the original) to a DIFFERENT (asset, timeframe) pair
  that already has supporting evidence below -- you may ONLY pick a target explicitly named in
  one of these entries, never a fresh guess:
""" + repair_candidates_text if MODIFICATION_ASSET_TIMEFRAME_CHANGE in allowed else
"- asset_timeframe_change is NOT available for this hypothesis -- its own sample was adequate on both halves, so failure cannot honestly be attributed to sample thinness."}

Return STRICT JSON only, with exactly these keys:
- modification_type: exactly one of {list(allowed)}
- modification_summary: 1-2 sentences describing the change
- diagnosis_basis: 1-2 sentences citing WHICH of the numbers above this change addresses
- failure_attribution: exactly "sample_thinness" or "mechanism"
- structured_entry_rule: the (possibly unchanged) entry rule, same shape as the original
- structured_entry_rule_short: null, unless modification_type is direction_add_mirror
- structured_exit_plan: the (possibly unchanged) exit plan, same shape as the original
- asset: the asset this modification runs on (same as original unless asset_timeframe_change)
- timeframe: the timeframe this modification runs on (same as original unless asset_timeframe_change)

Do not include any field other than these nine."""


@dataclass(frozen=True)
class ModificationProposalResult:
    proposal: dict | None
    usage: dict
    cost_usd: float
    error: str | None = None


def _extract_text(content: object) -> str:
    """Re-inlined from hypothesis_gen._extract_text -- this codebase's own
    precedent (see hypothesis_gen.py's own module docstring, itself re-
    inlining news_sentiment_llm's helper) is that an underscore-prefixed
    helper in another module is that module's own implementation detail, not
    a shared API to import across modules."""
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


def propose_modification(
    original_hypothesis: dict,
    original_result: dict,
    repair_candidates: list[dict],
    api_key: str,
    grid_shift: dict | None = None,
    params: HypothesisGenParameters = LLM_DEFAULT_PARAMETERS,
) -> ModificationProposalResult:
    """ONE call, ONE proposed modification -- per the anti-p-hacking rule
    (module docstring): no re-rolling, no trying multiple modifications and
    keeping the best. Raises ApiKeyRejectedError on a 401 (matching
    hypothesis_gen.validate_api_key's own semantics); every other failure
    (network, malformed response) is returned as `error`, never raised,
    matching hypothesis_gen's own per-call error handling convention."""
    if not api_key.strip():
        return ModificationProposalResult(None, {}, 0.0, "no Claude API key configured -- no call made")

    preflight_note = validate_api_key(api_key, params)  # raises ApiKeyRejectedError on 401
    prompt = build_diagnosis_prompt(original_hypothesis, original_result, repair_candidates, grid_shift)
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
        return ModificationProposalResult(None, {}, 0.0, f"{exc.__class__.__name__}: {exc}")
    except (NoTextBlockError, json.JSONDecodeError) as exc:
        # billed (2xx, processed) but unusable -- record the real cost, matching
        # hypothesis_gen.ResponseParseError's own "never report $0.00 for a billed
        # call" discipline.
        return ModificationProposalResult(None, usage, cost, f"{exc.__class__.__name__}: {exc} (call WAS billed: ${cost:.6f})")

    note = f" (preflight note: {preflight_note})" if preflight_note else ""
    return ModificationProposalResult(data, usage, cost, None if not note else note.strip())


@dataclass(frozen=True)
class ModificationValidationResult:
    approved: bool
    reason: str


def _is_legitimate_direction_mirror(long_rule: StructuredRule, short_rule: StructuredRule) -> bool:
    """True iff `short_rule` is a legitimate mirror of `long_rule` for
    direction_add_mirror. NOT the same as "short_rule == mirror_condition
    applied to every condition" -- this project's own real precedent
    (EXT_ADX_RANGE_V3/V4_BTC_1D, tools/external_candidates_formal_test.py)
    mirrors "close < bb_lower" to "close > bb_upper", not "close > bb_lower"
    (a literal mirror_condition() call only flips the op, never compare_to_
    field) -- and leaves its shared ADX regime condition COMPLETELY UNCHANGED
    between long and short, the same "regime observation, not a price-vs-
    entry relationship" reasoning mirror_condition's own docstring already
    gives for why regime_break_condition is never mirrored.

    The actual invariant enforced: same number of conditions, same `field`
    tested at each position (the mechanism's own sensors never change), and
    each condition is EITHER completely unchanged (a shared/regime gate) OR
    has its op exactly flipped per mirror_condition's own op-flip table
    (value and/or compare_to_field free to change ONLY when the op is
    genuinely flipped -- an unchanged op requires the whole condition
    unchanged, so a threshold change can never hide behind "the op didn't
    change"). This is what actually distinguishes "testing the same
    mechanism on the opposite side" from "an independently authored rule
    smuggled in under this label"."""
    if len(long_rule.conditions) != len(short_rule.conditions):
        return False
    for long_c, short_c in zip(long_rule.conditions, short_rule.conditions):
        if long_c.field != short_c.field:
            return False
        if short_c == long_c:
            continue
        if short_c.op != mirror_condition(long_c).op:
            return False
    return True


def _entry_rule_is_threshold_only_change(original_rule: StructuredRule, proposed_rule: StructuredRule) -> bool:
    """True iff `proposed_rule` has the exact same (field, op, compare_to_field)
    sequence as `original_rule` -- only numeric `value`s may differ. A
    structural change (different field, different op, added/removed
    condition, or a changed compare_to_field) is NOT a threshold retune."""
    if len(original_rule.conditions) != len(proposed_rule.conditions):
        return False
    return all(
        o.field == p.field and o.op == p.op and o.compare_to_field == p.compare_to_field
        for o, p in zip(original_rule.conditions, proposed_rule.conditions)
    )


def _asset_timeframe_supported_by_repair_candidates(
    asset: str, timeframe: str, repair_candidates: list[dict]
) -> tuple[bool, str]:
    """Coarse, auditable substring check -- same "no fuzzy matching, fully
    auditable from the reported reason alone" philosophy hypothesis_gen.
    check_duplicate already uses -- against docs/site_data/repair_candidates.
    json's own diagnosis+proposed_fix text. Matches the project's own real
    precedent exactly: RMR_CONFIRMATION_METALS_WEEKLY's proposed_fix text
    contains the literal substring "GOLD/1week" and "SILVER/1week"."""
    needle = f"{asset}/{timeframe}".lower()
    for candidate in repair_candidates:
        haystack = f"{candidate.get('diagnosis', '')} {candidate.get('proposed_fix', '')}".lower()
        if needle in haystack:
            return True, str(candidate.get("hypothesis_name", ""))
    return False, ""


def validate_modification(
    original_hypothesis: dict, proposal: dict, repair_candidates: list[dict]
) -> ModificationValidationResult:
    """The hard boundary enforcement: if the LLM's proposal falls outside the
    approved repair-scope (docs/repair_lab_investigation_report.md Task 3),
    this rejects it and no attempt is ever launched. Every rejection reason
    is specific enough to be logged verbatim (Task 6's chain record)."""
    mtype = proposal.get("modification_type")
    if mtype not in MODIFICATION_TYPES:
        return ModificationValidationResult(
            False, f"rejected: modification_type {mtype!r} is not one of the approved repair-scope types {MODIFICATION_TYPES}"
        )

    try:
        original_rule = parse_structured_rule(original_hypothesis.get("structured_entry_rule"))
        original_exit = parse_exit_plan(original_hypothesis.get("structured_exit_plan"))
    except RuleAmbiguousError as exc:
        return ModificationValidationResult(
            False, f"rejected: the original hypothesis's own entry_rule/exit_plan isn't machine-checkable, "
                   f"cannot validate a repair against it: {exc}"
        )

    try:
        proposed_rule = parse_structured_rule(proposal.get("structured_entry_rule"))
        proposed_exit = parse_exit_plan(proposal.get("structured_exit_plan"))
    except RuleAmbiguousError as exc:
        return ModificationValidationResult(
            False, f"rejected: proposed structured_entry_rule/structured_exit_plan isn't machine-checkable: {exc}"
        )

    proposed_short_raw = proposal.get("structured_entry_rule_short")
    original_asset, original_timeframe = str(original_hypothesis.get("asset", "")), str(original_hypothesis.get("timeframe", ""))
    proposed_asset = str(proposal.get("asset") or original_asset)
    proposed_timeframe = str(proposal.get("timeframe") or original_timeframe)
    asset_timeframe_unchanged = proposed_asset == original_asset and proposed_timeframe == original_timeframe

    if mtype != MODIFICATION_ASSET_TIMEFRAME_CHANGE and not asset_timeframe_unchanged:
        return ModificationValidationResult(
            False, f"rejected: modification_type={mtype!r} must keep asset/timeframe unchanged "
                   f"({original_asset}/{original_timeframe}) -- got {proposed_asset}/{proposed_timeframe}"
        )

    if mtype == MODIFICATION_DIRECTION_ADD_MIRROR:
        if proposed_rule != original_rule:
            return ModificationValidationResult(
                False, "rejected: direction_add_mirror must keep structured_entry_rule byte-identical to the "
                       "original -- the mirror is ADDED, never a replacement"
            )
        if proposed_exit != original_exit:
            return ModificationValidationResult(
                False, "rejected: direction_add_mirror must keep structured_exit_plan byte-identical to the original"
            )
        if proposed_short_raw is None:
            return ModificationValidationResult(False, "rejected: direction_add_mirror must set structured_entry_rule_short -- nothing was added")
        try:
            proposed_short = parse_structured_rule(proposed_short_raw)
        except RuleAmbiguousError as exc:
            return ModificationValidationResult(False, f"rejected: structured_entry_rule_short isn't machine-checkable: {exc}")
        if not _is_legitimate_direction_mirror(original_rule, proposed_short):
            return ModificationValidationResult(
                False, "rejected: structured_entry_rule_short is not a legitimate mirror of the original rule -- "
                       "every condition must test the same field as its long-rule counterpart, and must be either "
                       "completely unchanged (a shared regime gate, matching regime_break_condition's own "
                       "never-mirrored precedent) or have its comparison operator exactly flipped "
                       "(rule_dsl.mirror_condition's own op-flip semantics) -- direction_add_mirror only permits "
                       "testing the SAME mechanism on the opposite side, not an independently authored short rule"
            )
        return ModificationValidationResult(True, "approved: direction_add_mirror -- original rule unchanged, short leg is a legitimate mirror")

    if mtype == MODIFICATION_ASSET_TIMEFRAME_CHANGE:
        if asset_timeframe_unchanged:
            return ModificationValidationResult(
                False, "rejected: modification_type=asset_timeframe_change but asset/timeframe are unchanged "
                       "from the original -- nothing was actually changed"
            )
        if proposed_rule != original_rule or proposed_exit != original_exit:
            return ModificationValidationResult(
                False, "rejected: asset_timeframe_change must keep the mechanism (structured_entry_rule and "
                       "structured_exit_plan) byte-identical to the original -- only WHERE it runs may change, "
                       "per docs/site_data/repair_candidates.json's own precedent (RMR_CONFIRMATION_METALS_WEEKLY "
                       "keeps the mechanism, moves the asset)"
            )
        if proposed_short_raw is not None:
            return ModificationValidationResult(False, "rejected: asset_timeframe_change must not also add a direction change -- one modification per attempt")
        if proposal.get("failure_attribution") != FAILURE_ATTRIBUTION_SAMPLE_THINNESS:
            return ModificationValidationResult(
                False, "rejected: asset_timeframe_change requires the diagnosis to attribute failure to sample "
                       "thinness, not the mechanism"
            )
        supported, matched_name = _asset_timeframe_supported_by_repair_candidates(proposed_asset, proposed_timeframe, repair_candidates)
        if not supported:
            return ModificationValidationResult(
                False, f"rejected: no supporting evidence for {proposed_asset}/{proposed_timeframe} in "
                       f"docs/site_data/repair_candidates.json -- asset/timeframe changes must be justified by "
                       f"evidence already on file, never a fresh guess"
            )
        return ModificationValidationResult(True, f"approved: asset_timeframe_change to {proposed_asset}/{proposed_timeframe}, supported by repair_candidates.json entry {matched_name!r}")

    if mtype == MODIFICATION_ENTRY_THRESHOLD:
        if proposed_short_raw is not None:
            return ModificationValidationResult(False, "rejected: entry_threshold must not also add a direction change -- one modification per attempt")
        if not _entry_rule_is_threshold_only_change(original_rule, proposed_rule):
            return ModificationValidationResult(
                False, "rejected: entry_threshold must keep the same fields/ops/compare_to_field as the "
                       "original entry rule, retuning only numeric values -- this proposal changed the rule's "
                       "structure, not just a threshold"
            )
        return ModificationValidationResult(True, "approved: entry_threshold -- same rule structure, retuned values")

    if mtype == MODIFICATION_EXIT_STRUCTURE:
        if proposed_short_raw is not None:
            return ModificationValidationResult(False, "rejected: exit_structure must not also add a direction change -- one modification per attempt")
        if proposed_rule != original_rule:
            return ModificationValidationResult(False, "rejected: exit_structure must keep structured_entry_rule byte-identical to the original -- only the exit may change")
        return ModificationValidationResult(True, "approved: exit_structure -- entry rule unchanged, exit mechanics restructured")

    return ModificationValidationResult(False, "rejected: unhandled modification_type")  # unreachable given the check above


def load_repair_candidates(path: Path = DEFAULT_REPAIR_CANDIDATES_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
