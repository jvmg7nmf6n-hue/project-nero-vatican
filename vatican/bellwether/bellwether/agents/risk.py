"""Module 13 — Risk Engine.

Independent skeptic. Flags reasons to distrust the call: internal signal
disagreement, crowded positioning/leverage, imminent high-impact catalysts, and
elevated volatility. Produces a list of risks and a confidence *haircut* the
trade engine must apply.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, DataProvenance, RiskFlag
from ._synthesis import combined_provenance, real_only_signals, weakest_provenance
from .base import AnalysisContext, BaseAgent


class RiskAgent(BaseAgent):
    name = "risk"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        # VATICAN INTEGRATION (Stage 2, "close the provenance leak"
        # directive): in live mode every check below only fires from
        # real/mixed-provenance data — a check whose OWN provider has no
        # real implementation yet (derivatives, on-chain, calendar; VIX
        # until it's wired) is skipped entirely rather than silently
        # computed from the mock draw and folded into a haircut that then
        # gets applied on top of a real read. Mock mode (default) is
        # UNCHANGED — every check runs exactly as before.
        live = ctx.settings.data_mode == "live"
        flags: list[RiskFlag] = []
        haircut = 0.0
        contributing_provenances: list[DataProvenance] = []

        # 1) Signal disagreement per asset.
        for asset in (Asset.GOLD, Asset.BITCOIN):
            asset_signals = real_only_signals(ctx, asset) if live else ctx.all_signals(asset)
            sigs = [s for s in asset_signals if s.bias != Bias.NEUTRAL]
            if live and asset_signals:
                contributing_provenances.append(combined_provenance(ctx, asset_signals))
            if len(sigs) >= 3:
                bulls = sum(1 for s in sigs if s.bias.score > 0)
                bears = sum(1 for s in sigs if s.bias.score < 0)
                if bulls and bears and min(bulls, bears) / (bulls + bears) > 0.35:
                    sev = min(1.0, min(bulls, bears) / (bulls + bears) + 0.2)
                    flags.append(RiskFlag(label=f"{asset.value} signal conflict",
                                          severity=sev,
                                          detail=f"{bulls} bullish vs {bears} bearish drivers"))
                    haircut += 0.1

        # 2a) Crowded leverage from derivatives. VATICAN INTEGRATION
        # (Stage 2, Part B): btc_perp_funding_bps is now real in live mode
        # (VaticanRealDerivatives) -- gated on ITS OWN field provenance,
        # same pattern as the VIX check below (4), not on data_mode. Runs
        # unconditionally in mock mode (unchanged), and in live mode only
        # once the fetch actually succeeded this cycle.
        d = ctx.data.derivatives.metrics()
        funding_provenance = ctx.data.derivatives.provenance_of("btc_perp_funding_bps")
        if (not live) or funding_provenance in (DataProvenance.REAL, DataProvenance.MIXED):
            if d.get("btc_perp_funding_bps", 0) > 6:
                flags.append(RiskFlag(label="BTC leverage crowded", severity=0.6,
                                      detail=f"perp funding {d['btc_perp_funding_bps']:+.1f} bps"))
                haircut += 0.08
            if live:
                contributing_provenances.append(funding_provenance)

        # 2b) On-chain valuation froth. No live OnChainProvider exists yet
        # (see build_data_hub) -- MVRV-Z is ALWAYS mock today in both data
        # modes, so this check is skipped entirely in live mode rather than
        # computed from a value that can never currently be real.
        if not live:
            mvrv = ctx.data.onchain.metrics().get("mvrv_z", 1.0)
            if mvrv > 3.0:
                flags.append(RiskFlag(label="BTC valuation hot", severity=0.5,
                                      detail=f"MVRV-Z {mvrv:.2f} (>3 historically frothy)"))
                haircut += 0.05

        # 3) Imminent catalysts within ~3 days. economic_calendar has no
        # live provider yet either (MockCalendar in both modes) -- same
        # skip-in-live-mode treatment as (2).
        if not live:
            cal = ctx.result("economic_calendar")
            catalysts = (cal.meta.get("catalysts", []) if cal else [])
            soon = [c for c in catalysts if "FOMC" in c["name"] or "CPI" in c["name"] or "NFP" in c["name"]]
            if soon:
                flags.append(RiskFlag(label="High-impact catalyst ahead", severity=0.55,
                                      detail=", ".join(c["name"] for c in soon[:3])))
                haircut += 0.1

        # 4) Vol regime -- gated on VIX's OWN field provenance (currently
        # always synthetic; this becomes live automatically once VIX is
        # wired, no further change needed here).
        vix_provenance = ctx.market.provenance_of("vix")
        if (not live) or vix_provenance in (DataProvenance.REAL, DataProvenance.MIXED):
            if ctx.market.vix > 25:
                flags.append(RiskFlag(label="Elevated volatility regime", severity=0.5,
                                      detail=f"VIX {ctx.market.vix:.1f}"))
                haircut += 0.05
            if live:
                contributing_provenances.append(vix_provenance)

        haircut = round(min(0.5, haircut), 3)
        provenance = weakest_provenance(contributing_provenances) if live else DataProvenance.SYNTHETIC
        return self.result(
            risks=[f"{f.label}: {f.detail}" for f in flags],
            confidence=0.6,
            provenance=provenance,
            meta={"haircut": haircut, "flags": [f.model_dump() for f in flags]},
        )
