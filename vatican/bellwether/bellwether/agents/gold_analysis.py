"""Module 6 — Gold Analysis.

Synthesises every gold-relevant signal into a single read: net bias, probability,
a plain-English 'the read', and a deliberate counter-case (the strongest argument
the other way) to fight confirmation bias.
"""
from __future__ import annotations

from ..llm import LLMUnavailable
from ..schemas import AgentResult, Asset, DataProvenance, Signal
from ._synthesis import aggregate, combined_provenance, real_only_signals
from .base import AnalysisContext, BaseAgent


class GoldAnalysisAgent(BaseAgent):
    name = "gold_analysis"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        # VATICAN INTEGRATION (Stage 2): in "mock" mode (the default, and
        # every existing test's mode), behavior is byte-identical to
        # upstream — every signal blends in, exactly as before. In "live"
        # mode, only signals from agents whose OWN provenance is REAL/MIXED
        # contribute — a purely-mock agent is excluded from this read
        # rather than silently blended in (see real_only_signals's own
        # docstring for why this is decided per-agent, not from data_mode).
        if ctx.settings.data_mode == "live":
            signals = real_only_signals(ctx, Asset.GOLD)
        else:
            signals = ctx.all_signals(Asset.GOLD)
        read = aggregate(Asset.GOLD, signals)
        provenance = (combined_provenance(ctx, signals) if ctx.settings.data_mode == "live"
                     else DataProvenance.SYNTHETIC)
        # Re-emit a single consolidated signal so downstream agents see the net.
        net_signal = Signal(asset=Asset.GOLD, bias=read.bias, strength=min(1.0, abs(read.net_score) / 2 + 0.2),
                            rationale="consolidated gold read", source_agent=self.name)
        reasoning, counter = self._narrate_fallback(read)
        try:
            if self.llm.available:
                reasoning, counter = await self._narrate_llm(ctx, read)
        except LLMUnavailable:
            pass
        return self.result(
            signals=[net_signal],
            predictions=[reasoning],
            expectations=[f"COUNTER-CASE: {counter}"],
            confidence=read.confidence,
            used_llm=self.llm.available,
            provenance=provenance,
            meta={
                "net_score": read.net_score,
                "bias": read.bias.value,
                "probability_up": read.probability_up,
                "top_drivers": read.top_drivers,
                "reasoning": reasoning,
                "counter_case": counter,
            },
        )

    def _narrate_fallback(self, read) -> tuple[str, str]:
        bull = "; ".join(s.rationale for s in read.bullish[:3]) or "no strong bullish drivers"
        bear = "; ".join(s.rationale for s in read.bearish[:3]) or "no strong bearish drivers"
        reasoning = (f"Gold net bias {read.bias.value} (score {read.net_score:+.2f}, "
                     f"P(up)≈{read.probability_up:.0%}). Supporting: {bull}.")
        counter = f"Against the call: {bear}."
        return reasoning, counter

    async def _narrate_llm(self, ctx: AnalysisContext, read) -> tuple[str, str]:
        m = ctx.market
        bull = " | ".join(s.rationale for s in read.bullish[:4])
        bear = " | ".join(s.rationale for s in read.bearish[:4])
        prompt = (
            "Write a concise gold (XAUUSD) desk read. Return JSON "
            '{"read":"2-3 sentences","counter_case":"1-2 sentences, strongest opposing argument"}.\n'
            f"Net bias: {read.bias.value} (score {read.net_score:+.2f}, P(up)≈{read.probability_up:.0%}).\n"
            f"Market: real yield {m.real_yield_10y}%, DXY {m.dxy}, VIX {m.vix}.\n"
            f"Bullish drivers: {bull}\nBearish drivers: {bear}\n"
            "Be specific and non-promotional. Never claim certainty."
        )
        data = await self.llm.complete_json(prompt)
        return (str(data.get("read", "")).strip(),
                str(data.get("counter_case", "")).strip())
