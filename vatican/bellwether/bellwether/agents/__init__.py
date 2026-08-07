"""Agent registry. Each module from the master prompt is a BaseAgent subclass."""
from .base import AnalysisContext, BaseAgent
from .news_intelligence import NewsIntelligenceAgent
from .economic_calendar import EconomicCalendarAgent
from .geopolitical import GeopoliticalAgent
from .monetary_policy import MonetaryPolicyAgent
from .liquidity import LiquidityAgent
from .onchain import OnChainAgent
from .derivatives_etf import DerivativesEtfAgent
from .correlation import CorrelationAgent
from .historical_analog import HistoricalAnalogAgent
from .gold_analysis import GoldAnalysisAgent
from .bitcoin_analysis import BitcoinAnalysisAgent
from .scenario import ScenarioAgent
from .risk import RiskAgent
from .trade_recommendation import TradeRecommendationAgent
from .learning import LearningAgent

__all__ = [
    "AnalysisContext",
    "BaseAgent",
    "NewsIntelligenceAgent",
    "EconomicCalendarAgent",
    "GeopoliticalAgent",
    "MonetaryPolicyAgent",
    "LiquidityAgent",
    "OnChainAgent",
    "DerivativesEtfAgent",
    "CorrelationAgent",
    "HistoricalAnalogAgent",
    "GoldAnalysisAgent",
    "BitcoinAnalysisAgent",
    "ScenarioAgent",
    "RiskAgent",
    "TradeRecommendationAgent",
    "LearningAgent",
]
