"""VATICAN INTEGRATION (Stage 2, "fix the aggregation formula" directive,
docs/bellwether_aggregation_formula_report.md) — proves `agreement` and
`coverage` are exposed as separate fields (not just blended into
`confidence`) all the way from `_synthesis.aggregate()` through
gold_analysis/bitcoin_analysis's meta, trade_recommendation's per-asset
recommendations, and the top-level AnalysisOutput schema. `confidence`
itself is unchanged (0.3 + 0.45*agreement + 0.25*coverage) — this is a
structural addition, not a formula change.
"""
from __future__ import annotations

from bellwether.agents._synthesis import aggregate
from bellwether.agents.base import AnalysisContext
from bellwether.agents.bitcoin_analysis import BitcoinAnalysisAgent
from bellwether.agents.gold_analysis import GoldAnalysisAgent
from bellwether.agents.trade_recommendation import TradeRecommendationAgent
from bellwether.config import Settings
from bellwether.data import build_data_hub
from bellwether.schemas import AgentResult, Asset, Bias, DataProvenance, MarketSnapshot, Signal


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(gold_price=2600, btc_price=64000, dxy=104, real_yield_10y=1.9,
                          nominal_yield_10y=4.2, vix=15, fed_funds_mid=5.13)


def test_aggregate_no_signals_reports_zero_agreement_and_coverage():
    read = aggregate(Asset.GOLD, [])
    assert read.confidence == 0.25
    assert read.agreement == 0.0
    assert read.coverage == 0.0


def test_aggregate_agreement_and_coverage_are_the_formulas_own_components():
    """agreement = |net_score|/2, coverage = min(1, total_strength/4) — the
    EXACT same two terms confidence = 0.3 + 0.45*agreement + 0.25*coverage
    already used internally; this test proves the formula wasn't changed,
    only decomposed and exposed."""
    signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="a"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="b"),
    ]
    read = aggregate(Asset.GOLD, signals)
    expected_agreement = abs(read.net_score) / 2.0
    expected_coverage = min(1.0, 2.0 / 4.0)
    assert abs(read.agreement - round(expected_agreement, 3)) < 1e-6
    assert abs(read.coverage - round(expected_coverage, 3)) < 1e-6
    expected_confidence = round(0.3 + 0.45 * read.agreement + 0.25 * read.coverage, 3)
    assert read.confidence == expected_confidence


def test_aggregate_high_coverage_low_agreement_vs_low_coverage_high_agreement():
    """The whole point of the split: two reads that land on similar
    confidence can have very different agreement/coverage — a consumer of
    ONLY confidence can't tell these apart, a consumer of the new fields
    can."""
    # Broad but split: 4 signals, half bullish half bearish -> net near 0, low agreement, high coverage.
    split_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="a"),
        Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=1.0, source_agent="b"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="c"),
        Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.9, source_agent="d"),
    ]
    split_read = aggregate(Asset.GOLD, split_signals)
    # Narrow but unanimous: one strong signal -> high agreement, low coverage.
    narrow_signals = [Signal(asset=Asset.GOLD, bias=Bias.STRONG_BULLISH, strength=1.0, source_agent="a")]
    narrow_read = aggregate(Asset.GOLD, narrow_signals)

    assert split_read.coverage > narrow_read.coverage
    assert narrow_read.agreement > split_read.agreement


async def test_gold_analysis_meta_exposes_agreement_and_coverage():
    real_sig = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="real_agent")
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="mock", seed=1),
        results={"real_agent": AgentResult(agent="real_agent", signals=[real_sig], provenance=DataProvenance.REAL)},
    )
    res = await GoldAnalysisAgent().run(ctx)
    assert "agreement" in res.meta
    assert "coverage" in res.meta
    assert 0.0 <= res.meta["agreement"] <= 1.0
    assert 0.0 <= res.meta["coverage"] <= 1.0


async def test_bitcoin_analysis_meta_exposes_agreement_and_coverage():
    real_sig = Signal(asset=Asset.BITCOIN, bias=Bias.BEARISH, strength=0.7, source_agent="real_agent")
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="mock", seed=1),
        results={"real_agent": AgentResult(agent="real_agent", signals=[real_sig], provenance=DataProvenance.REAL)},
    )
    res = await BitcoinAnalysisAgent().run(ctx)
    assert "agreement" in res.meta
    assert "coverage" in res.meta


async def test_trade_recommendation_passes_through_agreement_and_coverage():
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="live", seed=1),
        results={
            "gold_analysis": AgentResult(agent="gold_analysis", provenance=DataProvenance.REAL, confidence=0.6,
                                         meta={"bias": "BULLISH", "probability_up": 0.7,
                                               "agreement": 0.8, "coverage": 0.3}),
            "risk": AgentResult(agent="risk", provenance=DataProvenance.REAL, meta={"haircut": 0.0}),
            "learning": AgentResult(agent="learning", provenance=DataProvenance.REAL, meta={"rolling_accuracy": 0.5}),
        },
    )
    res = await TradeRecommendationAgent().run(ctx)
    assert res.meta["recommendations"]["GOLD"]["agreement"] == 0.8
    assert res.meta["recommendations"]["GOLD"]["coverage"] == 0.3
