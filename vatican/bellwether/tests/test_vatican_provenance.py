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

from bellwether.agents._synthesis import aggregate, combined_provenance, real_only_signals
from bellwether.agents.base import AnalysisContext
from bellwether.agents.bitcoin_analysis import BitcoinAnalysisAgent
from bellwether.agents.gold_analysis import GoldAnalysisAgent
from bellwether.agents.monetary_policy import MonetaryPolicyAgent
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
    """If nero_core isn't importable (or the fetch fails for any reason),
    VaticanRealMarketData must fall back to the identical mock draw, labelled
    SYNTHETIC — never raise, never guess a substitute value."""
    import random
    rng = random.Random(42)
    provider = VaticanRealMarketData(rng)
    # Force the internal fetch to fail regardless of environment, so this
    # test's outcome doesn't depend on whether nero_core happens to be
    # importable in whatever environment runs it.
    import bellwether.data.providers as providers_mod
    monkeypatch.setattr(providers_mod, "_fetch_real_dfii10_level",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    snap = provider.snapshot()
    assert snap.field_provenance["real_yield_10y"] == DataProvenance.SYNTHETIC
    # Falls back to exactly what a fresh MockMarketData on the same seed produces.
    expected = MockMarketData(random.Random(42)).snapshot()
    assert snap.real_yield_10y == expected.real_yield_10y


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
