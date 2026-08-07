"""CC-1 directive (2026-08-07, "fix news_intelligence/geopolitical
provenance") -- proves news_intelligence.py/geopolitical.py now set their
own signal provenance from the real MacroEvent.provenance each ingested
event carries (set by nero_core.execution.bellwether_overlay
.build_real_macro_events for a genuine live RSS match), rather than always
reporting the SYNTHETIC default regardless of input. Both the LLM-unavailable
heuristic path (the one exercised in this test environment, no API key
configured) and the empty/irrelevant-events UNAVAILABLE case are covered.
"""
from __future__ import annotations

from bellwether.agents.base import AnalysisContext
from bellwether.agents.geopolitical import GeopoliticalAgent
from bellwether.agents.news_intelligence import NewsIntelligenceAgent
from bellwether.config import Settings
from bellwether.data import build_data_hub
from bellwether.schemas import Category, DataProvenance, MacroEvent, MarketSnapshot


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(gold_price=2600, btc_price=64000, dxy=104, real_yield_10y=1.9,
                          nominal_yield_10y=4.2, vix=15, fed_funds_mid=5.13)


def _ctx(events: list[MacroEvent]) -> AnalysisContext:
    return AnalysisContext(events=events, market=_snapshot(),
                           data=build_data_hub(Settings(data_mode="mock", seed=1)),
                           settings=Settings(data_mode="live", seed=1))


def test_macro_event_defaults_to_synthetic_provenance():
    """The schema-level default -- tools/sweep.py's own hand-authored
    scenario headlines and the FastAPI /analyze route's caller-supplied
    events correctly stay on this default, unaffected by this directive."""
    event = MacroEvent(headline="Some headline")
    assert event.provenance == DataProvenance.SYNTHETIC


async def test_news_intelligence_unavailable_when_no_events():
    ctx = _ctx([])
    res = await NewsIntelligenceAgent().run(ctx)
    assert res.provenance == DataProvenance.UNAVAILABLE


async def test_news_intelligence_real_when_events_are_real():
    events = [MacroEvent(headline="Fed signals rate cut amid cooling inflation",
                         provenance=DataProvenance.REAL)]
    ctx = _ctx(events)
    res = await NewsIntelligenceAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL
    # Not just the label -- a real signal must actually have been produced
    # from the real headline text (heuristic path, no API key in this env).
    assert len(res.signals) > 0


async def test_news_intelligence_synthetic_when_events_are_synthetic():
    events = [MacroEvent(headline="Fed signals rate cut amid cooling inflation")]  # default SYNTHETIC
    ctx = _ctx(events)
    res = await NewsIntelligenceAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC


async def test_news_intelligence_mixed_when_events_are_mixed():
    events = [
        MacroEvent(headline="Fed signals rate cut amid cooling inflation", provenance=DataProvenance.REAL),
        MacroEvent(headline="Some other synthetic headline"),  # default SYNTHETIC
    ]
    ctx = _ctx(events)
    res = await NewsIntelligenceAgent().run(ctx)
    assert res.provenance == DataProvenance.MIXED


async def test_news_intelligence_provenance_recomputed_fresh_each_call():
    """CC-1 directive item 1c: no stale caching across cycles -- a REAL
    cycle followed by an empty (fetch-failed) cycle must correctly degrade,
    never stay stuck on the prior cycle's REAL label."""
    agent = NewsIntelligenceAgent()
    real_ctx = _ctx([MacroEvent(headline="Fed signals rate cut", provenance=DataProvenance.REAL)])
    res1 = await agent.run(real_ctx)
    assert res1.provenance == DataProvenance.REAL

    empty_ctx = _ctx([])
    res2 = await agent.run(empty_ctx)
    assert res2.provenance == DataProvenance.UNAVAILABLE


async def test_geopolitical_unavailable_when_no_events():
    ctx = _ctx([])
    res = await GeopoliticalAgent().run(ctx)
    assert res.provenance == DataProvenance.UNAVAILABLE


async def test_geopolitical_unavailable_when_events_exist_but_none_are_geopolitically_relevant():
    """geopolitical.py filters ctx.events down to geo_events -- a REAL event
    that isn't geopolitically relevant must not make this agent REAL; it
    correctly has nothing to consume."""
    events = [MacroEvent(headline="Gold ETF inflows accelerate this week",
                         category=Category.ETF_FLOWS, provenance=DataProvenance.REAL)]
    ctx = _ctx(events)
    res = await GeopoliticalAgent().run(ctx)
    assert res.provenance == DataProvenance.UNAVAILABLE


async def test_geopolitical_real_when_relevant_events_are_real():
    events = [MacroEvent(headline="War escalates as missile strike hits key region",
                         category=Category.GEOPOLITICS, provenance=DataProvenance.REAL)]
    ctx = _ctx(events)
    res = await GeopoliticalAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL
    assert len(res.signals) > 0


async def test_geopolitical_synthetic_when_relevant_events_are_synthetic():
    events = [MacroEvent(headline="War escalates as missile strike hits key region",
                         category=Category.GEOPOLITICS)]  # default SYNTHETIC
    ctx = _ctx(events)
    res = await GeopoliticalAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC


async def test_geopolitical_ignores_irrelevant_real_events_when_computing_provenance():
    """A mix of one relevant REAL event and one irrelevant REAL event must
    still report REAL (both would combine to REAL anyway here), but this
    proves geo_events -- not the full ctx.events -- is what's measured: a
    third, irrelevant SYNTHETIC event must NOT drag this down to MIXED."""
    events = [
        MacroEvent(headline="War escalates as missile strike hits key region",
                  category=Category.GEOPOLITICS, provenance=DataProvenance.REAL),
        MacroEvent(headline="Gold ETF inflows accelerate this week",
                  category=Category.ETF_FLOWS),  # irrelevant, SYNTHETIC, must be excluded from the combination
    ]
    ctx = _ctx(events)
    res = await GeopoliticalAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL
