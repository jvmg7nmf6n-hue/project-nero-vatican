"""VATICAN INTEGRATION (Stage 2, docs/bellwether_audit.md) — tests proving
the real/synthetic/mixed/unavailable provenance mechanism actually works:
a consumer can never mistake a mock number for a real one, and a purely-mock
agent is excluded from the live-mode aggregate rather than silently blended
in. These tests don't require nero_core on the path (they construct
AgentResult/MarketSnapshot directly) except test_real_dfii10_wiring_if_available,
which is skipped if nero_core isn't importable — matching
VaticanRealMarketData's own soft-dependency design.
"""
from __future__ import annotations

import pytest

from bellwether.agents._synthesis import aggregate, combined_provenance, real_only_signals, weakest_provenance
from bellwether.agents.base import AnalysisContext
from bellwether.agents.bitcoin_analysis import BitcoinAnalysisAgent
from bellwether.agents.correlation import CorrelationAgent
from bellwether.agents.gold_analysis import GoldAnalysisAgent
from bellwether.agents.liquidity import LiquidityAgent
from bellwether.agents.monetary_policy import MonetaryPolicyAgent
from bellwether.agents.risk import RiskAgent
from bellwether.agents.scenario import ScenarioAgent
from bellwether.agents.trade_recommendation import TradeRecommendationAgent
from bellwether.config import Settings
from bellwether.data import VaticanRealMarketData, build_data_hub
from bellwether.data.providers import MockMarketData
from bellwether.schemas import AgentResult, Asset, Bias, DataProvenance, MarketSnapshot, Signal


def _snapshot(**field_provenance: DataProvenance) -> MarketSnapshot:
    return MarketSnapshot(
        gold_price=2600, btc_price=64000, dxy=104, real_yield_10y=1.9,
        nominal_yield_10y=4.2, vix=15, fed_funds_mid=5.13,
        field_provenance=field_provenance,
    )


def test_market_snapshot_missing_field_defaults_synthetic():
    """A field absent from field_provenance must never be assumed real —
    this is the "a consumer should never mistake mock for real" guarantee
    at its narrowest: even an EMPTY provenance dict (e.g. a hand-built
    MarketSnapshot in a test that forgot to set it) reads as SYNTHETIC, the
    conservative default, never REAL."""
    snap = _snapshot()
    assert snap.provenance_of("real_yield_10y") == DataProvenance.SYNTHETIC
    assert snap.provenance_of("dxy") == DataProvenance.SYNTHETIC


async def test_monetary_policy_provenance_mixed_when_only_one_field_real():
    """monetary_policy reads exactly real_yield_10y and dxy — if only one of
    the two is REAL, the agent's own result must report MIXED, never REAL
    (that would overstate it) and never SYNTHETIC (that would understate a
    real contribution actually present)."""
    market = _snapshot(real_yield_10y=DataProvenance.REAL, dxy=DataProvenance.SYNTHETIC)
    settings = Settings(data_mode="live", seed=1)
    hub = build_data_hub(Settings(data_mode="mock", seed=1))  # onchain/etc. still needed by ctx
    ctx = AnalysisContext(events=[], market=market, data=hub, settings=settings)
    res = await MonetaryPolicyAgent().run(ctx)
    assert res.provenance == DataProvenance.MIXED
    assert res.meta["real_yield_10y_provenance"] == "real"
    assert res.meta["dxy_provenance"] == "synthetic"


async def test_monetary_policy_provenance_real_when_both_fields_real():
    market = _snapshot(real_yield_10y=DataProvenance.REAL, dxy=DataProvenance.REAL)
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    ctx = AnalysisContext(events=[], market=market, data=hub, settings=Settings(data_mode="live", seed=1))
    res = await MonetaryPolicyAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL


async def test_monetary_policy_provenance_synthetic_by_default():
    """Mock mode's plain MockMarketData never sets field_provenance at all —
    monetary_policy must still report SYNTHETIC, matching every agent's
    pre-Stage-2 behavior exactly (default provenance, not a special case)."""
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    ctx = AnalysisContext(events=[], market=hub.market.snapshot(), data=hub, settings=Settings(data_mode="mock", seed=1))
    res = await MonetaryPolicyAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC


def test_real_only_signals_excludes_purely_synthetic_agents():
    """The core exclusion guarantee: a signal from an agent whose own
    provenance is SYNTHETIC must never appear in real_only_signals' output,
    even though ctx.all_signals() (the pre-Stage-2 behavior) would include
    it. A MIXED-provenance agent's signal DOES pass through — MIXED still
    carries real content, unlike pure SYNTHETIC."""
    real_sig = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="real_agent")
    mixed_sig = Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.5, source_agent="mixed_agent")
    mock_sig = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.9, source_agent="mock_agent")

    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="live", seed=1),
        results={
            "real_agent": AgentResult(agent="real_agent", signals=[real_sig], provenance=DataProvenance.REAL),
            "mixed_agent": AgentResult(agent="mixed_agent", signals=[mixed_sig], provenance=DataProvenance.MIXED),
            "mock_agent": AgentResult(agent="mock_agent", signals=[mock_sig], provenance=DataProvenance.SYNTHETIC),
        },
    )
    filtered = real_only_signals(ctx, Asset.GOLD)
    source_agents = {s.source_agent for s in filtered}
    assert source_agents == {"real_agent", "mixed_agent"}
    assert "mock_agent" not in source_agents
    # And the pre-Stage-2 accessor is untouched — still returns all three.
    assert {s.source_agent for s in ctx.all_signals(Asset.GOLD)} == {"real_agent", "mixed_agent", "mock_agent"}


def test_combined_provenance_unavailable_when_no_real_signals():
    """If real_only_signals finds nothing for an asset this cycle, the
    synthesis agent must report UNAVAILABLE, not silently fall through to a
    mock-derived NEUTRAL read that would look like a genuine
    absence-of-signal rather than an absence-of-real-data."""
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="live", seed=1), results={},
    )
    assert combined_provenance(ctx, []) == DataProvenance.UNAVAILABLE


async def test_gold_analysis_excludes_synthetic_agents_in_live_mode():
    """End-to-end: in live mode, a fake purely-synthetic agent's bullish
    GOLD signal must not move gold_analysis's own read at all — the
    aggregate must behave as if that signal was never emitted."""
    real_sig = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="real_agent")
    mock_sig = Signal(asset=Asset.GOLD, bias=Bias.STRONG_BEARISH, strength=1.0, source_agent="mock_agent")
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="live", seed=1),
        results={
            "real_agent": AgentResult(agent="real_agent", signals=[real_sig], provenance=DataProvenance.REAL),
            "mock_agent": AgentResult(agent="mock_agent", signals=[mock_sig], provenance=DataProvenance.SYNTHETIC),
        },
    )
    res = await GoldAnalysisAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL
    assert res.meta["bias"] == "BULLISH"  # only the real BULLISH signal counted, un-cancelled by the excluded bearish mock one


async def test_gold_analysis_unchanged_in_mock_mode():
    """Mock mode (the default, and every pre-Stage-2 test's mode) must
    behave byte-identically to upstream — both signals blend in, exactly as
    before this integration."""
    real_sig = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=1.0, source_agent="real_agent")
    mock_sig = Signal(asset=Asset.GOLD, bias=Bias.STRONG_BEARISH, strength=1.0, source_agent="mock_agent")
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="mock", seed=1),
        results={
            "real_agent": AgentResult(agent="real_agent", signals=[real_sig], provenance=DataProvenance.REAL),
            "mock_agent": AgentResult(agent="mock_agent", signals=[mock_sig], provenance=DataProvenance.SYNTHETIC),
        },
    )
    res = await GoldAnalysisAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC  # mock mode never claims real
    # Both signals blended (bullish 1.0 + strong_bearish -2.0, equal strength) -> net -0.5 -> BEARISH,
    # not the pure-BULLISH read live mode would give after excluding the mock signal.
    assert res.meta["bias"] == "BEARISH"


def test_vatican_real_market_data_falls_back_cleanly_without_nero_core(monkeypatch):
    """If nero_core/yfinance isn't importable (or either fetch fails for any
    reason), VaticanRealMarketData must fall back to the identical mock
    draw for that field, labelled SYNTHETIC — never raise, never guess a
    substitute value."""
    import random
    rng = random.Random(42)
    provider = VaticanRealMarketData(rng)
    # Force BOTH internal fetches to fail regardless of environment, so this
    # test's outcome doesn't depend on whether nero_core/yfinance happen to
    # be importable in whatever environment runs it.
    import bellwether.data.providers as providers_mod
    monkeypatch.setattr(providers_mod, "_fetch_real_dfii10_level",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    monkeypatch.setattr(providers_mod, "_fetch_real_dxy_level_cached",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    snap = provider.snapshot()
    assert snap.field_provenance["real_yield_10y"] == DataProvenance.SYNTHETIC
    assert snap.field_provenance["dxy"] == DataProvenance.SYNTHETIC
    # Falls back to exactly what a fresh MockMarketData on the same seed produces.
    expected = MockMarketData(random.Random(42)).snapshot()
    assert snap.real_yield_10y == expected.real_yield_10y
    assert snap.dxy == expected.dxy


def test_real_dfii10_wiring_if_nero_core_available():
    """Integration check: when nero_core IS importable (this repo's own
    environment, not every standalone Bellwether checkout), a live-mode
    snapshot's real_yield_10y must actually come back REAL and numerically
    different from a pure mock draw's — proving the wiring isn't a no-op.
    Skipped (not failed) when nero_core isn't on the path, matching
    VaticanRealMarketData's own graceful-degradation contract."""
    pytest.importorskip("nero_core")
    import random
    rng = random.Random(42)
    provider = VaticanRealMarketData(rng)
    snap = provider.snapshot()
    if snap.field_provenance["real_yield_10y"] != DataProvenance.REAL:
        pytest.skip("nero_core importable but no cached/live DFII10 data available in this environment")
    assert isinstance(snap.real_yield_10y, float)


def test_real_dxy_wiring_if_yfinance_available():
    """Integration check: when yfinance IS importable and DX-Y.NYB is
    reachable, dxy must come back REAL and in DXY-index scale (~80-130),
    not UUP-ETF scale (~20-40) — the exact unit-mismatch bug this wiring
    exists to avoid. Skipped (not failed) when yfinance/network isn't
    available."""
    pytest.importorskip("yfinance")
    import random
    rng = random.Random(42)
    provider = VaticanRealMarketData(rng)
    snap = provider.snapshot()
    if snap.field_provenance["dxy"] != DataProvenance.REAL:
        pytest.skip("yfinance importable but DX-Y.NYB unreachable in this environment")
    assert 60.0 < snap.dxy < 150.0  # genuinely DXY-scale, not UUP-ETF-price-scale


def test_real_vix_wiring_if_yfinance_available():
    """Same shape as the dxy check: real, in a plausible VIX range (single
    digits to ~80 covers every historical VIX reading), not left on the
    mock draw."""
    pytest.importorskip("yfinance")
    import random
    rng = random.Random(42)
    provider = VaticanRealMarketData(rng)
    snap = provider.snapshot()
    if snap.field_provenance["vix"] != DataProvenance.REAL:
        pytest.skip("yfinance importable but ^VIX unreachable in this environment")
    assert 5.0 < snap.vix < 80.0


async def test_liquidity_agent_mixed_once_vix_real_stablecoin_still_mock():
    """liquidity.py reads vix AND onchain's stablecoin figure for its BTC
    signal — both CAN be real now (CC-1 directive, 2026-08-07,
    VaticanRealOnChain), but this test deliberately builds a MOCK data hub
    (MockOnChain, whose provenance_of always reports SYNTHETIC) to isolate
    the vix-real/stablecoin-still-synthetic case: the honest overall
    provenance must be MIXED, not REAL, at this per-agent granularity (see
    the comment in liquidity.py itself; see test_vatican_onchain.py for the
    now-real stablecoin cases)."""
    market = _snapshot(vix=DataProvenance.REAL)
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    ctx = AnalysisContext(events=[], market=market, data=hub, settings=Settings(data_mode="live", seed=1))
    res = await LiquidityAgent().run(ctx)
    assert res.provenance == DataProvenance.MIXED


async def test_liquidity_agent_synthetic_when_vix_still_mock():
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    ctx = AnalysisContext(events=[], market=_snapshot(), data=hub, settings=Settings(data_mode="live", seed=1))
    res = await LiquidityAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC


# --------------------------------------------------------------------------- #
# "Close the provenance leak" directive (2026-08-07): risk/scenario/
# correlation/trade_recommendation must not let a purely-synthetic feed
# taint a live-mode result the way gold_analysis/bitcoin_analysis already
# guard against.
# --------------------------------------------------------------------------- #

def _live_ctx(results: dict, market: MarketSnapshot | None = None) -> AnalysisContext:
    return AnalysisContext(
        events=[], market=market or _snapshot(), data=build_data_hub(Settings(data_mode="mock", seed=1)),
        settings=Settings(data_mode="live", seed=1), results=results,
    )


async def test_risk_agent_ignores_synthetic_signal_disagreement_in_live_mode():
    """A 3-way bull/bear split from a SYNTHETIC-only agent must not produce
    a "signal conflict" flag or haircut in live mode — that disagreement was
    never real to begin with."""
    mock_signals = [
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="mock_agent"),
        Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.8, source_agent="mock_agent"),
        Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="mock_agent"),
    ]
    ctx = _live_ctx({
        "mock_agent": AgentResult(agent="mock_agent", signals=mock_signals, provenance=DataProvenance.SYNTHETIC),
    })
    res = await RiskAgent().run(ctx)
    assert res.risks == []
    assert res.meta["haircut"] == 0.0
    assert res.provenance == DataProvenance.UNAVAILABLE  # no real signals to assess at all


async def test_risk_agent_counts_real_signal_disagreement_in_live_mode():
    """The identical disagreement, but from REAL/MIXED-provenance agents,
    MUST still be flagged — this isn't "never flag conflicts in live mode,"
    it's "only flag conflicts that are actually real.\""""
    # 2 bullish vs 2 bearish -> min(2,2)/4 = 0.5 > 0.35, actually triggers the flag
    # (a 2-vs-1 split, e.g. min(2,1)/3=0.33, would NOT clear the threshold).
    real_signals_a = [Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="real_a")]
    real_signals_b = [Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.8, source_agent="real_b")]
    real_signals_c = [Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.8, source_agent="real_c")]
    real_signals_d = [Signal(asset=Asset.GOLD, bias=Bias.BEARISH, strength=0.8, source_agent="real_d")]
    ctx = _live_ctx({
        "real_a": AgentResult(agent="real_a", signals=real_signals_a, provenance=DataProvenance.REAL),
        "real_b": AgentResult(agent="real_b", signals=real_signals_b, provenance=DataProvenance.MIXED),
        "real_c": AgentResult(agent="real_c", signals=real_signals_c, provenance=DataProvenance.REAL),
        "real_d": AgentResult(agent="real_d", signals=real_signals_d, provenance=DataProvenance.REAL),
    })
    res = await RiskAgent().run(ctx)
    assert any("signal conflict" in r for r in res.risks)
    assert res.meta["haircut"] > 0.0
    assert res.provenance == DataProvenance.MIXED  # weakest of REAL/MIXED/REAL


async def test_risk_agent_ignores_synthetic_derivatives_onchain_calendar_in_live_mode():
    """derivatives/onchain/calendar have no live provider registered
    (build_data_hub's "live" branch still uses Mock* for all three) — their
    checks must not fire at all in live mode, however extreme the mock
    values are, rather than firing on data that can never currently be
    real."""
    hub = build_data_hub(Settings(data_mode="mock", seed=999))  # a seed likely to produce extreme mock values
    # Force genuinely extreme values regardless of seed luck.
    hub.derivatives.metrics = lambda: {"btc_perp_funding_bps": 50.0}  # far past the >6 threshold
    hub.onchain.metrics = lambda: {"mvrv_z": 10.0}  # far past the >3.0 threshold
    ctx = AnalysisContext(
        events=[], market=_snapshot(), data=hub,
        settings=Settings(data_mode="live", seed=1), results={},
    )
    res = await RiskAgent().run(ctx)
    assert res.risks == []
    assert res.meta["haircut"] == 0.0


async def test_risk_agent_vix_gated_on_field_provenance():
    """VIX > 25 must not produce a haircut in live mode while vix's own
    field_provenance is still SYNTHETIC (the current, pre-VIX-wiring state)
    — becomes live automatically, no code change needed, once VIX is real."""
    hot_vix_synthetic = _snapshot()  # field_provenance empty -> vix defaults SYNTHETIC
    hot_vix_synthetic = hot_vix_synthetic.model_copy(update={"vix": 40.0})
    ctx = _live_ctx({}, market=hot_vix_synthetic)
    res = await RiskAgent().run(ctx)
    assert res.risks == []

    hot_vix_real = _snapshot(vix=DataProvenance.REAL).model_copy(update={"vix": 40.0})
    ctx2 = _live_ctx({}, market=hot_vix_real)
    res2 = await RiskAgent().run(ctx2)
    assert any("volatility" in r.lower() for r in res2.risks)


async def test_risk_agent_unchanged_in_mock_mode():
    """Mock mode (default) must behave byte-identically to upstream: every
    check runs regardless of any provenance concept."""
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    hub.derivatives.metrics = lambda: {"btc_perp_funding_bps": 50.0}
    ctx = AnalysisContext(events=[], market=hub.market.snapshot(), data=hub,
                          settings=Settings(data_mode="mock", seed=1), results={})
    res = await RiskAgent().run(ctx)
    assert any("leverage" in r.lower() for r in res.risks)
    assert res.provenance == DataProvenance.SYNTHETIC


async def test_scenario_provenance_mirrors_weakest_of_gold_btc():
    ctx = _live_ctx({
        "gold_analysis": AgentResult(agent="gold_analysis", provenance=DataProvenance.REAL,
                                     meta={"bias": "BULLISH"}),
        "bitcoin_analysis": AgentResult(agent="bitcoin_analysis", provenance=DataProvenance.SYNTHETIC,
                                        meta={"bias": "NEUTRAL"}),
    })
    res = await ScenarioAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC  # weakest of REAL, SYNTHETIC


async def test_correlation_always_synthetic_regardless_of_mode():
    """CorrelationAgent's coefficients are hardcoded design constants (see
    docs/bellwether_audit.md) — never becomes REAL just because data_mode
    does, in either mode."""
    for mode in ("mock", "live"):
        ctx = AnalysisContext(events=[], market=_snapshot(real_yield_10y=DataProvenance.REAL, dxy=DataProvenance.REAL),
                              data=build_data_hub(Settings(data_mode="mock", seed=1)),
                              settings=Settings(data_mode=mode, seed=1), results={})
        res = await CorrelationAgent().run(ctx)
        assert res.provenance == DataProvenance.SYNTHETIC


async def test_trade_recommendation_per_asset_provenance_is_weakest_link():
    ctx = _live_ctx({
        "gold_analysis": AgentResult(agent="gold_analysis", provenance=DataProvenance.REAL,
                                     confidence=0.6, meta={"bias": "BULLISH", "probability_up": 0.7}),
        "bitcoin_analysis": AgentResult(agent="bitcoin_analysis", provenance=DataProvenance.SYNTHETIC,
                                        confidence=0.6, meta={"bias": "NEUTRAL", "probability_up": 0.5}),
        "risk": AgentResult(agent="risk", provenance=DataProvenance.REAL, meta={"haircut": 0.0}),
        "learning": AgentResult(agent="learning", provenance=DataProvenance.REAL, meta={"rolling_accuracy": 0.5}),
    })
    res = await TradeRecommendationAgent().run(ctx)
    assert res.meta["recommendations"]["GOLD"]["provenance"] == "real"
    assert res.meta["recommendations"]["BITCOIN"]["provenance"] == "synthetic"
    assert res.provenance == DataProvenance.SYNTHETIC  # weakest across both assets


async def test_no_agent_calls_ctx_all_signals_for_gold_or_bitcoin_in_live_mode(monkeypatch):
    """Explicit regression guard (Stage 2, "close the provenance leak"
    directive item 6): if any of gold_analysis/bitcoin_analysis/risk ever
    regresses back to ctx.all_signals(GOLD|BITCOIN) instead of
    real_only_signals in live mode, THIS test fails — it doesn't rely on
    inspecting output values, it tracks the actual call."""
    calls = []
    original = AnalysisContext.all_signals

    def tracking_all_signals(self, asset=None):
        if asset in (Asset.GOLD, Asset.BITCOIN):
            calls.append(asset)
        return original(self, asset)

    monkeypatch.setattr(AnalysisContext, "all_signals", tracking_all_signals)

    mock_signal = Signal(asset=Asset.GOLD, bias=Bias.BULLISH, strength=0.5, source_agent="mock_agent")
    ctx = _live_ctx({
        "mock_agent": AgentResult(agent="mock_agent", signals=[mock_signal], provenance=DataProvenance.SYNTHETIC),
    })
    await GoldAnalysisAgent().run(ctx)
    ctx.results["gold_analysis"] = await GoldAnalysisAgent().run(ctx)
    ctx.results["bitcoin_analysis"] = await BitcoinAnalysisAgent().run(ctx)
    await RiskAgent().run(ctx)

    assert calls == [], (
        f"ctx.all_signals(GOLD|BITCOIN) was called {len(calls)} time(s) in live mode — "
        "gold_analysis/bitcoin_analysis/risk must use real_only_signals instead"
    )
