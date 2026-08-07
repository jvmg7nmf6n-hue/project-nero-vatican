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


def combined_provenance(ctx, signals: list[Signal]) -> DataProvenance:
    """VATICAN INTEGRATION (Stage 2): the honest provenance for a synthesis
    agent (gold_analysis/bitcoin_analysis) built from `signals`. UNAVAILABLE
    if `signals` is empty (e.g. real_only_signals found nothing real for
    this asset this cycle — "insufficient data" is reported honestly, not
    silently defaulted to a mock-derived NEUTRAL read that LOOKS like a real
    absence-of-signal rather than an absence-of-real-data). REAL only if
    EVERY contributing source agent's own result is REAL; MIXED otherwise
    (covers both "some sources MIXED" and "some sources REAL, some
    SYNTHETIC" — the latter should not reach here if the caller already
    filtered via real_only_signals, but this function doesn't assume that)."""
    if not signals:
        return DataProvenance.UNAVAILABLE
    source_agents = {sig.source_agent for sig in signals}
    provs = {ctx.results[name].provenance for name in source_agents if name in ctx.results}
    if provs and provs == {DataProvenance.REAL}:
        return DataProvenance.REAL
    if provs & {DataProvenance.REAL, DataProvenance.MIXED}:
        return DataProvenance.MIXED
    return DataProvenance.SYNTHETIC


def aggregate(asset: Asset, signals: list[Signal]) -> AssetRead:
    """Confidence-weighted blend of every signal for one asset.

    Returns a net bias, a calibrated-ish probability of an up move, and the
    decomposition into bullish/bearish drivers used for explainability and the
    deliberate counter-case.
    """
    relevant = [s for s in signals if s.asset == asset and s.bias != Bias.NEUTRAL]
    if not relevant:
        return AssetRead(asset, 0.0, Bias.NEUTRAL, 0.25, 0.5, [], [], [])

    total_w = sum(s.strength for s in relevant) or 1.0
    net = sum(s.weighted_score for s in relevant) / total_w

    bullish = sorted([s for s in relevant if s.bias.score > 0],
                     key=lambda s: s.weighted_score, reverse=True)
    bearish = sorted([s for s in relevant if s.bias.score < 0],
                     key=lambda s: s.weighted_score)

    # Confidence rises with (a) signal mass and (b) agreement among signals.
    agreement = abs(net) / 2.0                       # 0 (split) .. 1 (unanimous strong)
    mass = min(1.0, total_w / 4.0)
    confidence = round(0.3 + 0.45 * agreement + 0.25 * mass, 3)

    # Logistic squashing of net score into a probability.
    prob_up = round(1.0 / (1.0 + pow(2.718281828, -1.1 * net)), 3)

    drivers = [f"{'+' if s.bias.score > 0 else ''}{s.bias.value} · {s.source_agent}"
               f" ({s.category.value})" for s in (bullish[:3] + bearish[:3])]

    return AssetRead(
        asset=asset,
        net_score=round(net, 3),
        bias=Bias.from_score(net),
        confidence=confidence,
        probability_up=prob_up,
        bullish=bullish,
        bearish=bearish,
        top_drivers=drivers,
    )
