"""Agent base classes and the shared context object.

Every module in the master prompt is implemented as a BaseAgent. Agents read
from a single AnalysisContext (events + market data + results produced by
upstream agents) and return a uniform AgentResult. This keeps the orchestrator
trivial and makes modules independently testable.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..config import Settings, get_settings
from ..data import DataHub
from ..llm import LLMClient
from ..schemas import AgentResult, Asset, MacroEvent, MarketSnapshot, Signal

log = logging.getLogger("bellwether.agents")


@dataclass
class AnalysisContext:
    """Carried through the whole pipeline; later agents read earlier results."""
    events: list[MacroEvent]
    market: MarketSnapshot
    data: DataHub
    settings: Settings = field(default_factory=get_settings)
    results: dict[str, AgentResult] = field(default_factory=dict)

    # -- convenience accessors over upstream output --
    def all_signals(self, asset: Asset | None = None) -> list[Signal]:
        out: list[Signal] = []
        for res in self.results.values():
            for sig in res.signals:
                if asset is None or sig.asset == asset:
                    out.append(sig)
        return out

    def result(self, agent_name: str) -> AgentResult | None:
        return self.results.get(agent_name)


class BaseAgent(ABC):
    """Subclasses set `name` and implement `run`."""
    name: str = "base"

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    @abstractmethod
    async def run(self, ctx: AnalysisContext) -> AgentResult: ...

    # Small helper so agents can construct their envelope tersely.
    def result(self, **kwargs) -> AgentResult:
        kwargs.setdefault("agent", self.name)
        return AgentResult(**kwargs)
