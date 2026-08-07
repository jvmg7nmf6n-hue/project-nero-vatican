"""Module 2 — Economic Calendar & Surprise Engine.

Two jobs:
  * Score the *surprise* of recent data releases (actual vs consensus) and turn
    it into directional signals.
  * Surface upcoming high-importance catalysts (FOMC, CPI, NFP, ECB, BOJ) so the
    risk and scenario engines know what is on the radar.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, Signal
from .base import AnalysisContext, BaseAgent

# How a positive surprise in each series tends to push each asset.
# +1 means "upside surprise is bullish for the asset", -1 the opposite.
_INFLATION_GOLD = +1     # hot inflation -> gold bid (debasement / real-rate ambiguity)
_INFLATION_BTC = +0      # mixed; treat as mild
_LABOR_GOLD = -1         # strong jobs -> hawkish Fed -> gold pressure
_LABOR_BTC = -1


class EconomicCalendarAgent(BaseAgent):
    name = "economic_calendar"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        cal = ctx.data.calendar
        recent = cal.recent_releases()
        upcoming = cal.upcoming()

        signals: list[Signal] = []
        facts: list[str] = []
        for item in recent:
            surprise = item.surprise
            if surprise is None:
                continue
            facts.append(
                f"{item.name}: actual {item.actual} vs cons {item.consensus} "
                f"(surprise {surprise:+.2f})"
            )
            gold_dir, btc_dir = self._direction(item.category)
            if gold_dir:
                signals.append(self._mk(Asset.GOLD, surprise * gold_dir, item.category, item.name))
            if btc_dir:
                signals.append(self._mk(Asset.BITCOIN, surprise * btc_dir, item.category, item.name))

        catalysts = [
            {"name": i.name, "region": i.region.value, "category": i.category.value,
             "when": i.when.isoformat(), "consensus": i.consensus}
            for i in upcoming
        ]
        # Average absolute surprise as the agent's confidence proxy.
        avg_abs = (sum(abs(s.weighted_score) for s in signals) / len(signals)) if signals else 0.0
        return self.result(
            signals=signals,
            facts=facts,
            expectations=[f"Upcoming: {c['name']} ({c['region']})" for c in catalysts],
            confidence=min(0.8, 0.4 + avg_abs),
            meta={"catalysts": catalysts},
        )

    @staticmethod
    def _direction(cat: Category) -> tuple[int, int]:
        if cat == Category.INFLATION:
            return _INFLATION_GOLD, _INFLATION_BTC
        if cat == Category.LABOR:
            return _LABOR_GOLD, _LABOR_BTC
        return 0, 0

    def _mk(self, asset: Asset, score: float, cat: Category, name: str) -> Signal:
        # Map a surprise*direction in roughly [-1,1] onto the -2..2 bias scale.
        bias = Bias.from_score(score * 2)
        return Signal(
            asset=asset, bias=bias, strength=min(1.0, abs(score) + 0.2),
            category=cat, source_agent=self.name,
            is_fact=True, rationale=f"data surprise on {name}",
        )
