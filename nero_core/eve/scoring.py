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
from datetime import datetime, timezone
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
    is (correctly, conservatively) treated as NOT self-derivative."""
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
    has already tried is not an INDEPENDENT test of the survival bar."""
    updated = []
    for r in scored_records:
        raw = r.get("raw_hypothesis") if isinstance(r.get("raw_hypothesis"), dict) else {}
        tags = list(r.get("contamination_tags") or [])
        tags.extend(tag_derivative(raw, eve_history, tag_name=SELF_DERIVATIVE_TAG_NAME))
        updated.append({**r, "contamination_tags": tags})
    return updated


def _parse_loose_date(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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
    anything."""
    flags = []
    for turn in session_record.get("turns", []):
        raw_response = turn.get("raw_response") or {}
        for block in raw_response.get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
                continue
            for result in block.get("content", []) or []:
                if not isinstance(result, dict):
                    continue
                page_age = result.get("page_age")
                pub_date = _parse_loose_date(page_age)
                if pub_date is not None and pub_date >= backtest_window_start:
                    flags.append({
                        "tag": "LOOKAHEAD_RISK",
                        "turn_index": turn.get("turn_index"),
                        "url": result.get("url"),
                        "publication_date": page_age,
                        "reason": (
                            f"source dated {page_age!r} does not pre-date the backtest window start "
                            f"({backtest_window_start.date().isoformat()}) -- Eve searching after the "
                            f"window may have found a writeup describing what already happened in it"
                        ),
                    })
    return flags
