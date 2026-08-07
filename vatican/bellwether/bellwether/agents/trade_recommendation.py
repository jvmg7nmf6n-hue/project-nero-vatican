"""Module 14 — Trade Recommendation Engine.

Combines each asset's net read with the Risk Engine's haircut and the Learning
Engine's historical accuracy to produce a final, explainable bias. Output is a
*bias with assumptions and risks*, never a guaranteed outcome or sized order.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, DataProvenance
from ._synthesis import weakest_provenance
from .base import AnalysisContext, BaseAgent


class TradeRecommendationAgent(BaseAgent):
    name = "trade_recommendation"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        risk = ctx.result("risk")
        haircut = float(risk.meta.get("haircut", 0.0)) if risk else 0.0
        learn = ctx.result("learning")
        accuracy = float(learn.meta.get("rolling_accuracy", 0.5)) if learn else 0.5
        # Calibration multiplier: a model that's been wrong gets its confidence trimmed.
        calib = 0.7 + 0.6 * (accuracy - 0.5)   # accuracy 0.5 -> 0.7 ; 0.75 -> 0.85
        risk_provenance = risk.provenance if risk else DataProvenance.UNAVAILABLE
        learn_provenance = learn.provenance if learn else DataProvenance.UNAVAILABLE

        recs = {}
        asset_provenances = []
        for asset, agent_name in ((Asset.GOLD, "gold_analysis"), (Asset.BITCOIN, "bitcoin_analysis")):
            res = ctx.result(agent_name)
            if not res:
                continue
            bias = Bias(res.meta.get("bias", "NEUTRAL"))
            raw_conf = float(res.meta.get("confidence", res.confidence))
            prob_up = float(res.meta.get("probability_up", 0.5))
            final_conf = round(max(0.0, (raw_conf - haircut) * calib), 3)

            actionable = final_conf >= ctx.settings.min_actionable_confidence
            stance = bias if actionable else Bias.NEUTRAL
            # VATICAN INTEGRATION (Stage 2, "close the provenance leak"
            # directive): this asset's own recommendation is only as
            # trustworthy as the WEAKEST of its own gold/bitcoin_analysis
            # read, the risk haircut applied on top of it, and the
            # calibration multiplier -- reported per-asset, since GOLD and
            # BITCOIN can genuinely differ (e.g. once VIX lands, liquidity
            # feeds BITCOIN's read but not GOLD's the same way).
            asset_provenance = weakest_provenance([res.provenance, risk_provenance, learn_provenance])
            asset_provenances.append(asset_provenance)
            recs[asset.value] = {
                "bias": stance.value,
                "raw_bias": bias.value,
                "confidence": final_conf,
                "probability_up": prob_up,
                "actionable": actionable,
                "drivers": res.meta.get("top_drivers", []),
                "read": res.meta.get("reasoning", ""),
                "counter_case": res.meta.get("counter_case", ""),
                "provenance": asset_provenance.value,
            }

        notes = [
            f"Applied risk haircut: -{haircut:.2f}",
            f"Calibration from rolling accuracy {accuracy:.0%}: x{calib:.2f}",
            "Output is directional bias for research, not a guaranteed outcome or order.",
        ]
        return self.result(
            predictions=[f"{k}: {v['bias']} (conf {v['confidence']:.0%}, "
                         f"P(up) {v['probability_up']:.0%})" for k, v in recs.items()],
            facts=notes,
            confidence=0.6,
            provenance=weakest_provenance(asset_provenances),
            meta={"recommendations": recs, "haircut": haircut, "calibration": round(calib, 3)},
        )
