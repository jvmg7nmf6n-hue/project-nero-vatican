"""Shared asset-universe declarations for anything that scores or backtests
against a full-history research export. Both `nero_core.eve` and
`nero_core.research_agent` (Adam) import this rather than each declaring
their own copy, so the two systems can never silently drift on which
(asset, timeframe) pairs are safe to score hypotheses against.

TWO DISTINCT UNIVERSES, NEVER CONFLATED (see docs/investigations/
eve_engine_v1_report.md for the full reasoning behind this split):

APPROVED_RESEARCH_UNIVERSE -- the SEARCH universe. Eve (multi-turn,
open-ended hypothesis generation) and Adam (scanner-triggered hypothesis
generation) may PROPOSE and SCORE hypotheses only against a pair in this
set. A pair enters this set only once it has BOTH (i) its own full-history
research export, and (ii) its own random-hypothesis baseline computed
against that SAME export -- a baseline computed on one asset's candles
does not transfer to another (different volatility, liquidity, fee impact,
regime structure). This is a pre-registered universe: extending it is a
human decision made after running a fresh export + baseline for that
specific pair, never inferred from which export files happen to already
exist on disk -- widening the search space after seeing results is the
multiple-comparisons "garden of forking paths" this whole discipline
exists to prevent.

APPROVED_EVALUATION_UNIVERSE -- the EVALUATION universe: pairs a human
already chose and wired live in nero_core.execution.live_scheduler months
ago, accruing real paper trades in truth_ledger.db, now being backtested
against real multi-year history for the first time. These are not
proposals -- their identity does not change based on what a backtest says,
so evaluating a fixed, pre-existing, already-running strategy is not the
same act as searching for a new one, and does not carry the same
multiple-comparisons risk the research universe's pre-registration
discipline exists to control. PRECISELY BECAUSE of that distinction, this
universe must NEVER be available to Eve's or Adam's hypothesis-generation/
scoring paths -- an evaluation-only pair is for a human-directed backtest
script to read directly, never for a candles_provider a scoring pipeline
calls. See test_asset_universe.py's EvaluationUniverseNeverScorableTest.

The two universes are disjoint by construction (asserted below, at import
time -- a broken invariant fails loudly and immediately, not silently) and
are additionally stored under separate directories on disk
(docs/research_data/candles/ vs docs/research_data/evaluation_candles/) as
defense in depth: a scoring-context candles_provider that only ever reads
from the research directory can never accidentally pick up an
evaluation-only export, even if this module's own constants were ever
misconfigured.
"""
from __future__ import annotations

# SEARCH universe -- see module docstring. PRE-REGISTERED (docs/
# investigations/eve_engine_v1_report.md): BTCUSDT, ETHUSDT, SOLUSDT,
# PAXGUSDT -- declared as a package before any of ETH/SOL/PAXG's own results
# existed, and binding in both directions: every declared asset gets its own
# export + baseline regardless of what an earlier one showed, and no asset
# is added later just because earlier ones came up empty (that would be the
# multiple-comparisons "garden of forking paths" this discipline exists to
# prevent). NEAR (shorter Binance history, thinner liquidity) and DOGE
# (meme/news-driven regime -- any backtest edge would be regime-specific by
# nature, not a persistent structural one) were considered and deliberately
# excluded, with reasons, at the same time this universe was declared.
#
# Each pair's own K=200 random-hypothesis baseline (0/200 SURVIVED in every
# case; the PROMISING-WATCHLIST count differs meaningfully per asset --
# BTC/4h: 17, BTC's own random-baseline investigation predates this file;
# ETH/4h: 3; SOL/4h: 0; PAXG/4h: 8 -- see docs/investigations/
# {eth,sol,paxg}_4h_random_baseline_result.json), confirming a baseline
# genuinely does not transfer between assets even when none of them ever
# reach SURVIVED.
APPROVED_RESEARCH_UNIVERSE: frozenset[tuple[str, str]] = frozenset({
    ("BTC", "4h"),
    ("ETH", "4h"),
    ("SOL", "4h"),
    ("PAXG", "4h"),
})

# EVALUATION universe -- see module docstring. BTC/24h backtests the two
# live RANGE_MEAN_REVERSION variants (range-mean-reversion-v1.1.0-long-only,
# range-mean-reversion-v1.3.0-confirmation) against real multi-year daily
# history for the first time. BTC-ETH/12h (COINTEGRATION_PAIRS) was
# investigated but deliberately NOT added here -- see the closing report's
# own section on why a two-asset pairs strategy cannot run through the
# single-asset rule_dsl harness.
APPROVED_EVALUATION_UNIVERSE: frozenset[tuple[str, str]] = frozenset({
    ("BTC", "24h"),
})

_OVERLAP = APPROVED_RESEARCH_UNIVERSE & APPROVED_EVALUATION_UNIVERSE
if _OVERLAP:
    raise AssertionError(
        f"APPROVED_RESEARCH_UNIVERSE and APPROVED_EVALUATION_UNIVERSE must be disjoint -- "
        f"found overlap: {_OVERLAP}. A pair used for hypothesis search must never also be "
        f"an evaluation-only pair, or Eve/Adam could silently score proposals against it."
    )
