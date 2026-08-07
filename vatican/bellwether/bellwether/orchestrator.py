"""The Orchestrator — multi-agent coordinator.

Runs the 15 modules in dependency stages (concurrently within a stage), then
composes the single AnalysisOutput defined by the master prompt and persists the
fresh predictions so the Learning Engine can score them later.

    Stage A  independent producers  (news, calendar, geo, monetary, liquidity,
                                     on-chain, derivatives, correlation,
                                     historical, learning)
    Stage B  per-asset synthesis    (gold_analysis, bitcoin_analysis)
    Stage C  scenario + risk
    Stage D  trade_recommendation
"""
from __future__ import annotations

import asyncio
import logging

from .agents._synthesis import aggregate
from .agents.base import AnalysisContext
from .agents.bitcoin_analysis import BitcoinAnalysisAgent
from .agents.correlation import CorrelationAgent
from .agents.derivatives_etf import DerivativesEtfAgent
from .agents.economic_calendar import EconomicCalendarAgent
from .agents.geopolitical import GeopoliticalAgent
from .agents.gold_analysis import GoldAnalysisAgent
from .agents.historical_analog import HistoricalAnalogAgent
from .agents.learning import LearningAgent
from .agents.liquidity import LiquidityAgent
from .agents.monetary_policy import MonetaryPolicyAgent
from .agents.news_intelligence import NewsIntelligenceAgent
from .agents.onchain import OnChainAgent
from .agents.risk import RiskAgent
from .agents.scenario import ScenarioAgent
from .agents.trade_recommendation import TradeRecommendationAgent
from .config import Settings, get_settings
from .data import build_data_hub
from .llm import LLMClient
from .schemas import (
    AnalysisOutput,
    Asset,
    Bias,
    Category,
    HistoricalMatch,
    MacroEvent,
    Region,
    Scenario,
)
from .store import PredictionStore

log = logging.getLogger("bellwether.orchestrator")


class Orchestrator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = LLMClient(self.settings)
        self.data = build_data_hub(self.settings)
        self.store = PredictionStore(self.settings.store_path)

        self.news = NewsIntelligenceAgent(self.llm)
        self.calendar = EconomicCalendarAgent(self.llm)
        self.geo = GeopoliticalAgent(self.llm)
        self.monetary = MonetaryPolicyAgent(self.llm)
        self.liquidity = LiquidityAgent(self.llm)
        self.onchain = OnChainAgent(self.llm)
        self.derivatives = DerivativesEtfAgent(self.llm)
        self.correlation = CorrelationAgent(self.llm)
        self.historical = HistoricalAnalogAgent(self.llm)
        self.learning = LearningAgent(self.store, self.llm)
        self.gold = GoldAnalysisAgent(self.llm)
        self.bitcoin = BitcoinAnalysisAgent(self.llm)
        self.scenario = ScenarioAgent(self.llm)
        self.risk = RiskAgent(self.llm)
        self.trade = TradeRecommendationAgent(self.llm)

    async def analyze(self, events: list[MacroEvent] | None = None,
                      *, persist: bool = True) -> AnalysisOutput:
        events = events or []
        ctx = AnalysisContext(
            events=events,
            market=self.data.market.snapshot(),
            data=self.data,
            settings=self.settings,
        )

        await self._run_stage(ctx, [
            self.news, self.calendar, self.geo, self.monetary, self.liquidity,
            self.onchain, self.derivatives, self.correlation, self.historical, self.learning,
        ])
        await self._run_stage(ctx, [self.gold, self.bitcoin])
        await self._run_stage(ctx, [self.scenario, self.risk])
        await self._run_stage(ctx, [self.trade])

        output = self._compose(ctx)
        if persist:
            self._persist(output)
        return output

    async def _run_stage(self, ctx: AnalysisContext, agents) -> None:
        results = await asyncio.gather(
            *(a.run(ctx) for a in agents), return_exceptions=True
        )
        for agent, res in zip(agents, results):
            if isinstance(res, Exception):
                log.warning("agent %s failed: %s", agent.name, res)
                continue
            ctx.results[res.agent] = res

    # ------------------------------------------------------------------ #
    # Composition
    # ------------------------------------------------------------------ #
    def _compose(self, ctx: AnalysisContext) -> AnalysisOutput:
        gold_read = aggregate(Asset.GOLD, ctx.all_signals(Asset.GOLD))
        btc_read = aggregate(Asset.BITCOIN, ctx.all_signals(Asset.BITCOIN))

        primary = self._primary_event(ctx)
        headline = primary.headline if primary else "Macro synthesis (no discrete headline)"
        category = primary.category if primary else self._dominant_category(ctx)
        country = primary.region if primary else Region.GLOBAL

        importance = self._importance(ctx)
        surprise = self._surprise(ctx)

        trade = ctx.result("trade_recommendation")
        recs = trade.meta.get("recommendations", {}) if trade else {}
        gold_rec = recs.get("GOLD", {})
        btc_rec = recs.get("BITCOIN", {})

        confidence = round(
            (float(gold_rec.get("confidence", gold_read.confidence))
             + float(btc_rec.get("confidence", btc_read.confidence))) / 2, 3
        )

        hist = ctx.result("historical_analog")
        matches: list[HistoricalMatch] = hist.historical_matches if hist else []

        scen = ctx.result("scenario")
        scenarios = [Scenario(**s) for s in (scen.meta.get("scenarios", []) if scen else [])]

        risk = ctx.result("risk")
        risks = risk.risks if risk else []

        assumptions = self._assumptions(ctx)
        reasoning = self._reasoning(ctx, gold_rec, btc_rec)
        # VATICAN INTEGRATION (Stage 2): every agent that actually ran this
        # cycle, labelled with its own reported provenance — so a consumer
        # of gold_bias/confidence can see exactly which agents that number
        # is built from, not just trust it.
        provenance_breakdown = {name: res.provenance for name, res in ctx.results.items()}

        return AnalysisOutput(
            headline=headline,
            category=category,
            country=country,
            importance_score=importance,
            surprise_score=surprise,
            gold_bias=Bias(gold_rec.get("bias", gold_read.bias.value)),
            bitcoin_bias=Bias(btc_rec.get("bias", btc_read.bias.value)),
            confidence=confidence,
            gold_agreement=float(gold_rec.get("agreement", gold_read.agreement)),
            gold_coverage=float(gold_rec.get("coverage", gold_read.coverage)),
            bitcoin_agreement=float(btc_rec.get("agreement", btc_read.agreement)),
            bitcoin_coverage=float(btc_rec.get("coverage", btc_read.coverage)),
            probability_up_gold=float(gold_rec.get("probability_up", gold_read.probability_up)),
            probability_up_bitcoin=float(btc_rec.get("probability_up", btc_read.probability_up)),
            historical_matches=matches,
            assumptions=assumptions,
            risks=risks,
            provenance_breakdown=provenance_breakdown,
            alternative_scenarios=scenarios,
            reasoning=reasoning,
        )

    def _primary_event(self, ctx: AnalysisContext) -> MacroEvent | None:
        if not ctx.events:
            return None
        # Most "important" = strongest associated signal, else first.
        def weight(e: MacroEvent) -> float:
            return max((s.strength for s in ctx.all_signals()
                        if e.headline[:30] in s.rationale), default=0.0)
        return max(ctx.events, key=weight)

    def _dominant_category(self, ctx: AnalysisContext) -> Category:
        counts: dict[Category, float] = {}
        for s in ctx.all_signals():
            counts[s.category] = counts.get(s.category, 0.0) + s.strength
        return max(counts, key=counts.get) if counts else Category.OTHER

    def _importance(self, ctx: AnalysisContext) -> float:
        sigs = ctx.all_signals()
        mass = min(1.0, sum(s.strength for s in sigs) / 8.0)
        geo = ctx.result("geopolitical")
        tension = float(geo.meta.get("tension", 0.0)) if geo else 0.0
        cal = ctx.result("economic_calendar")
        has_catalyst = 1.0 if (cal and cal.meta.get("catalysts")) else 0.0
        return round(min(1.0, 0.5 * mass + 0.3 * tension + 0.2 * has_catalyst), 3)

    def _surprise(self, ctx: AnalysisContext) -> float:
        cal = ctx.result("economic_calendar")
        if not cal:
            return 0.2
        scores = [abs(s.weighted_score) for s in cal.signals]
        return round(min(1.0, (max(scores) if scores else 0.2)), 3)

    def _assumptions(self, ctx: AnalysisContext) -> list[str]:
        out: list[str] = []
        for name in ("monetary_policy", "liquidity", "gold_analysis", "bitcoin_analysis"):
            res = ctx.result(name)
            if res:
                out.extend(res.expectations)
        # de-dup, keep order
        seen, deduped = set(), []
        for a in out:
            if a not in seen:
                seen.add(a)
                deduped.append(a)
        return deduped[:8]

    def _reasoning(self, ctx: AnalysisContext, gold_rec: dict, btc_rec: dict) -> str:
        parts = []
        if gold_rec.get("read"):
            parts.append(f"GOLD — {gold_rec['read']}")
        if btc_rec.get("read"):
            parts.append(f"BITCOIN — {btc_rec['read']}")
        learn = ctx.result("learning")
        if learn and learn.facts:
            parts.append(learn.facts[0])
        return " ".join(parts)

    def _persist(self, output: AnalysisOutput) -> None:
        self.store.record_prediction(
            Asset.GOLD.value, output.gold_bias.value,
            output.probability_up_gold, output.confidence, ref=output.headline)
        self.store.record_prediction(
            Asset.BITCOIN.value, output.bitcoin_bias.value,
            output.probability_up_bitcoin, output.confidence, ref=output.headline)

    # Convenience for the learning feedback loop.
    def record_outcome(self, prediction_id: str, realized_return: float) -> bool:
        return self.store.record_outcome(prediction_id, realized_return)
