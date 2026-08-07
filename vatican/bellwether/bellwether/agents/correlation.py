"""Module 10 — Correlation Engine.

Adds context (not standalone signals) about the prevailing cross-asset regime:
gold's inverse link to real yields, bitcoin's beta to risk, and whether gold and
bitcoin are currently moving together (a 'debasement trade' tell) or diverging.
It nudges confidence rather than adding fresh directional pressure.
"""
from __future__ import annotations

from ..schemas import AgentResult
from .base import AnalysisContext, BaseAgent


class CorrelationAgent(BaseAgent):
    name = "correlation"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        m = ctx.market
        # Stylised, regime-flavoured correlation estimates derived from the snapshot.
        # (A live build would compute rolling correlations from price history.)
        gold_realyield_corr = -0.7      # structural
        btc_risk_corr = 0.55 if m.vix < 20 else 0.35
        # When the dollar is strong both tend to struggle together.
        gold_btc_corr = 0.4 if m.dxy > 105 else 0.2

        notes = [
            f"Gold vs 10y real yield: ~{gold_realyield_corr:+.2f} (inverse, structural).",
            f"BTC vs risk appetite: ~{btc_risk_corr:+.2f} (regime-dependent).",
            f"Gold vs BTC: ~{gold_btc_corr:+.2f} "
            f"({'co-moving / debasement tone' if gold_btc_corr > 0.35 else 'diversifying'}).",
        ]
        return self.result(
            facts=notes,
            confidence=0.5,
            meta={
                "gold_realyield_corr": gold_realyield_corr,
                "btc_risk_corr": btc_risk_corr,
                "gold_btc_corr": gold_btc_corr,
            },
        )
