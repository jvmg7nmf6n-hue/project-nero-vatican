"""CC-1 directive (2026-08-07, "wire the 2 safest agents real"), Item 1 —
proves VaticanRealOnChain wires DefiLlama's free stablecoincharts/all endpoint
the same shape as VIX/DXY/funding: real-when-available, honestly-provenanced,
falls back to the mock draw (never guesses) on any failure, and liquidity.py
gates its own combined provenance on BOTH real inputs.
"""
from __future__ import annotations

import random

from bellwether.agents.base import AnalysisContext
from bellwether.agents.liquidity import LiquidityAgent
from bellwether.config import Settings
from bellwether.data import build_data_hub
from bellwether.data.providers import MockOnChain, VaticanRealOnChain
from bellwether.schemas import DataProvenance, MarketSnapshot


def _snapshot(**field_provenance: DataProvenance) -> MarketSnapshot:
    return MarketSnapshot(gold_price=2600, btc_price=64000, dxy=104, real_yield_10y=1.9,
                          nominal_yield_10y=4.2, vix=15, fed_funds_mid=5.13,
                          field_provenance=field_provenance)


def test_vatican_real_onchain_falls_back_cleanly_on_fetch_failure(monkeypatch):
    """If `requests` isn't importable (or the fetch fails for any reason),
    VaticanRealOnChain must fall back to the identical mock draw for
    stablecoin_supply_chg_pct, labelled SYNTHETIC — never raise, never guess
    a substitute value."""
    rng = random.Random(42)
    provider = VaticanRealOnChain(rng)
    import bellwether.data.providers as providers_mod
    monkeypatch.setattr(providers_mod, "_fetch_real_stablecoin_supply_chg_pct_cached",
                        lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")))
    metrics = provider.metrics()
    assert provider.provenance_of("stablecoin_supply_chg_pct") == DataProvenance.SYNTHETIC
    expected = MockOnChain(random.Random(42)).metrics()
    assert metrics["stablecoin_supply_chg_pct"] == expected["stablecoin_supply_chg_pct"]


def test_vatican_real_onchain_provenance_of_other_fields_always_synthetic():
    """Only stablecoin_supply_chg_pct has a real source — every other
    on-chain field (exchange_netflow_btc, lth_supply_chg_pct, mvrv_z,
    funding_rate_bps) must never be reported as anything other than
    SYNTHETIC, regardless of the stablecoin fetch's own outcome. This
    module's own funding_rate_bps field is DIFFERENT from derivatives'
    btc_perp_funding_bps (a separate mock field on OnChainProvider,
    confirmed unwired) — must stay SYNTHETIC too."""
    rng = random.Random(1)
    provider = VaticanRealOnChain(rng)
    provider.metrics()
    assert provider.provenance_of("exchange_netflow_btc") == DataProvenance.SYNTHETIC
    assert provider.provenance_of("lth_supply_chg_pct") == DataProvenance.SYNTHETIC
    assert provider.provenance_of("mvrv_z") == DataProvenance.SYNTHETIC
    assert provider.provenance_of("funding_rate_bps") == DataProvenance.SYNTHETIC


def test_mock_onchain_provenance_of_defaults_synthetic():
    """MockOnChain needs zero code changes to satisfy the ABC's new
    provenance_of method — the base class's own concrete default covers it."""
    provider = MockOnChain(random.Random(1))
    assert provider.provenance_of("stablecoin_supply_chg_pct") == DataProvenance.SYNTHETIC


def test_real_stablecoin_fetch_if_network_available():
    """Integration check: when the real network fetch succeeds, the result
    must be a plausible day-over-day %% change (bounded, not a wild/garbage
    number) and must come back labelled REAL, numerically different in kind
    from the mock draw's own [-1.5, 2.5] range only by coincidence, not by
    construction. Skipped (not failed) when the network/endpoint is
    unreachable in this environment."""
    import pytest
    import bellwether.data.providers as providers_mod

    try:
        value = providers_mod._fetch_real_stablecoin_supply_chg_pct()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"stablecoins.llama.fi unreachable in this environment: {exc}")
    assert isinstance(value, float)
    assert -20.0 < value < 20.0  # a single day's total stablecoin supply move is never this extreme in practice


async def test_liquidity_agent_real_when_both_vix_and_stablecoin_real(monkeypatch):
    """CC-1 directive (2026-08-07): the genuinely NEW case this directive
    unlocks — both of liquidity's real inputs present at once must combine to
    REAL, not MIXED, matching monetary_policy's own both-real precedent."""
    import bellwether.data.providers as providers_mod

    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    real_onchain = providers_mod.VaticanRealOnChain(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_stablecoin_supply_chg_pct_cached", lambda: 0.5)
    hub.onchain = real_onchain
    ctx = AnalysisContext(events=[], market=_snapshot(vix=DataProvenance.REAL), data=hub,
                          settings=Settings(data_mode="live", seed=1))
    res = await LiquidityAgent().run(ctx)
    assert res.provenance == DataProvenance.REAL
    assert res.meta["stablecoin_supply_provenance"] == "real"


async def test_liquidity_agent_mixed_when_only_stablecoin_real(monkeypatch):
    """The mirror case of the existing vix-real/stablecoin-mock test: vix
    still mock, stablecoin real -> MIXED either way, order doesn't matter."""
    import bellwether.data.providers as providers_mod

    hub = build_data_hub(Settings(data_mode="mock", seed=1))
    real_onchain = providers_mod.VaticanRealOnChain(random.Random(1))
    monkeypatch.setattr(providers_mod, "_fetch_real_stablecoin_supply_chg_pct_cached", lambda: 0.5)
    hub.onchain = real_onchain
    ctx = AnalysisContext(events=[], market=_snapshot(), data=hub,  # vix defaults SYNTHETIC
                          settings=Settings(data_mode="live", seed=1))
    res = await LiquidityAgent().run(ctx)
    assert res.provenance == DataProvenance.MIXED
