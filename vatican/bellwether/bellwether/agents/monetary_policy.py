"""Module 4 — Monetary Policy Engine.

Gold's single most important driver is the real interest rate: higher real
yields raise the opportunity cost of holding non-yielding gold (bearish), lower
real yields are bullish. A strong dollar is an additional headwind. Bitcoin is
treated as a long-duration risk asset: easier policy / weaker dollar is
supportive.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, DataProvenance, Signal
from .base import AnalysisContext, BaseAgent

# Anchor levels around which we judge "high" vs "low".
_REAL_YIELD_NEUTRAL = 1.8   # %
_DXY_NEUTRAL = 104.0


class MonetaryPolicyAgent(BaseAgent):
    name = "monetary_policy"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        m = ctx.market
        real_gap = m.real_yield_10y - _REAL_YIELD_NEUTRAL   # +ve = restrictive
        dxy_gap = (m.dxy - _DXY_NEUTRAL) / _DXY_NEUTRAL      # fractional

        # Gold: rising real yields & strong dollar are bearish -> invert.
        gold_score = -(real_gap * 1.2) - (dxy_gap * 4.0)
        # Bitcoin: less real-rate sensitive, but a strong dollar still weighs.
        btc_score = -(real_gap * 0.5) - (dxy_gap * 3.0)

        signals = [
            Signal(asset=Asset.GOLD, bias=Bias.from_score(gold_score),
                   strength=min(1.0, abs(gold_score) / 2 + 0.2),
                   category=Category.MONETARY_POLICY, is_fact=True, source_agent=self.name,
                   rationale=(f"10y real yield {m.real_yield_10y:.2f}% vs ~{_REAL_YIELD_NEUTRAL:.1f}% "
                              f"neutral; DXY {m.dxy:.1f}")),
            Signal(asset=Asset.BITCOIN, bias=Bias.from_score(btc_score),
                   strength=min(1.0, abs(btc_score) / 2 + 0.15),
                   category=Category.MONETARY_POLICY, is_fact=True, source_agent=self.name,
                   rationale=f"USD liquidity proxy; DXY {m.dxy:.1f}"),
        ]
        facts = [
            f"10y real yield: {m.real_yield_10y:.2f}% (neutral ~{_REAL_YIELD_NEUTRAL:.1f}%)",
            f"DXY: {m.dxy:.1f} (neutral ~{_DXY_NEUTRAL:.0f})",
            f"Fed funds mid: {m.fed_funds_mid:.2f}%",
        ]
        # VATICAN INTEGRATION: this agent's own honest provenance, derived
        # from exactly the two fields it actually reads (real_yield_10y,
        # dxy) — never assumed from the settings' data_mode, so a future
        # provider that makes ONLY one of the two real (as today: real_yield
        # real, dxy still synthetic — see VaticanRealMarketData's own
        # docstring on why) is reported as MIXED, not silently rounded up
        # to REAL.
        real_yield_prov = m.provenance_of("real_yield_10y")
        dxy_prov = m.provenance_of("dxy")
        if real_yield_prov == DataProvenance.REAL and dxy_prov == DataProvenance.REAL:
            provenance = DataProvenance.REAL
        elif real_yield_prov == DataProvenance.REAL or dxy_prov == DataProvenance.REAL:
            provenance = DataProvenance.MIXED
        else:
            provenance = DataProvenance.SYNTHETIC
        return self.result(signals=signals, facts=facts, confidence=0.7, provenance=provenance,
                           meta={"real_gap": round(real_gap, 3), "dxy_gap": round(dxy_gap, 4),
                                 "real_yield_10y_provenance": real_yield_prov.value,
                                 "dxy_provenance": dxy_prov.value})
