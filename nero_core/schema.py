from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class AssetSymbol(str, Enum):
    BTC = "BTC"
    SPY = "SPY"
    ETH = "ETH"
    GOLD = "GOLD"
    OIL = "OIL"
    FDX = "FDX"


class MacroEvent(BaseModel):
    event_id: str
    event_date: date
    title: str
    narrative: str
    tags: list[str] = Field(default_factory=list)
    asset_bias: dict[str, float] = Field(default_factory=dict)


class AnalysisRequest(BaseModel):
    asset: AssetSymbol
    headline: str = Field(min_length=8)
    lookback_days: int = Field(default=30, ge=10, le=180)


class HistoricalMatch(BaseModel):
    event_id: str
    event_date: date
    title: str
    similarity: float = Field(ge=0, le=1)
    forward_bias: float
    tags: list[str]


class BrainOutput(BaseModel):
    matches: list[HistoricalMatch]
    thematic_score: float = Field(ge=-1, le=1)
    dominant_tags: list[str]


class AssessmentOutput(BaseModel):
    rsi: float = Field(ge=0, le=100)
    trend_score: float = Field(ge=-1, le=1)
    fair_value_gap: Literal["bullish", "bearish", "none"]
    liquidity_sweep: Literal["upside", "downside", "none"]
    momentum_score: float = Field(ge=-1, le=1)
    macd_signal: Literal["bullish", "bearish", "neutral"] = "neutral"
    ma_alignment: Literal["bullish", "bearish", "neutral"] = "neutral"
    atr_pct: float = Field(default=0.0, ge=0)
    confluence_score: float = Field(default=50.0, ge=0, le=100)
    confluence_label: str = "Mixed confluence"
    market_regime: Literal["Bull", "Bear", "Range"] = "Range"
    volatility_regime: Literal["High-Vol", "Normal-Vol", "Low-Vol"] = "Normal-Vol"
    bos_signal: Literal["bullish", "bearish", "none"] = "none"
    technical_bias_score: float = Field(default=0.0, ge=-1, le=1)


class VerdictOutput(BaseModel):
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    summary: str
    drivers: list[str]


class NeroResult(BaseModel):
    request: AnalysisRequest
    brain: BrainOutput
    assessment: AssessmentOutput
    verdict: VerdictOutput


class BacktestResult(BaseModel):
    average_forward_return: float
    win_rate: float
    sample_count: int
    trades: list[dict[str, object]]
