"""Module 10 — Correlation Engine.

Adds context (not standalone signals) about the prevailing cross-asset regime:
gold's inverse link to real yields, bitcoin's beta to risk, and whether gold and
bitcoin are currently moving together (a 'debasement trade' tell) or diverging.
It nudges confidence rather than adding fresh directional pressure.
"""
from __future__ import annotations

from ..schemas import AgentResult, DataProvenance
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
            # VATICAN INTEGRATION (Stage 2, "close the provenance leak"
            # directive): the three coefficients above are hardcoded design
            # constants (-0.7, 0.55/0.35, 0.4/0.2), not computed from data —
            # confirmed in docs/bellwether_audit.md ("not even mock-random").
            # Which branch gets picked depends on real_yield_10y/vix/dxy, but
            # the OUTPUT is always one of a fixed handful of numbers either
            # way — this agent structurally can never be REAL until it's
            # rewritten to compute an actual rolling correlation from real
            # candle history (a real future addition, not a wiring gap).
            # Unconditionally SYNTHETIC, in every data_mode. Emits no
            # signals, so it was never at risk of leaking into
            # gold_analysis/bitcoin_analysis's aggregate in the first place.
            provenance=DataProvenance.SYNTHETIC,
            meta={
                "gold_realyield_corr": gold_realyield_corr,
                "btc_risk_corr": btc_risk_corr,
                "gold_btc_corr": gold_btc_corr,
            },
        )
