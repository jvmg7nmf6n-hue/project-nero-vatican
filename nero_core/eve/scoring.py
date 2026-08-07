"""Phase 3 -- scoring: measurement, NEVER gating (spec's own words). Every
Eve hypothesis gets a testability classification and, when testable, an
in-sample and out-of-sample verdict from Adam's own unmodified statistical
harness -- nothing here ever prevents a hypothesis from being recorded or
reported, no matter how it scores.

***** THE ONE DOCUMENTED EXCEPTION TO THIS BRANCH'S ISOLATION RULE *****
Every OTHER module under nero_core/eve/ imports nothing from
nero_core.research_agent (confirmed by test_eve_no_auto_wire.py). THIS
module is the sole, narrow exception, and it is deliberate: spec 3.1 ("Every
machine-checkable Eve hypothesis runs through the exact same auto_tester.py
/ classify_verdict / bootstrap_mean_r_ci path Adam's go through, reused
UNMODIFIED") cannot be satisfied any other way that doesn't undermine the
guarantee it exists for. Reinlining auto_tester.py's ~750-line backtest
engine (the way every OTHER Eve module reinlines a small private helper)
would GUARANTEE eventual drift from Adam's real harness as it evolves,
which is exactly the property "same harness, reused unmodified" is meant to
rule out -- a stale copy would make the whole Eve-vs-Adam comparison
meaningless in exactly the way a live import cannot. So this module imports:
  - nero_core.research_agent.rule_dsl (parse_bidirectional_entry_rules,
    parse_exit_plan, RuleAmbiguousError) -- to decide testability, the SAME
    parser frequency_gate.py/auto_tester.py already use.
  - nero_core.research_agent.auto_tester.test_hypothesis -- to actually run
    a TESTABLE hypothesis through the real backtest/frequency-gate harness.
  - tools.backtest_statistics (classify_verdict) -- NOT under
    nero_core/research_agent/ at all, so no isolation concern there in the
    first place.
This module imports NOTHING else from nero_core.research_agent -- no
eligibility gate, no modification whitelist, no single-proposal rule, no
live_scheduler/default_registry reference (confirmed by
test_eve_no_auto_wire.py's own scoring-module-specific check, which asserts
the import set is exactly this named list and nothing more).

TESTABILITY vs VERDICT (spec 3.2): testability is a property of the
hypothesis's SHAPE (can rule_dsl parse it at all), never a statistical
outcome. verdict_is/verdict_oos are populated ONLY when testability ==
TESTABLE.

IS/OOS SPLIT (spec 3.3 -- flagged design decision, see closing report):
auto_tester.test_hypothesis's own returned `verdict` already REQUIRES both
halves (chronological 70/30 train/test split) to look good together --
useful as a reference (`verdict_combined` below) but not itself a clean
"in-sample" or "out-of-sample" verdict. This module derives verdict_is/
verdict_oos by calling classify_verdict SEPARATELY on the train half
against ITSELF and the test half against ITSELF -- reusing the exact same
function, unmodified, twice, rather than needing a second harness path.
Zero-trade halves are labeled INSUFFICIENT_SAMPLE directly (never DIED --
"never fired" is not evidence of a losing edge); a positive-expectancy half
below MIN_SAMPLE_SIZE is also relabeled INSUFFICIENT_SAMPLE, splitting
Adam's single PROMISING-WATCHLIST bucket into Eve's two distinct SURVIVED/
DIED/PROMISING_WATCHLIST/INSUFFICIENT_SAMPLE outcomes using ONLY inputs
classify_verdict itself already examines (trades, expectancy_r, ci) --
never re-deriving its DIED/SURVIVED branch logic.

P-VALUE APPROXIMATION (spec 3.4 -- flagged design decision): bootstrap_
mean_r_ci returns only the percentile [2.5, 97.5] CI, not the raw resampled-
means distribution (computed internally, then discarded) or a p-value.
normal_approx_p_value below derives an APPROXIMATE two-sided p-value from
the CI's own bounds (SE ~= CI width / (2*1.96), z = mean_r/SE, p from the
standard normal CDF) -- explicitly an approximation, not an exact bootstrap
p-value, since the harness itself is never modified to expose the raw
distribution.

P-VALUE RELIABILITY GATE (added after a real K=200 random-baseline run
exposed a live bug -- see docs/investigations/eve_engine_v1_report.md):
bootstrap resampling on a half with very few trades (most commonly exactly
1) always resamples the SAME single value, collapsing lower_2_5==upper_97_5
to a zero-width CI. The original version of normal_approx_p_value treated
that degenerate SE as "p=0.0" (maximally significant) whenever mean_r != 0
-- fabricating a significant-looking p-value from a single data point. Two
independent guards now exist, and BOTH fail toward "no p-value," never
toward significance:
  1. normal_approx_p_value itself returns None (not 0.0/1.0) whenever the
     CI's own implied standard error is zero or numerically indistinguishable
     from zero (see _MIN_RELIABLE_SE below) -- a degenerate CI is not
     evidence of anything, regardless of which half or how many trades
     produced it.
  2. score_hypothesis additionally nulls p_value_is/p_value_oos outright
     whenever that half's own trade count is below MIN_SAMPLE_SIZE (tools.
     backtest_statistics's own constant, reused unmodified) -- even a half
     with, say, 15 trades and a non-degenerate CI is still underpowered by
     this project's own sample-size bar, and its p-value/FDR-family
     membership should not imply otherwise.
Neither guard touches verdict_is/verdict_oos/verdict_combined in any way --
those are computed entirely independently by _map_half_verdict, which
already has its own, separate INSUFFICIENT_SAMPLE handling. A hypothesis's
verdict is unaffected by whether its p-value happens to be null --
test_eve_scoring_fdr.py has a dedicated regression test proving exactly
this (VerdictUnaffectedByPValueGateTest).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from nero_core.research_agent.auto_tester import VERDICT_UNTESTABLE as ADAM_VERDICT_UNTESTABLE
from nero_core.research_agent.auto_tester import test_hypothesis as adam_test_hypothesis
from nero_core.research_agent.rule_dsl import RuleAmbiguousError, parse_bidirectional_entry_rules, parse_exit_plan
from tools.backtest_statistics import MIN_SAMPLE_SIZE, VERDICT_DIED, VERDICT_SURVIVED, classify_verdict

class DataSourceRefusedError(Exception):
    """Raised by a scoring-context candles_provider (see
    nero_core.eve.pipeline.default_candles_provider) when asked for an
    (asset, timeframe) pair it refuses to silently degrade for -- e.g. no
    full-history research export exists, only the website's 200-row display
    export. Before this existed, that situation returned the 200-row frame
    with no signal it wasn't real backtest history: a scored verdict on
    GOLD or EURUSD looked identical to one on BTC/4h (the only pair that has
    ever had a random-hypothesis baseline computed against it) even though
    the two ran on completely different amounts of history. score_hypothesis
    catches this specific exception and records an explicit,
    grep-able refusal (candle_data_source="refused") instead of either a
    silent substitution or a null verdict indistinguishable from "no candle
    data was available anywhere for this pair." Never caught anywhere else
    in this module -- a caller that wants degraded data on purpose must say
    so explicitly by passing a different candles_provider, not rely on this
    being swallowed."""


TESTABILITY_TESTABLE = "TESTABLE"
TESTABILITY_UNTESTABLE_BY_DSL = "UNTESTABLE_BY_DSL"
# Added after Session 0-B's own follow-up finding: classify_testability's
# rule_dsl-parseability check and auto_tester.test_hypothesis's own,
# DEEPER "can I actually test this" check (missing/unparseable
# generated_at -- structurally supposed to be unreachable now that
# hypothesis_shapes._inject_generated_at always stamps a real one server
# -side, but this reconciliation is a hard invariant, not conditioned on
# that fix holding forever) are two DIFFERENT questions. Before this
# constant existed, a hypothesis that failed the second, deeper check
# still carried `testability: "TESTABLE"` (set earlier by classify_
# testability and never revisited) sitting next to `verdict_combined:
# "UNTESTABLE"` (Adam's own literal harness string) -- a record that
# asserted testable and untestable about the same hypothesis at once.
# score_hypothesis below downgrades `testability` to this value whenever
# that happens, so the two fields can never again disagree.
TESTABILITY_UNTESTABLE_BY_HARNESS = "UNTESTABLE_BY_HARNESS"

VERDICT_EVE_SURVIVED = "SURVIVED"
VERDICT_EVE_DIED = "DIED"
VERDICT_EVE_PROMISING_WATCHLIST = "PROMISING_WATCHLIST"
VERDICT_EVE_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"

DERIVATIVE_SIMILARITY_THRESHOLD = 0.6
DEFAULT_FDR_ALPHA = 0.05
DERIVATIVE_TAG_NAME = "DERIVATIVE"
# Added for the CC-1 review's item 1 (confirmed gap: eve_hypotheses.json was
# write-only, and tag_derivative was only ever called with adam_history --
# nothing stopped Eve re-proposing her own past idea and having it counted
# as a fresh independent data point). Distinct tag name from DERIVATIVE_TAG_
# NAME so a record's contamination_tags can never conflate "converges with
# something Adam already proposed" and "Eve has already proposed this
# herself" -- see apply_self_derivative_tags below.
SELF_DERIVATIVE_TAG_NAME = "SELF_DERIVATIVE"
# CC-1 directive, item B1 (2026-08-06): a hypothesis similar enough to a
# prior one to earn a SELF_DERIVATIVE-shaped similarity flag, but which
# DECLARES that prior hypothesis as its parent via a validated
# `derived_from` field (see validate_derived_from), is a deliberate
# refinement, not lazy repetition -- tagged REFINEMENT instead and kept
# IN the FDR family (apply_fdr_correction), unlike SELF_DERIVATIVE. Same
# similarity method/threshold, same tag_derivative call -- only the tag
# name differs, and only for the ONE flag matching the declared parent
# (an unrelated undeclared match on a DIFFERENT prior still gets tagged
# SELF_DERIVATIVE and still excludes the record from FDR membership via
# is_self_derivative below).
REFINEMENT_TAG_NAME = "REFINEMENT"
# The 4 required sub-fields when a hypothesis declares derived_from -- see
# validate_derived_from. Partial (some but not all present/non-empty) is
# a hard validation error, never silently accepted.
DERIVED_FROM_REQUIRED_FIELDS = ("parent_hypothesis_name", "parent_session_id", "what_changed", "why_this_change")


def classify_testability(raw_hypothesis: dict) -> tuple[str, str]:
    """TESTABLE iff BOTH structured_entry_rule and structured_exit_plan
    parse without RuleAmbiguousError via rule_dsl -- the ONE place this is
    decided, reused unmodified. Never crashes on a malformed raw_hypothesis
    (e.g. not even a dict, or missing the relevant keys entirely) -- that is
    just as much "not machine-checkable" as an explicit RuleAmbiguousError."""
    try:
        parse_bidirectional_entry_rules(raw_hypothesis)
        parse_exit_plan(raw_hypothesis.get("structured_exit_plan"))
    except RuleAmbiguousError as exc:
        return TESTABILITY_UNTESTABLE_BY_DSL, str(exc)
    except (AttributeError, TypeError, KeyError) as exc:
        return TESTABILITY_UNTESTABLE_BY_DSL, f"{exc.__class__.__name__}: {exc}"
    return TESTABILITY_TESTABLE, "structured_entry_rule and structured_exit_plan both parse via rule_dsl"


def validate_derived_from(raw_hypothesis: dict, known_hypothesis_names: set) -> tuple[bool, str]:
    """CC-1 directive, item B1: `derived_from` is an OPTIONAL declared field
    -- null/absent is always valid (nothing declared). When present, it
    must be a dict with ALL FOUR of DERIVED_FROM_REQUIRED_FIELDS non-empty
    (partial is a hard error, mirroring classify_testability's own "never
    guess a substitute" discipline) -- AND `parent_hypothesis_name` must
    actually appear in `known_hypothesis_names` (the real union of Adam's
    history, Eve's own prior-session history, and this session's own
    already-finalized hypotheses so far -- see session.py's own call site).
    Naming a never-proposed parent is a hard error: this is what makes
    REFINEMENT tagging (apply_self_derivative_tags) trustworthy -- a
    declared parent that was never validated against real data would let
    any similarity match be waved through as "deliberate," defeating the
    whole point of distinguishing refinement from repetition.

    Returns (True, "") when valid (including the null case). Returns
    (False, reason) otherwise -- callers route this through the SAME
    retry-or-finalize mechanism classify_testability's own DSL errors
    already use (see session.py's _process_proposed_hypotheses), not a
    silent rejection."""
    derived_from = raw_hypothesis.get("derived_from") if isinstance(raw_hypothesis, dict) else None
    if derived_from is None:
        return True, ""
    if not isinstance(derived_from, dict):
        return False, f"derived_from must be a JSON object (or omitted entirely), got {type(derived_from).__name__}"

    missing_or_empty = [
        f for f in DERIVED_FROM_REQUIRED_FIELDS
        if not isinstance(derived_from.get(f), str) or not derived_from.get(f).strip()
    ]
    if missing_or_empty:
        return False, (
            f"derived_from is present but missing/empty required field(s) {missing_or_empty} -- all of "
            f"{list(DERIVED_FROM_REQUIRED_FIELDS)} must be non-empty strings when derived_from is declared "
            f"at all, or omit derived_from entirely for a fresh (non-refinement) hypothesis"
        )

    parent_name = derived_from["parent_hypothesis_name"]
    if parent_name not in known_hypothesis_names:
        return False, (
            f"derived_from.parent_hypothesis_name {parent_name!r} does not match any hypothesis this "
            f"platform has a real record of (checked against Adam's history, your own prior-session "
            f"history, and everything already proposed this session) -- a declared parent must be a real, "
            f"previously-proposed hypothesis, never invented"
        )
    return True, ""


def _map_half_verdict(stats) -> str | None:
    """`stats` is a nero_core.research_agent.auto_tester.HalfStats or None
    (None means test_hypothesis never reached the backtest at all -- gate
    rejection or parse failure upstream; distinct from a half that WAS
    backtested but produced zero trades, which IS an INSUFFICIENT_SAMPLE
    verdict, not a null one)."""
    if stats is None:
        return None
    if stats.trades == 0:
        return VERDICT_EVE_INSUFFICIENT_SAMPLE
    stats_dict = {"expectancy_r": stats.expectancy_r, "trades": stats.trades, "ci": stats.ci}
    adam_verdict = classify_verdict(stats_dict, stats_dict, min_sample_size=MIN_SAMPLE_SIZE)
    if adam_verdict == VERDICT_DIED:
        return VERDICT_EVE_DIED
    if adam_verdict == VERDICT_SURVIVED:
        return VERDICT_EVE_SURVIVED
    # PROMISING-WATCHLIST from a self-compared half: positive expectancy,
    # but not (adequate sample AND CI clears zero). Split using `trades`
    # alone (already one of classify_verdict's own inputs).
    if stats.trades < MIN_SAMPLE_SIZE:
        return VERDICT_EVE_INSUFFICIENT_SAMPLE
    return VERDICT_EVE_PROMISING_WATCHLIST


def _standard_normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# Below this, the CI's implied standard error is treated as degenerate --
# not just exactly zero (the common case: a single-trade half, where
# resampling with replacement always draws that one value, so
# lower_2_5 == upper_97_5 exactly) but anything numerically indistinguishable
# from it, guarding against floating-point noise producing a tiny nonzero SE
# from an otherwise-degenerate resample.
_MIN_RELIABLE_SE = 1e-9


def normal_approx_p_value(ci) -> float | None:
    """See module docstring's P-VALUE APPROXIMATION and P-VALUE RELIABILITY
    GATE sections. Returns None (never a fabricated number) if `ci` is None,
    or if the CI's own implied standard error is zero/near-zero -- a
    degenerate CI is not evidence of anything, and this function must NEVER
    fail toward significance on ambiguous input."""
    if ci is None:
        return None
    se = (ci.upper_97_5 - ci.lower_2_5) / (2 * 1.959964)
    if se <= _MIN_RELIABLE_SE:
        return None
    z = ci.mean_r / se
    return 2.0 * (1.0 - _standard_normal_cdf(abs(z)))


def benjamini_hochberg(p_values: list[float], alpha: float = DEFAULT_FDR_ALPHA) -> list[bool]:
    """Standard BH step-up FDR procedure, pure stdlib (no scipy in
    requirements.txt). Returns one bool per input p-value, same order,
    True iff that hypothesis survives FDR correction at `alpha` across the
    whole family passed in."""
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    sorted_p = [p_values[i] for i in order]
    thresholds = [(rank + 1) / n * alpha for rank in range(n)]
    largest_k = -1
    for k in range(n):
        if sorted_p[k] <= thresholds[k]:
            largest_k = k
    survives = [False] * n
    for rank in range(largest_k + 1):
        survives[order[rank]] = True
    return survives


def _p_value_for_half(stats) -> float | None:
    """None (never a fabricated number) if `stats` is None, if its trade
    count is below MIN_SAMPLE_SIZE (see the module docstring's P-VALUE
    RELIABILITY GATE), or if normal_approx_p_value itself declines (a
    degenerate CI). This is what keeps an underpowered half OUT of the FDR
    family entirely (apply_fdr_correction already skips any record whose
    p-value is None) -- it does NOT touch verdict_is/verdict_oos, which are
    computed independently by _map_half_verdict."""
    if stats is None or stats.trades < MIN_SAMPLE_SIZE:
        return None
    return normal_approx_p_value(stats.ci)


def score_hypothesis(record: dict, candles_provider: Callable[[str, str], object], now: datetime | None = None) -> dict:
    """Scores ONE hypothesis record (nero_core.eve.hypothesis_shapes's own
    shape). Returns a NEW dict -- never mutates `record`. `candles_provider`
    matches nero_core.research_agent.pipeline's own (asset, timeframe) ->
    DataFrame|None convention."""
    now = now or datetime.now(timezone.utc)
    raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
    testability, testability_reason = classify_testability(raw)

    updated = dict(record)
    updated["testability"] = testability
    updated["testability_reason"] = testability_reason
    updated["verdict_is"] = None
    updated["verdict_oos"] = None
    updated["verdict_combined"] = None
    updated["p_value_is"] = None
    updated["p_value_oos"] = None
    updated["frequency_classification"] = None
    updated["measured_trades_per_year"] = None
    # Tagged on every scored record, success or refusal -- see
    # DataSourceRefusedError's own docstring: a null verdict must never be
    # ambiguous between "no data anywhere" and "data existed but was refused
    # as an unapproved substitute."
    updated["candle_data_source"] = None
    updated["candle_row_count"] = None

    if testability != TESTABILITY_TESTABLE:
        return updated

    asset = raw.get("asset")
    timeframe = raw.get("timeframe")
    if not asset or not timeframe:
        updated["testability_reason"] += " (missing asset/timeframe -- verdict cannot be computed)"
        return updated

    try:
        candles = candles_provider(asset, timeframe)
    except DataSourceRefusedError as exc:
        updated["candle_data_source"] = "refused"
        updated["testability_reason"] += f" (candle data source refused rather than substituted: {exc})"
        return updated

    if candles is None or len(candles) == 0:
        updated["testability_reason"] += " (no candle data available for this asset/timeframe -- verdict cannot be computed)"
        return updated

    updated["candle_data_source"] = getattr(candles, "attrs", {}).get("data_source", "unknown")
    updated["candle_row_count"] = len(candles)

    result = adam_test_hypothesis(raw, candles, now=now)
    updated["verdict_combined"] = result.verdict
    if result.verdict == ADAM_VERDICT_UNTESTABLE:
        # Reconcile rather than let `testability: "TESTABLE"` sit next to
        # `verdict_combined: "UNTESTABLE"` -- see TESTABILITY_UNTESTABLE_BY_
        # HARNESS's own module-level comment. `result.reason` already
        # carries auto_tester's own human-readable explanation (e.g. a
        # missing/unparseable generated_at, or its own internal re-parse
        # failure) -- reused verbatim, not re-derived.
        updated["testability"] = TESTABILITY_UNTESTABLE_BY_HARNESS
        updated["testability_reason"] = result.reason
    updated["frequency_classification"] = result.frequency_classification
    updated["measured_trades_per_year"] = result.measured_trades_per_year
    updated["verdict_is"] = _map_half_verdict(result.train)
    updated["verdict_oos"] = _map_half_verdict(result.test)
    updated["p_value_is"] = _p_value_for_half(result.train)
    updated["p_value_oos"] = _p_value_for_half(result.test)
    return updated


def score_all(records: list[dict], candles_provider: Callable[[str, str], object], now: datetime | None = None) -> list[dict]:
    return [score_hypothesis(r, candles_provider, now=now) for r in records]


def is_self_derivative(record: dict) -> bool:
    """True iff `record` carries a SELF_DERIVATIVE contamination tag (see
    apply_self_derivative_tags below). Public (no leading underscore) --
    apply_fdr_correction uses this to exclude a self-derivative hypothesis
    from the FDR family, and nero_core.eve.pipeline uses it directly to
    count self-derivative hypotheses per session for ablation_metadata (CC-1
    review item 1d), rather than duplicating the contamination_tags-scanning
    logic in a second place. A record can have MULTIPLE contamination_tags
    entries (e.g. both DERIVATIVE and SELF_DERIVATIVE); any one
    SELF_DERIVATIVE tag is enough."""
    return any(t.get("tag") == SELF_DERIVATIVE_TAG_NAME for t in (record.get("contamination_tags") or []))


def is_freshness_disqualified(record: dict) -> bool:
    """True iff `record` was disqualified by check_freshness_disqualification
    (CC-1 directive item 7, see apply_freshness_disqualification below).
    Public for the same reason is_self_derivative is: apply_fdr_correction
    uses it to exclude a disqualified record from the FDR family (item 7c),
    and callers elsewhere can check it without re-scanning the record's
    raw flag list."""
    return bool(record.get("freshness_disqualified", False))


def apply_freshness_disqualification(scored_records: list[dict], session_flags: list[dict]) -> list[dict]:
    """CC-1 directive item 7: applies check_freshness_disqualification's
    session-level flags to every record in `scored_records` -- see that
    function's own PER-HYPOTHESIS ATTRIBUTION LIMITATION docstring section
    for why this is session-wide, not selective. ALWAYS sets
    freshness_disqualified explicitly (True or False, never left absent) so
    a reader can distinguish "checked, found clean" from "never checked."
    Item 7a's audit fields are stamped per-record via
    freshness_disqualification_reason, with hypothesis_name filled in from
    each record's own raw_hypothesis (session_flags themselves carry
    hypothesis_name=None, since check_freshness_disqualification cannot know
    which specific hypothesis a search result informed).

    Callers MUST run this BEFORE apply_fdr_correction, exactly like
    apply_self_derivative_tags -- a record not yet checked is (correctly,
    conservatively) treated as NOT disqualified, never fabricated as
    disqualified."""
    updated = []
    for r in scored_records:
        raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
        hypothesis_name = raw.get("hypothesis_name")
        disqualified = bool(session_flags)
        reason = [dict(flag, hypothesis_name=hypothesis_name) for flag in session_flags] if disqualified else None
        updated.append({**r, "freshness_disqualified": disqualified, "freshness_disqualification_reason": reason})
    return updated


def apply_fdr_correction(scored_records: list[dict], alpha: float = DEFAULT_FDR_ALPHA, field: str = "p_value_oos") -> list[dict]:
    """Spec 3.3: 'Report both everywhere. Never report verdict_is alone.'
    -- but the FDR-corrected HEADLINE number (spec 3.4) is the
    out-of-sample one by default (field='p_value_oos'); callers that also
    want an FDR pass over p_value_is can call this again with
    field='p_value_is'. Records with no usable p-value in `field` get
    fdr_survives_{is,oos}=None, never a fabricated True/False.

    SELF_DERIVATIVE EXCLUSION (added after the CC-1 review's own item 1):
    a hypothesis Eve has already proposed in an earlier session is not an
    INDEPENDENT test of the 5% OOS bar, even though it is still scored and
    its real verdict is still recorded in full (this project's rule is
    "measure, never gate" -- see module docstring). It is therefore
    excluded from the FDR family here regardless of whether it has a real
    p-value: `fdr_survives_{is,oos}` stays None for it, and
    `excluded_from_fdr_family_reason` is set explicitly to
    "self_derivative" so that None is never ambiguous with "no p-value for
    an unrelated reason" (e.g. INSUFFICIENT_SAMPLE). Callers MUST run
    apply_self_derivative_tags (and apply_derivative_tags, though that one
    does not affect FDR membership) BEFORE this function, or every record
    is (correctly, conservatively) treated as NOT self-derivative.

    FRESHNESS-DISQUALIFICATION EXCLUSION -- ADDED 2026-08-05, REVERTED
    2026-08-05 (CC-1 correction directive): item 7's binding freshness gate
    briefly excluded a freshness-disqualified record from the FDR family
    here, for the same stated reason the self-derivative exclusion above
    exists. It was reverted because check_freshness_disqualification is
    necessarily SESSION-WIDE (see that function's own PER-HYPOTHESIS
    ATTRIBUTION LIMITATION docstring) -- one qualifying search result
    disqualifies every hypothesis in the session, which in the one real
    session tested (Eve Session 1) emptied `indices_with_p` entirely,
    making the pre-registered "5% OOS survival, FDR-corrected per session"
    criterion unsatisfiable by construction rather than by result. See
    docs/site_data/eve_session_registry.json's own
    freshness_gate_reversal_provenance field for the full record. Freshness
    disqualification is now informational-only again, exactly like
    is_self_derivative was before the CC-1 review's own item 1 made THAT
    one binding here -- is_freshness_disqualified/apply_freshness_
    disqualification/the item 7a audit fields/item 7b's fail-loud warning
    all still compute and record exactly as before; only this exclusion
    was removed."""
    result_field = "fdr_survives_oos" if field == "p_value_oos" else "fdr_survives_is"
    indices_with_p = [
        i for i, r in enumerate(scored_records)
        if r.get(field) is not None and not is_self_derivative(r)
    ]
    p_values = [scored_records[i][field] for i in indices_with_p]
    survives = benjamini_hochberg(p_values, alpha=alpha)

    updated = [dict(r) for r in scored_records]
    for r in updated:
        r.setdefault(result_field, None)
        if is_self_derivative(r) and r.get(field) is not None:
            r["excluded_from_fdr_family_reason"] = "self_derivative"
    for pos, idx in enumerate(indices_with_p):
        updated[idx][result_field] = survives[pos]
    return updated


# --- Contamination tags (spec 3.5) -- informational only, NEVER gating ------

_STOPWORDS = frozenset({
    "this", "that", "these", "those", "with", "from", "into", "than", "then",
    "each", "both", "near", "real", "only", "over", "such", "less", "more",
    "will", "have", "been", "were", "when", "what", "which", "while", "does",
})


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS]


def _term_frequency_cosine_similarity(text_a: str, text_b: str) -> float:
    """Lexical term-frequency cosine similarity -- NOT a full TF-IDF (no
    corpus to derive IDF weights from at N=1 comparisons) and NOT an
    embedding-based similarity (see module docstring / closing report:
    deliberately avoided to keep this a $0, dependency-free check --
    requirements.txt has no embedding client, and adding a paid embedding
    call would be a second, unbudgeted cost surface the spec never
    mentions). A reasonable lexical-overlap proxy, not a semantic one --
    flagged as a starting point for human calibration."""
    a_tokens, b_tokens = _tokenize(text_a), _tokenize(text_b)
    if not a_tokens or not b_tokens:
        return 0.0
    a_counts, b_counts = Counter(a_tokens), Counter(b_tokens)
    shared = set(a_counts) & set(b_counts)
    dot = sum(a_counts[t] * b_counts[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a_counts.values()))
    norm_b = math.sqrt(sum(v * v for v in b_counts.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def tag_derivative(
    raw_hypothesis: dict,
    adam_history: list[dict],
    threshold: float = DERIVATIVE_SIMILARITY_THRESHOLD,
    tag_name: str = DERIVATIVE_TAG_NAME,
) -> list[dict]:
    """Informational only, never gating (spec 3.5): flags similarity to any
    prior hypothesis TEXT in `adam_history` (originally always Adam's own
    history -- verdicts were never supplied to Eve in the first place, see
    nero_core.eve.context -- so this measures CONVERGENCE, not copying-of-
    a-known-winner). `tag_name` defaults to DERIVATIVE_TAG_NAME (the
    original, still-default behavior, byte-identical for every existing
    caller); apply_self_derivative_tags below reuses this SAME function and
    SAME threshold unmodified, passing Eve's own prior-session history and
    tag_name=SELF_DERIVATIVE_TAG_NAME instead -- deliberately not a
    reimplementation of the similarity method."""
    text = f"{raw_hypothesis.get('hypothesis_name', '')} {raw_hypothesis.get('mechanism', '')}"
    flags = []
    for prior in adam_history:
        prior_text = f"{prior.get('hypothesis_name', '')} {prior.get('mechanism', '')}"
        similarity = _term_frequency_cosine_similarity(text, prior_text)
        if similarity >= threshold:
            flags.append({
                "tag": tag_name,
                "matched_hypothesis_name": prior.get("hypothesis_name"),
                "similarity": round(similarity, 4),
                "method": "term-frequency cosine similarity (lexical, not semantic)",
            })
    return flags


def apply_derivative_tags(scored_records: list[dict], adam_history: list[dict]) -> list[dict]:
    updated = []
    for r in scored_records:
        raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
        tags = list(r.get("contamination_tags") or [])
        tags.extend(tag_derivative(raw, adam_history))
        updated.append({**r, "contamination_tags": tags})
    return updated


def apply_self_derivative_tags(scored_records: list[dict], eve_history: list[dict]) -> list[dict]:
    """CC-1 review, item 1: Eve's own PRIOR-SESSION hypothesis history
    (raw_hypothesis dicts from earlier sessions' records in eve_hypotheses.
    json, filtered by the caller to exclude the CURRENT session's own
    records -- see pipeline.py's load_eve_history_excluding_session) checked
    with the exact same tag_derivative function and DERIVATIVE_SIMILARITY_
    THRESHOLD (0.6) as the Adam-history check -- same discipline as
    WEB_SEARCH_TOOL's own byte-identical reuse, not a reinvented method.

    A hypothesis tagged SELF_DERIVATIVE here is NOT discarded and NOT
    re-scored differently -- "measure, never gate" (module docstring)
    applies exactly as it does to every other contamination tag. What
    changes is downstream, in apply_fdr_correction: a self-derivative
    hypothesis is excluded from the FDR family, because a hypothesis Eve
    has already tried is not an INDEPENDENT test of the survival bar.

    REFINEMENT SPLIT (CC-1 directive, item B1, 2026-08-06): a similarity
    flag whose `matched_hypothesis_name` equals the hypothesis's own
    validated `derived_from.parent_hypothesis_name` (see
    validate_derived_from -- already confirmed real before this ever
    runs, since session.py's pre-submit validator rejects an invented
    parent) is reclassified REFINEMENT_TAG_NAME instead of
    SELF_DERIVATIVE_TAG_NAME -- ONLY that one flag. A record can still
    carry an UNRELATED SELF_DERIVATIVE flag against some OTHER,
    undeclared prior hypothesis at the same time; that flag is untouched
    and still excludes the record from the FDR family via
    is_self_derivative below -- declaring one real parent does not
    launder an unrelated undeclared near-duplicate."""
    updated = []
    for r in scored_records:
        raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
        declared_parent = None
        derived_from = raw.get("derived_from") if isinstance(raw.get("derived_from"), dict) else None
        if derived_from is not None:
            declared_parent = derived_from.get("parent_hypothesis_name")
        derivative_flags = tag_derivative(raw, eve_history, tag_name=SELF_DERIVATIVE_TAG_NAME)
        reclassified_flags = [
            {**flag, "tag": REFINEMENT_TAG_NAME} if declared_parent and flag["matched_hypothesis_name"] == declared_parent else flag
            for flag in derivative_flags
        ]
        tags = list(r.get("contamination_tags") or [])
        tags.extend(reclassified_flags)
        updated.append({**r, "contamination_tags": tags})
    return updated


def apply_declared_refinement_tags(scored_records: list[dict], known_hypothesis_names: set) -> list[dict]:
    """CC-1 directive, "Fix the REFINEMENT tagging mechanism gap"
    (2026-08-07): closes a real, confirmed gap in apply_self_derivative_tags
    above. That function only ever reclassifies a SELF_DERIVATIVE flag into
    REFINEMENT when tag_derivative's own similarity check (against
    `eve_history`, PRIOR SESSIONS ONLY) happens to independently fire against
    the declared parent -- so a hypothesis whose real, valid derived_from
    names a parent that either (a) is in the SAME session (structurally
    absent from `eve_history` by that function's own design, see its
    docstring) or (b) simply never crosses DERIVATIVE_SIMILARITY_THRESHOLD,
    gets ZERO contamination tags at all, indistinguishable from a hypothesis
    that never declared a refinement in the first place.

    Confirmed real, not hypothetical: CHANNEL_BREAKOUT_HIGH20_BTC_4H
    (eve_hypotheses.json, session eve-20260806T180819Z-e777cdef) validly
    declares VOL_CONFIRMED_CHANNEL_BREAKOUT_BTC_4H as its parent -- but that
    parent is in the SAME session, so it was never in `eve_history` for
    tag_derivative to compare against at all (their real lexical similarity
    is actually 0.6638, ABOVE threshold -- the prior write-up describing this
    gap as "never crossed the 0.6 threshold" was imprecise; the true cause is
    same-session exclusion, confirmed by direct computation before this fix).

    THE FIX: REFINEMENT should be a structural fact -- "a valid, real
    derived_from parent is declared" -- independent of whether the
    similarity mechanism happens to also fire. This function re-validates
    each record's own derived_from via validate_derived_from (the SAME
    validation session.py's pre-submit gate already ran, re-run here against
    the SAME kind of known-names universe so an "inert" derived_from --
    structurally incomplete, or naming a parent that never really existed,
    per session.py's own documented retry-exhaustion behavior -- is correctly
    never tagged) and adds an independent REFINEMENT tag whenever it's
    valid, UNLESS apply_self_derivative_tags's own reclassification already
    added one for the same declared parent (checked, never duplicated).

    Purely ADDITIVE: never removes or alters any existing tag. A record can
    still carry an unrelated SELF_DERIVATIVE flag against some OTHER,
    undeclared prior hypothesis at the same time -- exactly the existing
    "declaring one real parent does not launder an unrelated undeclared
    near-duplicate" principle (apply_self_derivative_tags's own docstring),
    completely unchanged by this function. Call this AFTER
    apply_self_derivative_tags and BEFORE apply_fdr_correction, mirroring
    that function's own required ordering."""
    updated = []
    for r in scored_records:
        raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
        derived_from = raw.get("derived_from") if isinstance(raw.get("derived_from"), dict) else None
        tags = list(r.get("contamination_tags") or [])
        if derived_from is not None:
            valid, _ = validate_derived_from(raw, known_hypothesis_names)
            parent_name = derived_from.get("parent_hypothesis_name")
            already_credited = any(
                t.get("tag") == REFINEMENT_TAG_NAME and t.get("matched_hypothesis_name") == parent_name
                for t in tags
            )
            if valid and not already_credited:
                tags.append({
                    "tag": REFINEMENT_TAG_NAME,
                    "matched_hypothesis_name": parent_name,
                    "method": "declared_derived_from (validated structurally, independent of the similarity threshold)",
                })
        updated.append({**r, "contamination_tags": tags})
    return updated


def is_refinement(record: dict) -> bool:
    """True iff `record` carries a REFINEMENT contamination tag -- mirrors
    is_self_derivative's own shape exactly. Public for the same reason:
    nero_core.eve.pipeline uses it to count refinements per session for
    ablation_metadata, and apply_fdr_correction's own docstring/tests
    reference it directly to confirm a REFINEMENT-tagged record is NOT
    excluded from the FDR family the way a SELF_DERIVATIVE one is."""
    return any(t.get("tag") == REFINEMENT_TAG_NAME for t in (record.get("contamination_tags") or []))


# CC-1 directive, item A4: real web_search_tool_result page_age values
# gathered from two live Eve sessions were NOT covered by the original
# ISO-only format list -- "December 10, 2025" / "March 9, 2025" (a
# spelled-out-month absolute date) and "1 month ago" / "3 days ago" /
# "3 weeks ago" (a relative-to-search-time date) both failed to parse and
# were silently treated as "no publication date" (i.e. never flagged for
# lookahead risk, no matter how recent the actual source was).
_RELATIVE_DATE_PATTERN = re.compile(r"^(\d+)\s+(hour|day|week|month|year)s?\s+ago$", re.IGNORECASE)
_RELATIVE_DATE_UNIT_TO_TIMEDELTA = {
    "hour": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
    "week": lambda n: timedelta(weeks=n),
    # No calendar-aware month/year unit exists on timedelta -- these are
    # documented approximations (30-day month, 365-day year), which is fine
    # here: this feeds a FLAG-never-DISCARD check (tag_lookahead_risk), so
    # erring a few days off the true calendar date does not change any
    # gating outcome, only the flagged reason text.
    "month": lambda n: timedelta(days=30 * n),
    "year": lambda n: timedelta(days=365 * n),
}


def _parse_loose_date(raw: object, reference: datetime | None = None) -> datetime | None:
    """`reference` is the point in time relative-format dates ("3 days ago")
    are measured from -- the caller passes the session's own started_at, NOT
    wall-clock now, since a relative date on a page fetched during the
    session is relative to WHEN IT WAS FETCHED, not to whenever this scoring
    function happens to run afterward. Defaults to wall-clock now only when
    the caller has no better reference available."""
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    match = _RELATIVE_DATE_PATTERN.match(raw)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        ref = reference if reference is not None else datetime.now(timezone.utc)
        return ref - _RELATIVE_DATE_UNIT_TO_TIMEDELTA[unit](amount)
    return None


def _session_relative_reference(session_record: dict) -> datetime | None:
    """The point in time relative-format page_age values ("3 days ago") are
    measured from -- the session's own started_at, NOT wall-clock now (which
    could be arbitrarily later, e.g. this scoring re-run against an old
    session file). None if started_at is missing/unparseable."""
    started_at = session_record.get("started_at")
    if isinstance(started_at, str):
        try:
            return datetime.fromisoformat(started_at)
        except ValueError:
            return None
    return None


def _iter_web_search_results(session_record: dict, reference: datetime | None) -> list[dict]:
    """Every web_search_tool_result entry across the whole session's turns,
    as {turn_index, url, page_age, pub_date (parsed, may be None)} -- the
    shared traversal both tag_lookahead_risk and
    check_freshness_disqualification below scan, so the two checks can never
    silently drift apart on WHAT counts as a search result even though they
    apply different threshold logic to the parsed dates."""
    results = []
    for turn in session_record.get("turns", []):
        raw_response = turn.get("raw_response") or {}
        for block in raw_response.get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
                continue
            for result in block.get("content", []) or []:
                if not isinstance(result, dict):
                    continue
                page_age = result.get("page_age")
                results.append({
                    "turn_index": turn.get("turn_index"),
                    "url": result.get("url"),
                    "page_age": page_age,
                    "pub_date": _parse_loose_date(page_age, reference),
                })
    return results


def tag_lookahead_risk(session_record: dict, backtest_window_start: datetime) -> list[dict]:
    """SESSION-LEVEL (flagged design decision, see closing report): scans
    every web_search_tool_result block across the whole session's turns for
    a publication date that does not pre-date `backtest_window_start`.
    Scoped to the session rather than to an individual hypothesis because
    this branch's session log does not itself link a specific search result
    to a specific later propose_hypothesis call -- a per-hypothesis
    attribution would require inferring that link, which this module
    declines to guess at. FLAG, NEVER DISCARD (spec 3.5's own words) -- this
    returns tags for a human to review, never removes or downgrades
    anything. INFORMATIONAL ONLY -- see check_freshness_disqualification
    below (CC-1 directive item 7) for the BINDING sibling check added
    2026-08-05, which uses a different, fixed-recency threshold rather than
    this function's backtest_window_start."""
    reference = _session_relative_reference(session_record)
    flags = []
    for result in _iter_web_search_results(session_record, reference):
        pub_date = result["pub_date"]
        if pub_date is not None and pub_date >= backtest_window_start:
            flags.append({
                "tag": "LOOKAHEAD_RISK",
                "turn_index": result["turn_index"],
                "url": result["url"],
                "publication_date": result["page_age"],
                "reason": (
                    f"source dated {result['page_age']!r} does not pre-date the backtest window start "
                    f"({backtest_window_start.date().isoformat()}) -- Eve searching after the "
                    f"window may have found a writeup describing what already happened in it"
                ),
            })
    return flags


# CC-1 directive, item 7 -- SEARCH FRESHNESS, Variant C, BINDING (unlike
# tag_lookahead_risk above, which stays informational-only/unchanged). A
# starting point derived from ONE real session's data (Session 1,
# eve-20260804T020749Z-4cf6e4c9: 2 of 4 real web-search sources flagged
# under this exact rule -- see item 7d's re-score in
# docs/investigations/factory_loop_implementation_report.md), expected to be
# recalibrated as more sessions accumulate real search-date data, NOT a
# principled fixed constant.
FRESHNESS_DISQUALIFICATION_WINDOW_DAYS = 30
FRESHNESS_DISQUALIFICATION_RULE = "variant_c_30day"


def check_freshness_disqualification(session_record: dict, session_started_at: datetime) -> list[dict]:
    """BINDING (CC-1 directive item 7): a source read during this session and
    published within FRESHNESS_DISQUALIFICATION_WINDOW_DAYS of the session's
    own start disqualifies from Trial admission (item 4e, nero_core.
    research_agent.trial.admit_to_trial) and the FDR family (item 7c) --
    NEVER deleted or hidden; the hypothesis stays fully recorded with its
    real verdict (item 7c's own words). Variant C per spec B6's own
    real-data comparison of three candidate rules (A: window-start, B:
    OOS-half-start, C: fixed recency) -- C was the only one that
    discriminated within Session 1's real 4-source sample rather than
    flagging everything or nothing.

    PER-HYPOTHESIS ATTRIBUTION LIMITATION (documented, not silently
    narrowed): exactly like tag_lookahead_risk above, this session's own log
    does not link a specific search result to the specific propose_hypothesis
    call it may have informed. Every flag returned here is therefore applied
    by the caller (nero_core.eve.pipeline.run_pipeline) to EVERY hypothesis
    this session proposed, not just the one downstream of that particular
    search -- the data does not support finer attribution, and this
    project's discipline is to state a check's real scope rather than
    silently narrow it beyond what the data supports (see item 7b's
    fail-loud rule for the 100%-of-session consequence of this choice).

    Each returned dict carries hypothesis_name=None (filled in by the
    caller, once per disqualified hypothesis) plus the audit fields item 7a
    requires: offending_source_url, parsed_pub_date, rule_fired."""
    cutoff = session_started_at - timedelta(days=FRESHNESS_DISQUALIFICATION_WINDOW_DAYS)
    reference = _session_relative_reference(session_record) or session_started_at
    flags = []
    for result in _iter_web_search_results(session_record, reference):
        pub_date = result["pub_date"]
        if pub_date is not None and pub_date >= cutoff:
            flags.append({
                "tag": "FRESHNESS_DISQUALIFIED",
                "hypothesis_name": None,
                "turn_index": result["turn_index"],
                "offending_source_url": result["url"],
                "parsed_pub_date": pub_date.isoformat(),
                "rule_fired": FRESHNESS_DISQUALIFICATION_RULE,
                "reason": (
                    f"source dated {result['page_age']!r} (parsed {pub_date.date().isoformat()}) is within "
                    f"{FRESHNESS_DISQUALIFICATION_WINDOW_DAYS} days of this session's own start "
                    f"({session_started_at.date().isoformat()}) -- Variant C binding disqualification"
                ),
            })
    return flags


# CC-1 directive (2026-08-05), items 1+2 -- PER-HYPOTHESIS CITATION-BASED
# FRESHNESS ATTRIBUTION. check_freshness_disqualification above stays exactly
# as it was (session-wide, informational, item 7a's audit fields unchanged) --
# this is a SIBLING, not a replacement, because check_freshness_
# disqualification's own session log has no structural way to link a search
# result to the specific propose_hypothesis call it may have informed (see
# its own PER-HYPOTHESIS ATTRIBUTION LIMITATION docstring). The correction
# directive's own finding: a causally-safe per-hypothesis rule ("a hypothesis
# may only be affected by searches preceding it") still yields 100%, because
# Eve front-loads all searching before proposing anything -- every hypothesis
# in a search-then-propose session follows every search. Rather than
# constrain Eve's research process to make ordering meaningful, this instead
# has Eve explicitly DECLARE which of this session's own real search results
# support each hypothesis (raw_hypothesis's optional `supporting_source_urls`,
# see nero_core.eve.tools_defs.PROPOSE_HYPOTHESIS_TOOL and hypothesis_shapes.
# build_hypothesis_record's own `supporting_source_urls` field) -- freshness
# risk is then attributed ONLY to those cited sources, never to every search
# the session happened to run.
#
# STRICTLY INFORMATIONAL, LIKE check_freshness_disqualification -- NEVER
# CONSULTED by admit_to_trial (nero_core.research_agent.trial) or
# apply_fdr_correction below. There is no code path from this section into
# either. See the module docstring above and this branch's own closing
# report for the documented incentive-problem analysis (the proposer and the
# cited evidence are the same party) that is the reason this must stay
# informational until a separate, deliberate decision reopens it.
CITATION_STATUS_NO_SEARCHES = "no_searches_in_session"
CITATION_STATUS_NO_SOURCES_CLAIMED = "no_sources_claimed"
CITATION_STATUS_CITED = "cited"
# ONLY EVER SET BY THE ONE-TIME BACKFILL MIGRATION (tools/backfill_eve_
# pre_citation_status.py), directly on already-persisted eve_hypotheses.json
# records that predate this whole mechanism -- classify_citation_status
# below NEVER returns this value itself. Item 5's own requirement: a record
# with no supporting_source_urls must not silently read as "checked, found
# nothing to cite" (CITATION_STATUS_NO_SOURCES_CLAIMED) -- that would be a
# false pass, indistinguishable from a hypothesis that genuinely had this
# question put to it and answered honestly with nothing.
CITATION_STATUS_UNSCOREABLE_PRE_CITATION = "unscoreable_pre_citation"

PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK = "nothing_to_check"
PER_HYPOTHESIS_FRESHNESS_CHECKED_CLEAN = "checked_clean"
PER_HYPOTHESIS_FRESHNESS_CHECKED_DISQUALIFIED = "checked_disqualified"
PER_HYPOTHESIS_FRESHNESS_UNSCOREABLE_PRE_CITATION = "unscoreable_pre_citation"


def _session_search_url_index(session_record: dict, reference: datetime | None) -> dict[str, dict]:
    """First-seen {url: {turn_index, url, page_age, pub_date}} across the
    whole session -- the set of URLs a citation is validated against (item
    1: 'every cited URL must appear in this session's own web_search_tool_
    result blocks'). Reuses _iter_web_search_results, the SAME traversal
    check_freshness_disqualification/tag_lookahead_risk already use, so this
    can never silently disagree with them on what counts as a real search
    result."""
    index: dict[str, dict] = {}
    for result in _iter_web_search_results(session_record, reference):
        url = result.get("url")
        if url and url not in index:
            index[url] = result
    return index


def validate_supporting_source_urls(
    claimed_urls: list[str], session_record: dict, session_started_at: datetime,
) -> tuple[list[str], list[str]]:
    """Splits `claimed_urls` (a hypothesis record's own top-level
    supporting_source_urls) into (valid, invalid) against this session's real
    search results. A cited URL absent from the session's own web_search_
    tool_result blocks is a HARD VALIDATION ERROR (item 1's own words), never
    a silent pass -- returned in the second list so the caller can surface it
    loudly (see nero_core.eve.pipeline's own fail-loud handling), not drop it
    unnoticed."""
    reference = _session_relative_reference(session_record) or session_started_at
    index = _session_search_url_index(session_record, reference)
    claimed = [u for u in (claimed_urls or []) if isinstance(u, str)]
    valid = [u for u in claimed if u in index]
    invalid = [u for u in claimed if u not in index]
    return valid, invalid


def classify_citation_status(record: dict, session_record: dict, session_started_at: datetime) -> dict:
    """Item 1's three genuinely different situations, kept distinguishable:
    CITATION_STATUS_NO_SEARCHES (the session performed no web searches at
    all -- nothing was ever available to cite), CITATION_STATUS_NO_SOURCES_
    CLAIMED (searches happened, but this hypothesis's own validated
    supporting_source_urls is empty), or CITATION_STATUS_CITED (one or more
    validated URLs). Never returns CITATION_STATUS_UNSCOREABLE_PRE_CITATION
    -- that status exists only for the one-time backfill migration to stamp
    directly onto already-persisted pre-mechanism records; a record scored
    through this function by definition has the mechanism available to it."""
    claimed = record.get("supporting_source_urls")
    reference = _session_relative_reference(session_record) or session_started_at
    index = _session_search_url_index(session_record, reference)
    valid_urls, invalid_urls = validate_supporting_source_urls(claimed, session_record, session_started_at)
    if not index:
        status = CITATION_STATUS_NO_SEARCHES
    elif not valid_urls:
        status = CITATION_STATUS_NO_SOURCES_CLAIMED
    else:
        status = CITATION_STATUS_CITED
    return {
        "citation_status": status,
        "supporting_source_urls_validated": valid_urls,
        "supporting_source_urls_invalid": invalid_urls,
    }


def check_per_hypothesis_freshness(record: dict, session_record: dict, session_started_at: datetime) -> dict:
    """CC-1 directive item 2: freshness risk attributed ONLY to `record`'s
    own validated supporting_source_urls -- unlike check_freshness_
    disqualification (session-wide), this can genuinely clear a hypothesis
    that cited nothing risky even in a session where some OTHER search
    result would trip the session-wide check. Reuses the exact same Variant C
    rule (FRESHNESS_DISQUALIFICATION_WINDOW_DAYS/_RULE) against each cited
    URL's own parsed publication date -- not a second, independently-tuned
    threshold.

    Where the hypothesis cites nothing (CITATION_STATUS_NO_SEARCHES or
    CITATION_STATUS_NO_SOURCES_CLAIMED), the honest result is "nothing to
    check" -- never reported as "clean" (which would imply a real check ran
    and found no risk) and never silently absent.

    STRICTLY INFORMATIONAL (see this section's own module-level comment
    above) -- this result is never consulted by admit_to_trial or
    apply_fdr_correction, exactly like check_freshness_disqualification's
    own result."""
    raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
    hypothesis_name = raw.get("hypothesis_name")
    citation = classify_citation_status(record, session_record, session_started_at)
    status = citation["citation_status"]

    if status in (CITATION_STATUS_NO_SEARCHES, CITATION_STATUS_NO_SOURCES_CLAIMED):
        freshness = {"result": PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK, "hypothesis_name": hypothesis_name}
    else:
        reference = _session_relative_reference(session_record) or session_started_at
        index = _session_search_url_index(session_record, reference)
        cutoff = session_started_at - timedelta(days=FRESHNESS_DISQUALIFICATION_WINDOW_DAYS)
        offending = None
        for url in citation["supporting_source_urls_validated"]:
            entry = index.get(url)
            pub_date = entry["pub_date"] if entry else None
            if pub_date is not None and pub_date >= cutoff:
                offending = {
                    "offending_source_url": url,
                    "parsed_pub_date": pub_date.isoformat(),
                    "rule_fired": FRESHNESS_DISQUALIFICATION_RULE,
                }
                break
        if offending is not None:
            freshness = {"result": PER_HYPOTHESIS_FRESHNESS_CHECKED_DISQUALIFIED, "hypothesis_name": hypothesis_name, **offending}
        else:
            freshness = {"result": PER_HYPOTHESIS_FRESHNESS_CHECKED_CLEAN, "hypothesis_name": hypothesis_name}

    return {**citation, "per_hypothesis_freshness": freshness}


def apply_per_hypothesis_freshness(
    scored_records: list[dict], session_record: dict, session_started_at: datetime | None,
) -> list[dict]:
    """Applies check_per_hypothesis_freshness to every record in
    `scored_records` (all from the SAME session -- this is nero_core.eve.
    pipeline's own per-session scoring pass, never a cross-session batch).
    `session_started_at` is None (never a fabricated fallback) when the
    session record's own started_at is missing/unparseable -- every record
    gets an explicit "cannot evaluate" freshness result instead, the same
    conservative-but-honest handling nero_core.eve.pipeline already applies
    to check_freshness_disqualification for the same missing-clock case.
    ALWAYS sets every field (never left absent), matching apply_freshness_
    disqualification's own discipline."""
    updated = []
    for r in scored_records:
        if session_started_at is None:
            raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
            attribution = {
                "citation_status": None,
                "supporting_source_urls_validated": [],
                "supporting_source_urls_invalid": [],
                "per_hypothesis_freshness": {
                    "result": None,
                    "hypothesis_name": raw.get("hypothesis_name"),
                    "reason": "session_started_at missing/unparseable -- cannot evaluate",
                },
            }
        else:
            attribution = check_per_hypothesis_freshness(r, session_record, session_started_at)
        updated.append({**r, **attribution})
    return updated
