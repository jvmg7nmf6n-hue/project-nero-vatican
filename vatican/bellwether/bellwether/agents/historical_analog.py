"""Module 11 — Historical Analog Engine.

Matches the current macro fingerprint (real yields, dollar, vol, policy stance)
against a small library of labelled regimes and returns the closest analogs with
their typical forward behaviour. LLM-enriched when available; otherwise a
nearest-neighbour over a hand-built feature table.
"""
from __future__ import annotations

from ..llm import LLMUnavailable
from ..schemas import AgentResult, HistoricalMatch
from .base import AnalysisContext, BaseAgent

# label -> (real_yield, dxy, vix, regime note, gold_fwd, btc_fwd)
_LIBRARY = [
    ("2020 pandemic easing", 0.5, 96, 35, "ZIRP + QE flood", "+25% / 6m", "+120% / 6m"),
    ("2022 hiking shock", 1.6, 108, 28, "fastest hikes in decades", "-8% / 6m", "-55% / 6m"),
    ("2023-24 higher-for-longer", 2.0, 104, 16, "restrictive but stable", "+12% / 6m", "+40% / 6m"),
    ("2019 mid-cycle cuts", 0.3, 97, 15, "insurance cuts, soft landing", "+15% / 6m", "+30% / 6m"),
    ("2011 sovereign-stress haven bid", 0.1, 75, 30, "EU crisis, safe-haven gold", "+20% / 6m", "n/a"),
]


class HistoricalAnalogAgent(BaseAgent):
    name = "historical_analog"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        matches = self._nearest(ctx)
        try:
            if self.llm.available:
                note = await self._llm_note(ctx, matches)
                return self.result(historical_matches=matches, predictions=[note],
                                   confidence=0.55, used_llm=True,
                                   meta={"matches": [m.label for m in matches]})
        except LLMUnavailable:
            pass
        return self.result(historical_matches=matches, confidence=0.5,
                           meta={"matches": [m.label for m in matches]})

    def _nearest(self, ctx: AnalysisContext) -> list[HistoricalMatch]:
        m = ctx.market
        scored = []
        for label, ry, dxy, vix, note, gfwd, bfwd in _LIBRARY:
            dist = (
                ((m.real_yield_10y - ry) / 2.0) ** 2
                + ((m.dxy - dxy) / 15.0) ** 2
                + ((m.vix - vix) / 15.0) ** 2
            ) ** 0.5
            sim = max(0.0, 1.0 - dist / 3.0)
            scored.append(HistoricalMatch(
                label=label, period=label.split()[0], similarity=round(sim, 3),
                gold_forward_return=gfwd, btc_forward_return=bfwd, note=note,
            ))
        scored.sort(key=lambda x: x.similarity, reverse=True)
        return scored[:3]

    async def _llm_note(self, ctx: AnalysisContext, matches: list[HistoricalMatch]) -> str:
        labels = ", ".join(m.label for m in matches)
        m = ctx.market
        prompt = (
            f"Current macro: 10y real yield {m.real_yield_10y}%, DXY {m.dxy}, VIX {m.vix}. "
            f"Closest historical analogs: {labels}. In two sentences, note what these "
            "analogs imply for gold and bitcoin and the key caveat. No preamble."
        )
        return await self.llm.complete(prompt)
