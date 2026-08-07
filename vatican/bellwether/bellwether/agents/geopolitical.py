"""Module 3 — Geopolitical Engine.

Assesses geopolitical tension from the event stream and maps it to safe-haven
demand (gold) and risk appetite (bitcoin). Escalation generally bids gold and
pressures bitcoin near-term; de-escalation does the reverse.
"""
from __future__ import annotations

import json

from ..llm import LLMUnavailable
from ..schemas import AgentResult, Asset, Bias, Category, Signal
from .base import AnalysisContext, BaseAgent

_ESCALATION = ("war", "invasion", "strike", "missile", "sanction", "escalation",
               "conflict", "attack", "nuclear", "blockade", "coup")
_DEESCALATION = ("ceasefire", "truce", "peace", "de-escalation", "deal", "agreement")


class GeopoliticalAgent(BaseAgent):
    name = "geopolitical"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        geo_events = [e for e in ctx.events
                      if e.category == Category.GEOPOLITICS
                      or any(k in f"{e.headline} {e.summary}".lower() for k in _ESCALATION + _DEESCALATION)]
        if not geo_events:
            return self.result(confidence=0.3, facts=["No material geopolitical events detected."])
        try:
            return await self._llm(ctx, geo_events)
        except LLMUnavailable:
            return self._heuristic(geo_events)

    async def _llm(self, ctx: AnalysisContext, events) -> AgentResult:
        items = [{"headline": e.headline, "region": e.region.value} for e in events]
        prompt = (
            "Assess geopolitical risk for safe-haven assets. Return JSON: "
            '{"tension":0..1,"direction":"escalating|stable|deescalating",'
            '"gold_bias":"<BIAS>","btc_bias":"<BIAS>","rationale":"...",'
            '"facts":[...]}. BIAS in {STRONG_BEARISH,BEARISH,NEUTRAL,BULLISH,STRONG_BULLISH}. '
            "Remember: escalation usually bids gold, pressures bitcoin short-term.\n\n"
            f"EVENTS:\n{json.dumps(items, indent=2)}"
        )
        data = await self.llm.complete_json(prompt)
        tension = float(data.get("tension", 0.4))
        signals = []
        try:
            signals.append(Signal(asset=Asset.GOLD, bias=Bias(data["gold_bias"]),
                                  strength=tension, category=Category.GEOPOLITICS,
                                  rationale=data.get("rationale", ""), source_agent=self.name))
            signals.append(Signal(asset=Asset.BITCOIN, bias=Bias(data["btc_bias"]),
                                  strength=tension, category=Category.GEOPOLITICS,
                                  rationale=data.get("rationale", ""), source_agent=self.name))
        except (KeyError, ValueError):
            pass
        return self.result(signals=signals, facts=list(data.get("facts", []))[:6],
                           confidence=min(0.85, 0.5 + tension / 2), used_llm=True,
                           meta={"tension": tension, "direction": data.get("direction")})

    def _heuristic(self, events) -> AgentResult:
        text = " ".join(f"{e.headline} {e.summary}".lower() for e in events)
        esc = sum(1 for k in _ESCALATION if k in text)
        de = sum(1 for k in _DEESCALATION if k in text)
        net = esc - de
        tension = min(1.0, esc / 4)
        gold = Bias.from_score(max(-2, min(2, net)))
        btc = Bias.from_score(max(-2, min(2, -net)))  # inverse short-term
        signals = [
            Signal(asset=Asset.GOLD, bias=gold, strength=max(0.3, tension),
                   category=Category.GEOPOLITICS, source_agent=self.name,
                   rationale=f"{esc} escalation vs {de} de-escalation keywords"),
            Signal(asset=Asset.BITCOIN, bias=btc, strength=max(0.3, tension),
                   category=Category.GEOPOLITICS, source_agent=self.name,
                   rationale="near-term risk-off proxy"),
        ]
        return self.result(signals=signals, confidence=0.4 + tension / 3,
                           meta={"tension": tension})
