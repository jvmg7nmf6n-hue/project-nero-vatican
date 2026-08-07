"""VATICAN INTEGRATION (Stage 2, Part B — BTC funding rate) — proves
VaticanRealDerivatives wires `nero_core.data_sources.funding_data` the same
shape as VIX/DXY: real-when-available, honestly-provenanced, falls back to
the mock draw (never guesses) on any failure, and derivatives_etf/risk gate
on that provenance rather than on data_mode alone.
"""
from __future__ import annotations

import random

from bellwether.agents.base import AnalysisContext
from bellwether.agents.derivatives_etf import DerivativesEtfAgent
from bellwether.agents.risk import RiskAgent
from bellwether.config import Settings
from bellwether.data import build_data_hub
from bellwether.data.providers import MockDerivatives, VaticanRealDerivatives
from bellwether.schemas import DataProvenance, MarketSnapshot


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(gold_price=2600, btc_price=64000, dxy=104, real_yield_10y=1.9,
                          nominal_yield_10y=4.2, vix=15, fed_funds_mid=5.13)


def test_vatican_real_derivatives_falls_back_cleanly_on_fetch_failure(monkeypatch):
    """If nero_core isn't importable (or the fetch fails for any reason),
    VaticanRealDerivatives must fall back to the identical mock draw for
    btc_perp_funding_bps, labelled SYNTHETIC — never raise, never guess."""
    rng = random.Random(42)
    provider = VaticanRealDerivatives(rng)
    import bellwether.data.providers as providers_mod
    monkeypatch.setattr(providers_mod, "_fetch_real_btc_funding_bps_cached",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    metrics = provider.metrics()
    assert provider.provenance_of("btc_perp_funding_bps") == DataProvenance.SYNTHETIC
    expected = MockDerivatives(random.Random(42)).metrics()
    assert metrics["btc_perp_funding_bps"] == expected["btc_perp_funding_bps"]


def test_vatican_real_derivatives_provenance_of_other_fields_always_synthetic():
    """Only btc_perp_funding_bps has a real source — every other derivatives
    field (btc_25d_skew, gold_mgr_net_long_pct, etc.) must never be reported
    as anything other than SYNTHETIC, regardless of the funding fetch's own
    outcome."""
    rng = random.Random(1)
    provider = VaticanRealDerivatives(rng)
    provider.metrics()
    assert provider.provenance_of("btc_25d_skew") == DataProvenance.SYNTHETIC
    assert provider.provenance_of("gold_mgr_net_long_pct") == DataProvenance.SYNTHETIC


def test_mock_derivatives_provenance_of_defaults_synthetic():
    """MockDerivatives needs zero code changes to satisfy the ABC's new
    provenance_of method — the base class's own concrete default covers it."""
    provider = MockDerivatives(random.Random(1))
    assert provider.provenance_of("btc_perp_funding_bps") == DataProvenance.SYNTHETIC


async def test_derivatives_etf_agent_mixed_when_funding_real(monkeypatch):
    hub = build_data_hub(Settings(data_mode="mock", seed=1))  # onchain/etf/calendar still needed by ctx
    import bellwether.data.providers as providers_mod
    real_deriv = providers_mod.VaticanRealDerivatives(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_btc_funding_bps_cached", lambda: 3.5)
    hub.derivatives = real_deriv
    ctx = AnalysisContext(events=[], market=_snapshot(), data=hub, settings=Settings(data_mode="live", seed=1))
    res = await DerivativesEtfAgent().run(ctx)
    assert res.provenance == DataProvenance.MIXED
    assert res.meta["btc_perp_funding_bps_provenance"] == "real"


async def test_derivatives_etf_agent_synthetic_when_funding_fetch_fails(monkeypatch):
    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    import bellwether.data.providers as providers_mod
    real_deriv = providers_mod.VaticanRealDerivatives(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_btc_funding_bps_cached",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    hub.derivatives = real_deriv
    ctx = AnalysisContext(events=[], market=_snapshot(), data=hub, settings=Settings(data_mode="live", seed=1))
    res = await DerivativesEtfAgent().run(ctx)
    assert res.provenance == DataProvenance.SYNTHETIC


async def test_risk_agent_funding_check_gated_on_real_provenance_in_live_mode(monkeypatch):
    """Crowded-leverage flag must fire in live mode once funding is real and
    extreme, but NOT while it's still a synthetic fallback -- the same
    provenance-gating discipline as the VIX check."""
    import bellwether.data.providers as providers_mod

    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    real_deriv = providers_mod.VaticanRealDerivatives(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_btc_funding_bps_cached", lambda: 50.0)
    hub.derivatives = real_deriv
    ctx = AnalysisContext(events=[], market=_snapshot(), data=hub, settings=Settings(data_mode="live", seed=1))
    res = await RiskAgent().run(ctx)
    assert any("leverage" in r.lower() for r in res.risks)

    hub2 = build_data_hub(Settings(data_mode="mock", seed=1))
    real_deriv2 = providers_mod.VaticanRealDerivatives(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_btc_funding_bps_cached",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    hub2.derivatives = real_deriv2
    hub2.derivatives._mock.metrics = lambda: {"btc_perp_funding_bps": 50.0, "btc_oi_chg_pct": 0.0,
                                              "btc_25d_skew": 0.0, "gold_futures_oi_chg_pct": 0.0,
                                              "gold_mgr_net_long_pct": 50.0}
    ctx2 = AnalysisContext(events=[], market=_snapshot(), data=hub2, settings=Settings(data_mode="live", seed=1))
    res2 = await RiskAgent().run(ctx2)
    assert res2.risks == []
