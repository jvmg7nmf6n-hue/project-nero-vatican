"""Module 9 — ETF / Derivatives Analytics.

Spot-ETF flows are a clean institutional demand proxy for both assets. Futures
open interest, perp funding, options skew and managed-money positioning describe
how leveraged and which way the crowd is leaning.
"""
from __future__ import annotations

from ..schemas import AgentResult, Asset, Bias, Category, Signal
from .base import AnalysisContext, BaseAgent


class DerivativesEtfAgent(BaseAgent):
    name = "derivatives_etf"

    async def run(self, ctx: AnalysisContext) -> AgentResult:
        flows = ctx.data.etf.flows()
        d = ctx.data.derivatives.metrics()

        btc_flow = flows.get("btc_spot_etf_flow_musd", 0.0)
        gold_flow = flows.get("gold_etf_flow_musd", 0.0)
        funding = d.get("btc_perp_funding_bps", 0.0)
        skew = d.get("btc_25d_skew", 0.0)              # >0 puts bid = fear
        oi_chg = d.get("btc_oi_chg_pct", 0.0)
        gold_net_long = d.get("gold_mgr_net_long_pct", 50.0)

        # Bitcoin: flows bullish; very high funding = crowded long (fade a bit); put skew = fear.
        btc_score = btc_flow / 400.0
        if funding > 6:
            btc_score -= 0.5                   # overheated leverage
        btc_score -= skew / 12.0               # fear discount
        # Gold: ETF flows + positioning extremes.
        gold_score = gold_flow / 300.0 + (gold_net_long - 50.0) / 40.0

        signals = [
            Signal(asset=Asset.BITCOIN, bias=Bias.from_score(btc_score),
                   strength=min(1.0, abs(btc_score) / 2 + 0.2), category=Category.ETF_FLOWS,
                   is_fact=True, source_agent=self.name,
                   rationale=(f"spot-ETF {btc_flow:+.0f}M, funding {funding:+.1f}bps, "
                              f"25d skew {skew:+.1f}, OI {oi_chg:+.1f}%")),
            Signal(asset=Asset.GOLD, bias=Bias.from_score(gold_score),
                   strength=min(1.0, abs(gold_score) / 2 + 0.15), category=Category.ETF_FLOWS,
                   is_fact=True, source_agent=self.name,
                   rationale=f"gold-ETF {gold_flow:+.0f}M, mgr net-long {gold_net_long:.0f}%"),
        ]
        facts = [
            f"BTC spot-ETF flow: {btc_flow:+.0f} M USD",
            f"Gold ETF flow: {gold_flow:+.0f} M USD",
            f"BTC perp funding: {funding:+.1f} bps; 25d skew: {skew:+.1f}",
        ]
        return self.result(signals=signals, facts=facts, confidence=0.62)
