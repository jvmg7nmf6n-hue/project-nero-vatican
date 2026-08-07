"""Module 7 — Bitcoin Analysis.

Mirror of the gold agent for BTCUSD: blends liquidity, on-chain, ETF/derivatives
and news signals into a net read plus a deliberate counter-case.
"""
from __future__ import annotations

from ..llm import LLMUnavailable
from ..schemas import AgentResult, Asset, DataProvenance, Signal
from ._synthesis import aggregate, combined_provenance, real_only_signals
from .base import AnalysisContext, BaseAgent


class BitcoinAnalysisAgent(BaseAgent):
    name = "bitcoin_analysis"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        # VATICAN INTEGRATION (Stage 2): same live/mock split as
        # gold_analysis.py — see that module's own comment for why.
        if ctx.settings.data_mode == "live":
            signals = real_only_signals(ctx, Asset.BITCOIN)
        else:
            signals = ctx.all_signals(Asset.BITCOIN)
        read = aggregate(Asset.BITCOIN, signals)
        provenance = (combined_provenance(ctx, signals) if ctx.settings.data_mode == "live"
                     else DataProvenance.SYNTHETIC)
        net_signal = Signal(asset=Asset.BITCOIN, bias=read.bias,
                            strength=min(1.0, abs(read.net_score) / 2 + 0.2),
                            rationale="consolidated bitcoin read", source_agent=self.name)
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
        reasoning = (f"Bitcoin net bias {read.bias.value} (score {read.net_score:+.2f}, "
                     f"P(up)≈{read.probability_up:.0%}). Supporting: {bull}.")
        counter = f"Against the call: {bear}."
        return reasoning, counter

    async def _narrate_llm(self, ctx: AnalysisContext, read) -> tuple[str, str]:
        m = ctx.market
        bull = " | ".join(s.rationale for s in read.bullish[:4])
        bear = " | ".join(s.rationale for s in read.bearish[:4])
        prompt = (
            "Write a concise bitcoin (BTCUSD) desk read. Return JSON "
            '{"read":"2-3 sentences","counter_case":"1-2 sentences, strongest opposing argument"}.\n'
            f"Net bias: {read.bias.value} (score {read.net_score:+.2f}, P(up)≈{read.probability_up:.0%}).\n"
            f"Market: VIX {m.vix}, DXY {m.dxy}.\n"
            f"Bullish drivers: {bull}\nBearish drivers: {bear}\n"
            "Be specific and non-promotional. Never claim certainty."
        )
        data = await self.llm.complete_json(prompt)
        return (str(data.get("read", "")).strip(),
                str(data.get("counter_case", "")).strip())
