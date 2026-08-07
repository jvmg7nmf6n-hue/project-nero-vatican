"""Module 15 — Learning Engine.

Closes the loop. Reads the prediction store for rolling directional accuracy and
Brier calibration, exposes them so the Trade Engine can scale confidence, and
(after the cycle) persists the fresh predictions for future scoring.

Note: this agent *reads* history during the cycle. Persisting the new prediction
happens in the orchestrator once the final output exists, via persist().
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset
from ..store import PredictionStore
from .base import AnalysisContext, BaseAgent


class LearningAgent(BaseAgent):
    name = "learning"

    def __init__(self, store: PredictionStore, llm=None) -> None:
        super().__init__(llm)
        self.store = store

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        overall = self.store.rolling_accuracy()
        gold_acc = self.store.rolling_accuracy(Asset.GOLD.value)
        btc_acc = self.store.rolling_accuracy(Asset.BITCOIN.value)
        n = len(self.store.scored())
        facts = [
            f"Rolling directional accuracy: {overall:.0%} over {n} scored calls "
            f"(gold {gold_acc:.0%}, btc {btc_acc:.0%}).",
            f"Brier score (lower=better): {self.store.brier():.3f}.",
        ]
        if n == 0:
            facts = ["No scored history yet — confidence uncalibrated, defaulting to neutral prior."]
        return self.result(
            facts=facts,
            confidence=0.5,
            meta={
                "rolling_accuracy": overall,
                "gold_accuracy": gold_acc,
                "btc_accuracy": btc_acc,
                "brier": self.store.brier(),
                "scored_count": n,
            },
        )
