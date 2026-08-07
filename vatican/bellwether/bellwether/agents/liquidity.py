"""Module 5 — Liquidity Engine.

Bitcoin in particular tracks global USD liquidity and risk appetite. We proxy
the regime with the dollar, equity-vol (VIX) and bond-vol (MOVE), plus
stablecoin supply growth from the on-chain feed (dry powder entering crypto).
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, Signal
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
        return self.result(signals=signals, facts=facts, confidence=0.65,
                           meta={"vix_z": round(vix_z, 3), "risk_on": round(risk_on, 3)})
