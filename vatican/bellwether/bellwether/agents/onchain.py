"""Module 8 — On-chain Analytics (Bitcoin).

Reads exchange netflows, long-term-holder supply, MVRV-Z and funding to gauge
accumulation vs distribution and froth.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, Signal
from .base import AnalysisContext, BaseAgent


class OnChainAgent(BaseAgent):
    name = "onchain"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        oc = ctx.data.onchain.metrics()
        netflow = oc.get("exchange_netflow_btc", 0.0)      # negative = coins leaving exchanges (bullish)
        lth = oc.get("lth_supply_chg_pct", 0.0)            # rising = accumulation (bullish)
        mvrv_z = oc.get("mvrv_z", 1.0)                     # high (>3) = overheated

        score = 0.0
        score += -netflow / 8000.0          # leaving exchanges -> bullish
        score += lth * 1.0                  # accumulation -> bullish
        if mvrv_z > 3.0:                    # froth -> fade
            score -= (mvrv_z - 3.0) * 0.8
        elif mvrv_z < 0:                    # capitulation -> contrarian bullish
            score += abs(mvrv_z) * 0.5

        sig = Signal(asset=Asset.BITCOIN, bias=Bias.from_score(score),
                     strength=min(1.0, abs(score) / 2 + 0.2), category=Category.ON_CHAIN,
                     is_fact=True, source_agent=self.name,
                     rationale=(f"netflow {netflow:+.0f} BTC, LTH supply {lth:+.2f}%, "
                                f"MVRV-Z {mvrv_z:.2f}"))
        facts = [
            f"Exchange netflow: {netflow:+.0f} BTC ({'outflow/bullish' if netflow < 0 else 'inflow/bearish'})",
            f"Long-term holder supply change: {lth:+.2f}%",
            f"MVRV-Z score: {mvrv_z:.2f}",
        ]
        return self.result(signals=[sig], facts=facts, confidence=0.6)
