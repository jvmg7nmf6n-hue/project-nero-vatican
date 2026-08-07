import pytest

from bellwether.agents import (
    MonetaryPolicyAgent, LiquidityAgent, OnChainAgent, DerivativesEtfAgent,
    EconomicCalendarAgent, AnalysisContext,
)
from bellwether.config import Settings
from bellwether.data import build_data_hub
from bellwether.schemas import Asset


@pytest.fixture
def ctx():
    s = Settings(data_mode="mock", seed=11)
    hub = build_data_hub(s)
    return AnalysisContext(events=[], market=hub.market.snapshot(), data=hub, settings=s)


async def test_monetary_agent_emits_both_assets(ctx):
    res = await MonetaryPolicyAgent().run(ctx)
    assets = {s.asset for s in res.signals}
    assert Asset.GOLD in assets and Asset.BITCOIN in assets
    assert res.facts


async def test_liquidity_agent(ctx):
    res = await LiquidityAgent().run(ctx)
    assert res.signals
    assert 0 <= res.confidence <= 1


async def test_onchain_agent_btc_only(ctx):
    res = await OnChainAgent().run(ctx)
    assert all(s.asset == Asset.BITCOIN for s in res.signals)


async def test_derivatives_agent(ctx):
    res = await DerivativesEtfAgent().run(ctx)
    assert {s.asset for s in res.signals} == {Asset.GOLD, Asset.BITCOIN}


async def test_calendar_agent_has_catalysts(ctx):
    res = await EconomicCalendarAgent().run(ctx)
    assert "catalysts" in res.meta
    assert isinstance(res.meta["catalysts"], list)
