"""Human-editable verification status wording for the public site export
(nero_core.execution.export_site_data). This is the ONE place status strings live —
export logic only ever looks values up here, never hardcodes wording inline, so
updating a strategy's status is a one-line edit here, not a code change to the
exporter itself.

Keyed by (strategy_id, strategy_version, asset) — Replay Machinery Generalization:
originally keyed by (strategy_id, asset) alone, but RANGE_MEAN_REVERSION wires TWO
different registered versions (long-only and confirmation) against the SAME asset
(BTC), which would otherwise silently collide on one shared status string even
though nero_core.execution.export_site_data's own trade-stats keying (strategy_id,
strategy_version, asset) already kept their P&L numbers correctly separate. Adding
strategy_version here closes that gap.
"""
from __future__ import annotations

from nero_core.strategies.pead import TICKERS as _PEAD_TICKERS

# Three New Hypothesis Batch, post-batch promotion list (docs/three_new_
# hypothesis_batch_closing_report.md) -- exact wording as specified in that
# batch's own status strings, never reworded here.
_GOLD_SILVER_RATIO_STATUS = (
    "watchlist — forward-testing, not verified (positive both halves, edge-over-random positive 3/4 configs; "
    "pairs-aware stop; vendor-timestamp fix applied; 1day grid-shift structurally unavailable)"
)
_PEAD_SURVIVED_STATUS = (
    "verified — survivor-bias caveat: tested on 7 large successful companies only; CI entirely positive; "
    "edge-over-random +0.35 to +0.60; real-world performance may differ"
)

VERIFICATION_STATUS: dict[tuple[str, str, str], str] = {
    ("BREAKOUT_MOMENTUM", "breakout-momentum-v1.2.0-gold-calibrated-1week", "GOLD"): "triple-verified",
    ("TREND_PULLBACK", "trend-pullback-v1.0.0", "BNB"): "verified — sample-limited",
    ("COINTEGRATION_PAIRS", "cointegration-pairs-v1.0.0", "BTC-ETH"): "verified — weakest, live-proving",
    ("NEWS_SENTIMENT", "news-sentiment-v1.0.0", "GOLD"): "forward-test-only, no historical backtest",
    ("NEWS_SENTIMENT", "news-sentiment-v1.0.0", "BTC"): "forward-test-only, no historical backtest",
    # Asset Expansion Phase A metals sweep (docs/metals_phase_a_full_sweep.md,
    # docs/metals_grid_shift_verification.md): positive both backtest halves, adequate
    # sample, but grid-shift verification does not apply at 24h and NO Phase A config
    # reached SURVIVED. Wired live at the user's explicit request to accrue forward
    # evidence — must never be worded as "verified".
    ("BREAKOUT_MOMENTUM", "breakout-momentum-v1.6.0-silver-calibrated-24h", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("TREND_PULLBACK", "trend-pullback-v1.5.0-silver-calibrated-24h", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma150-silver-calibrated-24h", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("VOLATILITY_SQUEEZE", "volatility-squeeze-v1.1.0-ma100-silver-calibrated-24h", "SILVER"): "promising-watchlist — forward-testing, not verified",
    # Comprehensive Asset Expansion, Part C: Crypto, Task C1 — order-book depth has no
    # historical replay, so there is literally no backtest to run, not merely one that
    # hasn't been done yet.
    ("ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "BTC"): "experimental — snapshot-based, forward-testing only, no backtest exists",
    ("ORDERFLOW_IMBALANCE", "orderflow-imbalance-v1.0.0", "ETH"): "experimental — snapshot-based, forward-testing only, no backtest exists",
    # Replay Machinery Generalization — RMR watchlist configs unblocked from the prior
    # deferral (docs/live_wiring_batch_rmr_watchlist_deferral.md). Same discipline as
    # the SILVER Phase A rows above: positive-both-halves backtest results exist, but
    # none reached SURVIVED (thin samples, CI crosses zero, grid-shift structurally
    # unavailable at 1d) — wired to accrue live forward evidence, never worded as
    # "verified". See docs/ranging_regime_batch_r1_regime_transition.md and
    # docs/rmr_variant_research_stage1.md for the underlying backtest results.
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "GOLD"):
        "watchlist — forward-testing, not verified (band-timing beat random both halves; N below 20-trade bar)",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.0.0", "SILVER"):
        "watchlist — forward-testing, not verified (band-timing beat random both halves; N below 20-trade bar)",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.1.0-long-only", "BTC"):
        "watchlist — forward-testing, not verified (mechanism-backed, LOW SAMPLE, CI crosses zero, 1d grid-shift structurally unavailable)",
    ("RANGE_MEAN_REVERSION", "range-mean-reversion-v1.3.0-confirmation", "BTC"):
        "watchlist — forward-testing, not verified (68% reversion-target exit rate vs 32% baseline; LOW SAMPLE, CI crosses zero, 1d grid-shift structurally unavailable)",
    # Three New Hypothesis Batch, post-batch promotion list -- GOLD_SILVER_RATIO_MR
    # (watchlist, not a survivor) and PEAD (verified, permanent survivor-bias
    # caveat) -- see docs/three_new_hypothesis_batch_closing_report.md.
    ("GOLD_SILVER_RATIO_MR", "gold-silver-ratio-mr-v1.0.0", "GOLD-SILVER"): _GOLD_SILVER_RATIO_STATUS,
    **{
        ("PEAD", version, ticker): _PEAD_SURVIVED_STATUS
        for version in ("pead-v1.0.0-surprise3pct-hold10", "pead-v1.0.0-surprise8pct-hold10")
        for ticker in _PEAD_TICKERS
    },
}

DEFAULT_VERIFICATION_STATUS = "unverified"


def verification_status_for(strategy_id: str, strategy_version: str, asset: str) -> str:
    """Looks up the maintained status string for (strategy_id, strategy_version,
    asset). Falls back to DEFAULT_VERIFICATION_STATUS — never raises, never
    fabricates a specific-sounding status for a config nobody has actually annotated
    here yet."""
    return VERIFICATION_STATUS.get((strategy_id, strategy_version, asset), DEFAULT_VERIFICATION_STATUS)
