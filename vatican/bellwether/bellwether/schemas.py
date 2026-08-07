"""Schemas — the typed contracts shared by every agent.

Design rule from the master prompt: keep FACTS, EXPECTATIONS and PREDICTIONS in
separate fields so a reader can always tell what is observed vs. priced-in vs.
inferred by the model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Asset(str, Enum):
    GOLD = "GOLD"        # XAUUSD
    BITCOIN = "BITCOIN"  # BTCUSD


class Region(str, Enum):
    USA = "USA"
    CHINA = "CHINA"
    JAPAN = "JAPAN"
    EUROZONE = "EUROZONE"
    UK = "UK"
    GLOBAL = "GLOBAL"
    OTHER = "OTHER"


class Category(str, Enum):
    MONETARY_POLICY = "MONETARY_POLICY"
    INFLATION = "INFLATION"
    GROWTH = "GROWTH"
    LABOR = "LABOR"
    GEOPOLITICS = "GEOPOLITICS"
    LIQUIDITY = "LIQUIDITY"
    REGULATION = "REGULATION"
    ETF_FLOWS = "ETF_FLOWS"
    ON_CHAIN = "ON_CHAIN"
    DERIVATIVES = "DERIVATIVES"
    RISK_SENTIMENT = "RISK_SENTIMENT"
    CENTRAL_BANK_DEMAND = "CENTRAL_BANK_DEMAND"
    OTHER = "OTHER"


class Bias(str, Enum):
    """Directional pressure. Ordinal values map to a -2..+2 numeric scale."""
    STRONG_BEARISH = "STRONG_BEARISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    STRONG_BULLISH = "STRONG_BULLISH"

    @property
    def score(self) -> int:
        return {
            Bias.STRONG_BEARISH: -2,
            Bias.BEARISH: -1,
            Bias.NEUTRAL: 0,
            Bias.BULLISH: 1,
            Bias.STRONG_BULLISH: 2,
        }[self]

    @classmethod
    def from_score(cls, x: float) -> "Bias":
        if x <= -1.5:
            return cls.STRONG_BEARISH
        if x <= -0.5:
            return cls.BEARISH
        if x < 0.5:
            return cls.NEUTRAL
        if x < 1.5:
            return cls.BULLISH
        return cls.STRONG_BULLISH


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
class MacroEvent(BaseModel):
    """A single ingested headline / data release / development."""
    headline: str
    summary: str = ""
    source: str = "unknown"
    region: Region = Region.GLOBAL
    category: Category = Category.OTHER
    url: str | None = None
    published_at: datetime = Field(default_factory=_now)


class DataProvenance(str, Enum):
    """VATICAN INTEGRATION (added Stage 2, see docs/bellwether_audit.md):
    labels whether a value came from a real data feed, a mock/synthetic
    draw, or neither. Ground rule: "a consumer should never be able to
    mistake a mock number for a real one" — this label lives in the schema
    itself, not a doc, so it travels with the data.

    REAL: sourced from a live/cached real feed (e.g. FRED DFII10).
    SYNTHETIC: `random.uniform()` mock draw — the original Bellwether
        default for every field, unchanged unless a real provider says
        otherwise.
    MIXED: an agent/composite whose inputs are a genuine blend of REAL and
        SYNTHETIC fields (e.g. monetary_policy today: real_yield_10y is
        REAL, dxy is still SYNTHETIC) — deliberately distinct from REAL so
        a mixed result can never be mistaken for a fully real one.
    UNAVAILABLE: a real fetch was attempted and failed, with no mock
        fallback used for that specific value (reserved for a future
        provider that refuses to substitute mock data silently; no current
        provider raises this — every real provider in this codebase falls
        back to the mock draw rather than leaving a field unset)."""
    REAL = "real"
    SYNTHETIC = "synthetic"
    MIXED = "mixed"
    UNAVAILABLE = "unavailable"


class MarketSnapshot(BaseModel):
    """Point-in-time market state used by the quantitative agents."""
    gold_price: float
    btc_price: float
    dxy: float                  # USD index
    real_yield_10y: float       # 10y TIPS real yield, %
    nominal_yield_10y: float
    vix: float
    fed_funds_mid: float
    move_index: float | None = None  # bond vol
    timestamp: datetime = Field(default_factory=_now)
    # VATICAN INTEGRATION: per-field provenance. A field name absent from
    # this dict means SYNTHETIC by convention (the original MockMarketData
    # never populates it at all) — never treat a missing key as REAL.
    field_provenance: dict[str, DataProvenance] = Field(default_factory=dict)

    def provenance_of(self, field: str) -> DataProvenance:
        return self.field_provenance.get(field, DataProvenance.SYNTHETIC)


# --------------------------------------------------------------------------- #
# Intermediate analysis objects
# --------------------------------------------------------------------------- #
class Signal(BaseModel):
    """One directional pressure on one asset, emitted by one agent."""
    asset: Asset
    bias: Bias
    # 0..1 — how strong / important this individual driver is right now.
    strength: float = Field(ge=0.0, le=1.0, default=0.5)
    category: Category = Category.OTHER
    rationale: str = ""
    source_agent: str = ""
    is_fact: bool = False         # observed data vs. inference

    @computed_field  # type: ignore[misc]
    @property
    def weighted_score(self) -> float:
        return self.bias.score * self.strength


class HistoricalMatch(BaseModel):
    label: str
    period: str
    similarity: float = Field(ge=0.0, le=1.0)
    gold_forward_return: str | None = None
    btc_forward_return: str | None = None
    note: str = ""


class Scenario(BaseModel):
    name: str
    probability: float = Field(ge=0.0, le=1.0)
    gold_bias: Bias
    btc_bias: Bias
    narrative: str


class RiskFlag(BaseModel):
    label: str
    severity: float = Field(ge=0.0, le=1.0)
    detail: str


class AgentResult(BaseModel):
    """Uniform envelope every agent returns."""
    agent: str
    signals: list[Signal] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    expectations: list[str] = Field(default_factory=list)
    predictions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    historical_matches: list[HistoricalMatch] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    # VATICAN INTEGRATION: this agent's own honest provenance for the cycle
    # that produced this result — defaults SYNTHETIC (the pre-Stage-2
    # behavior for every agent). An agent sets this itself, from the
    # provenance of whichever upstream fields it actually consumed.
    provenance: DataProvenance = DataProvenance.SYNTHETIC
    used_llm: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Final output — matches the OUTPUT JSON in the master prompt
# --------------------------------------------------------------------------- #
class AnalysisOutput(BaseModel):
    timestamp: datetime = Field(default_factory=_now)
    headline: str
    category: Category
    country: Region
    importance_score: float = Field(ge=0.0, le=1.0)
    surprise_score: float = Field(ge=0.0, le=1.0)
    gold_bias: Bias
    bitcoin_bias: Bias
    confidence: float = Field(ge=0.0, le=1.0)
    probability_up_gold: float = Field(ge=0.0, le=1.0)
    probability_up_bitcoin: float = Field(ge=0.0, le=1.0)
    historical_matches: list[HistoricalMatch] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternative_scenarios: list[Scenario] = Field(default_factory=list)
    reasoning: str = ""
    # VATICAN INTEGRATION: per-agent provenance for this cycle (agent name ->
    # DataProvenance), so a consumer of the top-level bias/confidence can see
    # exactly which of the 15 agents that number is actually built from —
    # "a consumer should never be able to mistake a mock number for a real
    # one" enforced at the output level, not just per-field.
    provenance_breakdown: dict[str, DataProvenance] = Field(default_factory=dict)

    def headline_json(self) -> dict[str, Any]:
        """Compact dict in exactly the field order of the spec."""
        return self.model_dump(mode="json")
