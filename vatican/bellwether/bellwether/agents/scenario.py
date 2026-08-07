"""Module 12 — Scenario Engine.

Turns the net reads into a small set of probability-weighted forward scenarios
(base / risk-on / risk-off), so the output is a distribution of outcomes rather
than a single point call.
"""
from __future__ import annotations

from ..llm import LLMUnavailable
from ..schemas import AgentResult, Asset, Bias, DataProvenance, Scenario
from ._synthesis import weakest_provenance
from .base import AnalysisContext, BaseAgent


class ScenarioAgent(BaseAgent):
    name = "scenario"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        gold = ctx.result("gold_analysis")
        btc = ctx.result("bitcoin_analysis")
        g_bias = Bias(gold.meta.get("bias", "NEUTRAL")) if gold else Bias.NEUTRAL
        b_bias = Bias(btc.meta.get("bias", "NEUTRAL")) if btc else Bias.NEUTRAL

        scenarios = self._heuristic_scenarios(g_bias, b_bias)
        try:
            if self.llm.available:
                scenarios = await self._llm_scenarios(ctx, g_bias, b_bias) or scenarios
        except LLMUnavailable:
            pass
        # VATICAN INTEGRATION (Stage 2, "close the provenance leak"
        # directive): scenario just narrates gold_analysis/bitcoin_analysis's
        # own biases, so it can never be more trustworthy than the weaker of
        # the two -- this needs no live/mock branch of its own, since those
        # two agents already encode the mode-dependent behavior correctly.
        provenance = weakest_provenance([
            gold.provenance if gold else DataProvenance.UNAVAILABLE,
            btc.provenance if btc else DataProvenance.UNAVAILABLE,
        ])
        return self.result(confidence=0.55, provenance=provenance,
                           meta={"scenarios": [s.model_dump() for s in scenarios]})

    def _heuristic_scenarios(self, g: Bias, b: Bias) -> list[Scenario]:
        return [
            Scenario(name="Base case", probability=0.5, gold_bias=g, btc_bias=b,
                     narrative="Current drivers persist; net reads play out modestly."),
            Scenario(name="Risk-on / easier policy", probability=0.25,
                     gold_bias=Bias.BULLISH, btc_bias=Bias.STRONG_BULLISH,
                     narrative="Softer data + dovish repricing lifts liquidity assets; BTC outperforms."),
            Scenario(name="Risk-off / hawkish shock", probability=0.25,
                     gold_bias=Bias.BULLISH, btc_bias=Bias.BEARISH,
                     narrative="Stronger dollar / vol spike; gold gets haven bid, BTC de-risks."),
        ]

    async def _llm_scenarios(self, ctx: AnalysisContext, g: Bias, b: Bias) -> list[Scenario]:
        m = ctx.market
        prompt = (
            "Generate exactly 3 probability-weighted scenarios (probabilities sum to 1) for the "
            "next 1-4 weeks for gold and bitcoin. Return JSON list of "
            '{"name":...,"probability":0..1,"gold_bias":"<BIAS>","btc_bias":"<BIAS>","narrative":"1 sentence"}. '
            "BIAS in {STRONG_BEARISH,BEARISH,NEUTRAL,BULLISH,STRONG_BULLISH}.\n"
            f"Context: gold read {g.value}, btc read {b.value}, real yield {m.real_yield_10y}%, "
            f"DXY {m.dxy}, VIX {m.vix}."
        )
        data = await self.llm.complete_json(prompt)
        out = []
        for s in data if isinstance(data, list) else data.get("scenarios", []):
            try:
                out.append(Scenario(name=s["name"], probability=float(s["probability"]),
                                    gold_bias=Bias(s["gold_bias"]), btc_bias=Bias(s["btc_bias"]),
                                    narrative=s.get("narrative", "")))
            except (KeyError, ValueError):
                continue
        return out[:3]
