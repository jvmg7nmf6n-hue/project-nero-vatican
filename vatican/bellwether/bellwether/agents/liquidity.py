"""Module 5 — Liquidity Engine.

Bitcoin in particular tracks global USD liquidity and risk appetite. We proxy
the regime with the dollar, equity-vol (VIX) and bond-vol (MOVE), plus
stablecoin supply growth from the on-chain feed (dry powder entering crypto).
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, DataProvenance, Signal
from .base import AnalysisContext, BaseAgent

_VIX_CALM = 15.0
_VIX_STRESS = 25.0


class LiquidityAgent(BaseAgent):
    name = "liquidity"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        m = ctx.market
        oc = ctx.data.onchain.metrics()

        # Risk-appetite component: low VIX = risk-on (good for BTC), high = risk-off.
        vix_z = (m.vix - _VIX_CALM) / (_VIX_STRESS - _VIX_CALM)   # 0 calm .. 1 stress
        risk_on = -vix_z + 0.5                                    # +0.5 calm .. -0.5 stress

        stable_growth = oc.get("stablecoin_supply_chg_pct", 0.0)
        # BTC: risk-on + expanding stablecoins are bullish.
        btc_score = (risk_on * 2.0) + (stable_growth * 0.6)
        # Gold: stress (high VIX) adds safe-haven bid -> bullish when risk-off.
        gold_score = (vix_z * 1.2)

        signals = [
            Signal(asset=Asset.BITCOIN, bias=Bias.from_score(btc_score),
                   strength=min(1.0, abs(btc_score) / 2 + 0.2), category=Category.LIQUIDITY,
                   is_fact=True, source_agent=self.name,
                   rationale=f"VIX {m.vix:.1f}, stablecoin supply {stable_growth:+.2f}%"),
            Signal(asset=Asset.GOLD, bias=Bias.from_score(gold_score),
                   strength=min(1.0, abs(gold_score) / 2 + 0.15), category=Category.RISK_SENTIMENT,
                   is_fact=True, source_agent=self.name,
                   rationale=f"VIX {m.vix:.1f} safe-haven component"),
        ]
        facts = [
            f"VIX: {m.vix:.1f}",
            f"MOVE (bond vol): {m.move_index}",
            f"Stablecoin supply change: {stable_growth:+.2f}%",
        ]
        # VATICAN INTEGRATION: this agent's own honest provenance. The GOLD
        # signal depends only on vix; the BTC signal ALSO depends on
        # oc["stablecoin_supply_chg_pct"] -- now ALSO real (CC-1 directive,
        # 2026-08-07, "wire the 2 safest agents real": VaticanRealOnChain's
        # own DefiLlama fetch). AgentResult.provenance is a single value for
        # the whole agent (not per-signal), so this combines BOTH real inputs
        # the SAME way monetary_policy.py already combines its own two real
        # inputs (real_yield_10y, dxy): both real -> REAL, either real ->
        # MIXED, neither -> SYNTHETIC. Before this directive, stablecoin
        # provenance was always SYNTHETIC (MockOnChain never overrode
        # provenance_of), so this agent could only ever reach MIXED at best --
        # now it can genuinely reach REAL.
        vix_provenance = m.provenance_of("vix")
        stablecoin_provenance = ctx.data.onchain.provenance_of("stablecoin_supply_chg_pct")
        if vix_provenance == DataProvenance.REAL and stablecoin_provenance == DataProvenance.REAL:
            provenance = DataProvenance.REAL
        elif vix_provenance == DataProvenance.REAL or stablecoin_provenance == DataProvenance.REAL:
            provenance = DataProvenance.MIXED
        else:
            provenance = DataProvenance.SYNTHETIC
        return self.result(signals=signals, facts=facts, confidence=0.65, provenance=provenance,
                           meta={"vix_z": round(vix_z, 3), "risk_on": round(risk_on, 3),
                                 "vix_provenance": vix_provenance.value,
                                 "stablecoin_supply_provenance": stablecoin_provenance.value})
