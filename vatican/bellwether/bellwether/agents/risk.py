"""Module 13 — Risk Engine.

Independent skeptic. Flags reasons to distrust the call: internal signal
disagreement, crowded positioning/leverage, imminent high-impact catalysts, and
elevated volatility. Produces a list of risks and a confidence *haircut* the
trade engine must apply.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, RiskFlag
from .base import AnalysisContext, BaseAgent


class RiskAgent(BaseAgent):
    name = "risk"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        flags: list[RiskFlag] = []
        haircut = 0.0

        # 1) Signal disagreement per asset.
        for asset in (Asset.GOLD, Asset.BITCOIN):
            sigs = [s for s in ctx.all_signals(asset) if s.bias != Bias.NEUTRAL]
            if len(sigs) >= 3:
                bulls = sum(1 for s in sigs if s.bias.score > 0)
                bears = sum(1 for s in sigs if s.bias.score < 0)
                if bulls and bears and min(bulls, bears) / (bulls + bears) > 0.35:
                    sev = min(1.0, min(bulls, bears) / (bulls + bears) + 0.2)
                    flags.append(RiskFlag(label=f"{asset.value} signal conflict",
                                          severity=sev,
                                          detail=f"{bulls} bullish vs {bears} bearish drivers"))
                    haircut += 0.1

        # 2) Crowded leverage / froth from derivatives + on-chain.
        d = ctx.data.derivatives.metrics()
        if d.get("btc_perp_funding_bps", 0) > 6:
            flags.append(RiskFlag(label="BTC leverage crowded", severity=0.6,
                                  detail=f"perp funding {d['btc_perp_funding_bps']:+.1f} bps"))
            haircut += 0.08
        mvrv = ctx.data.onchain.metrics().get("mvrv_z", 1.0)
        if mvrv > 3.0:
            flags.append(RiskFlag(label="BTC valuation hot", severity=0.5,
                                  detail=f"MVRV-Z {mvrv:.2f} (>3 historically frothy)"))
            haircut += 0.05

        # 3) Imminent catalysts within ~3 days.
        cal = ctx.result("economic_calendar")
        catalysts = (cal.meta.get("catalysts", []) if cal else [])
        soon = [c for c in catalysts if "FOMC" in c["name"] or "CPI" in c["name"] or "NFP" in c["name"]]
        if soon:
            flags.append(RiskFlag(label="High-impact catalyst ahead", severity=0.55,
                                  detail=", ".join(c["name"] for c in soon[:3])))
            haircut += 0.1

        # 4) Vol regime.
        if ctx.market.vix > 25:
            flags.append(RiskFlag(label="Elevated volatility regime", severity=0.5,
                                  detail=f"VIX {ctx.market.vix:.1f}"))
            haircut += 0.05

        haircut = round(min(0.5, haircut), 3)
        return self.result(
            risks=[f"{f.label}: {f.detail}" for f in flags],
            confidence=0.6,
            meta={"haircut": haircut, "flags": [f.model_dump() for f in flags]},
        )
