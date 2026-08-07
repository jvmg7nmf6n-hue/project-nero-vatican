"""Shared helpers for the per-asset synthesis agents."""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Asset, Bias, DataProvenance, Signal


@dataclass
class AssetRead:
    asset: Asset
    net_score: float          # weighted, on the -2..+2 bias scale
    bias: Bias
    confidence: float
    # VATICAN INTEGRATION (Stage 2, "fix the aggregation formula" directive,
    # docs/bellwether_aggregation_formula_report.md): `confidence` above is
    # kept unchanged (0.3 + 0.45*agreement + 0.25*coverage) for backward
    # compatibility with every existing consumer (trade_recommendation's
    # actionability threshold, risk's haircut math, every pre-existing
    # test) — nothing downstream breaks. `agreement` and `coverage` are the
    # SAME two components that formula already computes internally, now
    # also exposed as their own fields so a consumer can see them
    # separately rather than only the blend. See that report for why this
    # split matters: confidence alone can't distinguish "narrow but very
    # aligned" from "broad but only mildly aligned," and the two behave very
    # differently as more real agents get wired.
    agreement: float          # 0 (split) .. 1 (unanimous strong) — |net_score|/2
    coverage: float           # 0..1 — how much of the intended signal mass showed up this cycle
    probability_up: float
    bullish: list[Signal]
    bearish: list[Signal]
    top_drivers: list[str]


def real_only_signals(ctx, asset: Asset) -> list[Signal]:
    """VATICAN INTEGRATION (Stage 2): signals from `ctx.all_signals(asset)`
    whose SOURCE agent's own AgentResult.provenance is REAL or MIXED —
    i.e. excludes any agent still purely on the mock draw from the "live"
    aggregate, per the ground rule "any feed you can't source stays on
    mock, and its agent is excluded from the aggregate rather than silently
    included." Deliberately keyed off each source agent's OWN reported
    provenance (not ctx.settings.data_mode) — an agent's provenance is the
    one place this is actually decided; asking data_mode would assume every
    agent in "live" mode is automatically real, which is exactly the
    silent-inclusion this function exists to prevent."""
    out: list[Signal] = []
    for res in ctx.results.values():
        if res.provenance not in (DataProvenance.REAL, DataProvenance.MIXED):
            continue
        for sig in res.signals:
            if sig.asset == asset:
                out.append(sig)
    return out


_PROVENANCE_RANK = {
    DataProvenance.UNAVAILABLE: 0,
    DataProvenance.SYNTHETIC: 1,
    DataProvenance.MIXED: 2,
    DataProvenance.REAL: 3,
}


def weakest_provenance(provenances: list[DataProvenance]) -> DataProvenance:
    """VATICAN INTEGRATION (Stage 2, "close the provenance leak" directive):
    THE one place two-or-more provenances combine into one, so every
    downstream/composite agent (risk, scenario, trade_recommendation, and
    gold_analysis/bitcoin_analysis's own combined_provenance below) agrees
    on the same rule rather than each re-deriving its own. A composite is
    only ever as trustworthy as its WEAKEST contributing input — UNAVAILABLE
    < SYNTHETIC < MIXED < REAL — never rounded up. Empty input means nothing
    contributed at all, which is UNAVAILABLE (not, say, defaulting to
    SYNTHETIC — an agent that consulted zero sources didn't "use mock data,"
    it used none)."""
    if not provenances:
        return DataProvenance.UNAVAILABLE
    return min(provenances, key=lambda p: _PROVENANCE_RANK[p])


def combined_provenance(ctx, signals: list[Signal]) -> DataProvenance:
    """VATICAN INTEGRATION (Stage 2): the honest provenance for a synthesis
    agent (gold_analysis/bitcoin_analysis) built from `signals`. UNAVAILABLE
    if `signals` is empty (e.g. real_only_signals found nothing real for
    this asset this cycle — "insufficient data" is reported honestly, not
    silently defaulted to a mock-derived NEUTRAL read that LOOKS like a real
    absence-of-signal rather than an absence-of-real-data). Otherwise the
    WEAKEST of every distinct contributing source agent's own provenance
    (via weakest_provenance) — REAL only if every source is REAL."""
    if not signals:
        return DataProvenance.UNAVAILABLE
    source_agents = {sig.source_agent for sig in signals}
    provs = [ctx.results[name].provenance for name in source_agents if name in ctx.results]
    return weakest_provenance(provs)


# CC-1 master directive (2026-08-07), Part B Rung 1: correlation discount for
# `agreement`. Real pairwise Pearson correlation (LEVEL values -- matching
# every formula below, which all compute LEVEL gaps/z-scores, e.g.
# monetary_policy.py's `real_gap = m.real_yield_10y - _REAL_YIELD_NEUTRAL`,
# not a period-over-period change) measured over n=1229 real overlapping
# calendar days, 2021-08-09 to 2026-07-15, via
# vatican/bellwether/tools/correlation_matrix.py -- see
# docs/bellwether_stage2_report.md's Rung 1 section for the full matrix,
# methodology, and the 20-trading-day-change variant (more relevant to
# Rung 2's DSL fields, kept separate from this LEVEL-based table). This is a
# fixed table, not re-fetched at runtime -- these are slow-moving structural
# relationships between macro series, not something that needs measuring
# fresh every Orchestrator cycle.
_REAL_FIELD_CORRELATION: dict[frozenset[str], float] = {
    frozenset({"real_yield_10y", "dxy"}): 0.4833,
    frozenset({"real_yield_10y", "vix"}): -0.3444,
    frozenset({"real_yield_10y", "funding_rate_bps"}): -0.1551,
    frozenset({"dxy", "vix"}): 0.0870,
    frozenset({"dxy", "funding_rate_bps"}): -0.0883,
    frozenset({"vix", "funding_rate_bps"}): -0.2791,
}

# Which of the 4 real fields each Signal-EMITTING agent's own formula reads
# (see each agent's own module for the exact weights: monetary_policy.py
# blends real_yield_10y+dxy into one signal per asset; liquidity.py's GOLD
# signal is vix-only; derivatives_etf.py's BTC signal has a funding-rate
# threshold term). risk.py deliberately excluded: confirmed by reading
# risk.py in full, it returns RiskFlags/a confidence haircut, never a
# Signal -- it does not enter aggregate()'s relevant list at all, so it has
# no bearing on `agreement`.
_AGENT_REAL_FIELDS: dict[str, tuple[str, ...]] = {
    "monetary_policy": ("real_yield_10y", "dxy"),
    "liquidity": ("vix",),
    "derivatives_etf": ("funding_rate_bps",),
}


def _agent_pair_correlation(agent_a: str, agent_b: str) -> float:
    """Max absolute real-field correlation between two Signal-emitting
    agents' own underlying real fields -- 0.0 if either agent isn't in
    _AGENT_REAL_FIELDS (no measured relationship to discount by) or if
    neither field pairing has a measured correlation. Two agents that
    happen to read the literal SAME field (not the case for any pair
    today, but handled for completeness) get 1.0 by construction."""
    fields_a, fields_b = _AGENT_REAL_FIELDS.get(agent_a, ()), _AGENT_REAL_FIELDS.get(agent_b, ())
    if not fields_a or not fields_b:
        return 0.0
    best = 0.0
    for field_a in fields_a:
        for field_b in fields_b:
            if field_a == field_b:
                best = max(best, 1.0)
                continue
            rho = _REAL_FIELD_CORRELATION.get(frozenset({field_a, field_b}))
            if rho is not None:
                best = max(best, abs(rho))
    return best


def _discounted_agreement_numerator(relevant: list[Signal]) -> float:
    """CC-1 master directive Rung 1: `agreement` must not treat two agents
    driven by correlated real macro fields as fully independent
    confirmations when they happen to agree. Processes signals strongest
    first; a signal whose bias AGREES with an already-counted signal from a
    DIFFERENT, correlated real-field-driven agent has its contribution
    discounted by (1 - |agent-pair correlation|) -- the fraction of an
    agreeing signal a correlated peer already accounted for. A signal that
    DISAGREES with a usually-correlated peer is left at full weight -- that
    disagreement is genuinely more informative, not redundant. Divides by
    the SAME (undiscounted) total_w coverage already uses, deliberately --
    a fully redundant second signal (rho=1.0) then correctly SHRINKS the
    resulting ratio toward zero rather than leaving it unchanged (which a
    renormalized weighted average would do, since it's insensitive to
    duplicate copies of the same score by construction -- verified against
    this function's own regression test)."""
    ordered = sorted(relevant, key=lambda s: s.strength, reverse=True)
    counted: list[Signal] = []
    discounted_sum = 0.0
    for sig in ordered:
        max_rho = 0.0
        for prior in counted:
            if prior.source_agent == sig.source_agent:
                continue
            if (prior.bias.score > 0) != (sig.bias.score > 0):
                continue  # disagreement -- not redundant, full weight
            max_rho = max(max_rho, _agent_pair_correlation(prior.source_agent, sig.source_agent))
        effective_strength = sig.strength * (1.0 - max_rho)
        discounted_sum += sig.bias.score * effective_strength
        counted.append(sig)
    return discounted_sum


def aggregate(asset: Asset, signals: list[Signal]) -> AssetRead:
    """Confidence-weighted blend of every signal for one asset.

    Returns a net bias, a calibrated-ish probability of an up move, and the
    decomposition into bullish/bearish drivers used for explainability and the
    deliberate counter-case.
    """
    relevant = [s for s in signals if s.asset == asset and s.bias != Bias.NEUTRAL]
    if not relevant:
        return AssetRead(asset, 0.0, Bias.NEUTRAL, 0.25, 0.0, 0.0, 0.5, [], [], [])

    total_w = sum(s.strength for s in relevant) or 1.0
    net = sum(s.weighted_score for s in relevant) / total_w

    bullish = sorted([s for s in relevant if s.bias.score > 0],
                     key=lambda s: s.weighted_score, reverse=True)
    bearish = sorted([s for s in relevant if s.bias.score < 0],
                     key=lambda s: s.weighted_score)

    # Confidence rises with (a) signal coverage and (b) agreement among signals.
    # `agreement` uses the CORRELATION-DISCOUNTED numerator (see
    # _discounted_agreement_numerator's own docstring) over the SAME raw
    # total_w coverage uses -- net_score/bias/probability_up below are
    # deliberately left on the ORIGINAL undiscounted `net`, unchanged: this
    # directive's own scope is `agreement` only, not the directional call.
    net_discounted = _discounted_agreement_numerator(relevant) / total_w
    agreement = abs(net_discounted) / 2.0             # 0 (split) .. 1 (unanimous strong)
    coverage = min(1.0, total_w / 4.0)                # how much intended signal mass showed up
    confidence = round(0.3 + 0.45 * agreement + 0.25 * coverage, 3)

    # Logistic squashing of net score into a probability.
    prob_up = round(1.0 / (1.0 + pow(2.718281828, -1.1 * net)), 3)

    drivers = [f"{'+' if s.bias.score > 0 else ''}{s.bias.value} · {s.source_agent}"
               f" ({s.category.value})" for s in (bullish[:3] + bearish[:3])]

    return AssetRead(
        asset=asset,
        net_score=round(net, 3),
        bias=Bias.from_score(net),
        confidence=confidence,
        agreement=round(agreement, 3),
        coverage=round(coverage, 3),
        probability_up=prob_up,
        bullish=bullish,
        bearish=bearish,
        top_drivers=drivers,
    )
