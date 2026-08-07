"""Module 1 — News Intelligence.

Classifies each ingested event by region/category and emits a directional signal
per asset. Uses the LLM (optionally with web search to enrich a thin headline)
and falls back to a keyword heuristic when the LLM is unavailable.
"""
from __future__ import annotations

import json

from ..llm import LLMUnavailable
from ..schemas import AgentResult, Asset, Bias, Category, DataProvenance, Region, Signal
from .base import AnalysisContext, BaseAgent

_BULLISH_GOLD = ("rate cut", "dovish", "war", "sanction", "inflation", "weak dollar",
                 "safe haven", "central bank buying", "escalation", "recession")
_BEARISH_GOLD = ("rate hike", "hawkish", "strong dollar", "risk-on", "yields rise",
                 "ceasefire", "disinflation")
_BULLISH_BTC = ("etf inflow", "rate cut", "liquidity", "adoption", "approval",
                "halving", "risk-on", "institutional")
_BEARISH_BTC = ("ban", "hack", "crackdown", "rate hike", "regulation", "risk-off",
                "outflow", "liquidation")


class NewsIntelligenceAgent(BaseAgent):
    name = "news_intelligence"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        if not ctx.events:
            # CC-1 directive (2026-08-07): UNAVAILABLE, not the SYNTHETIC
            # default -- nothing was consumed at all this cycle, matching
            # combined_provenance's own "empty means UNAVAILABLE, not
            # SYNTHETIC" precedent (_synthesis.py) rather than implying a
            # fake reading was produced.
            return self.result(confidence=0.2, facts=["No events ingested this cycle."],
                               provenance=DataProvenance.UNAVAILABLE)
        try:
            return await self._llm_classify(ctx)
        except LLMUnavailable:
            return self._heuristic(ctx)

    @staticmethod
    def _events_provenance(events) -> DataProvenance:
        """CC-1 directive (2026-08-07, "fix news_intelligence/geopolitical
        provenance"): this agent's own provenance is the provenance of
        whichever events it actually consumed this cycle -- per-cycle, per
        the real MacroEvent.provenance each one carries (set by
        nero_core.execution.bellwether_overlay.build_real_macro_events for a
        genuine live RSS match, left on MacroEvent's own SYNTHETIC default
        otherwise), never a blanket assumption.

        Deliberately NOT _synthesis.weakest_provenance -- that function
        combines MULTIPLE AGENTS' own already-computed provenances (where
        MIXED may already be a value in the list) and is the wrong tool
        here: a genuine blend of REAL and SYNTHETIC EVENTS is exactly
        DataProvenance.MIXED's own documented case ("an agent/composite
        whose inputs are a genuine blend of REAL and SYNTHETIC fields"),
        which weakest_provenance never synthesizes on its own (it would
        collapse a [REAL, SYNTHETIC] list straight to SYNTHETIC, silently
        discarding the real contribution). Uses the SAME all-real/any-real/
        none-real pattern monetary_policy.py already uses for its own two
        fixed real inputs, generalized to N events instead of 2 fields."""
        if not events:
            return DataProvenance.UNAVAILABLE
        provenances = [e.provenance for e in events]
        if all(p == DataProvenance.REAL for p in provenances):
            return DataProvenance.REAL
        if any(p == DataProvenance.REAL for p in provenances):
            return DataProvenance.MIXED
        return DataProvenance.SYNTHETIC

    async def _llm_classify(self, ctx: AnalysisContext) -> AgentResult:
        items = [{"headline": e.headline, "summary": e.summary, "source": e.source}
                 for e in ctx.events]
        prompt = (
            "You are a macro news desk for Gold (XAUUSD) and Bitcoin (BTCUSD). "
            "For the events below, return a JSON object:\n"
            '{"signals":[{"asset":"GOLD|BITCOIN","bias":"STRONG_BEARISH|BEARISH|NEUTRAL|BULLISH|STRONG_BULLISH",'
            '"strength":0..1,"category":"<CATEGORY>","rationale":"...","headline":"..."}],'
            '"facts":["observed facts only"],"expectations":["what the market already prices in"]}\n'
            "Categories: MONETARY_POLICY, INFLATION, GROWTH, LABOR, GEOPOLITICS, LIQUIDITY, "
            "REGULATION, ETF_FLOWS, ON_CHAIN, DERIVATIVES, RISK_SENTIMENT, CENTRAL_BANK_DEMAND, OTHER.\n"
            "Be conservative; most single headlines are NEUTRAL-to-mild.\n\n"
            f"EVENTS:\n{json.dumps(items, indent=2)}"
        )
        data = await self.llm.complete_json(prompt, web_search=False)
        signals = [self._coerce_signal(s) for s in data.get("signals", [])]
        signals = [s for s in signals if s is not None]
        return self.result(
            signals=signals,
            facts=list(data.get("facts", []))[:8],
            expectations=list(data.get("expectations", []))[:8],
            confidence=0.6 if signals else 0.3,
            used_llm=True,
            provenance=self._events_provenance(ctx.events),
        )

    def _coerce_signal(self, s: dict) -> Signal | None:
        try:
            return Signal(
                asset=Asset(s["asset"]),
                bias=Bias(s["bias"]),
                strength=float(s.get("strength", 0.5)),
                category=Category(s.get("category", "OTHER")),
                rationale=str(s.get("rationale", ""))[:400],
                source_agent=self.name,
            )
        except (KeyError, ValueError):
            return None

    def _heuristic(self, ctx: AnalysisContext) -> AgentResult:
        signals: list[Signal] = []
        facts: list[str] = []
        for e in ctx.events:
            text = f"{e.headline} {e.summary}".lower()
            facts.append(f"{e.region.value}: {e.headline}")
            g = self._score(text, _BULLISH_GOLD, _BEARISH_GOLD)
            b = self._score(text, _BULLISH_BTC, _BEARISH_BTC)
            if g:
                signals.append(Signal(asset=Asset.GOLD, bias=Bias.from_score(g),
                                      strength=min(1.0, abs(g) / 2), category=e.category,
                                      rationale=f"keyword match in: {e.headline}", source_agent=self.name))
            if b:
                signals.append(Signal(asset=Asset.BITCOIN, bias=Bias.from_score(b),
                                      strength=min(1.0, abs(b) / 2), category=e.category,
                                      rationale=f"keyword match in: {e.headline}", source_agent=self.name))
        return self.result(signals=signals, facts=facts[:8],
                           confidence=0.4 if signals else 0.25, used_llm=False,
                           provenance=self._events_provenance(ctx.events))

    @staticmethod
    def _score(text: str, bull: tuple[str, ...], bear: tuple[str, ...]) -> int:
        s = sum(1 for k in bull if k in text) - sum(1 for k in bear if k in text)
        return max(-2, min(2, s))
