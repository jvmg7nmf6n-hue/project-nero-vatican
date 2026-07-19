"""Human-editable verification status wording for the public site export
(nero_core.execution.export_site_data). This is the ONE place status strings live —
export logic only ever looks values up here, never hardcodes wording inline, so
updating a strategy's status is a one-line edit here, not a code change to the
exporter itself.

Keyed by (strategy_id, asset) since that's how nero_core.execution.live_scheduler's
roster identifies each live config (a strategy_id can in principle trade more than one
asset in the future, even though today's roster is 1:1).
"""
from __future__ import annotations

VERIFICATION_STATUS: dict[tuple[str, str], str] = {
    ("BREAKOUT_MOMENTUM", "GOLD"): "triple-verified",
    ("TREND_PULLBACK", "BNB"): "verified — sample-limited",
    ("COINTEGRATION_PAIRS", "BTC-ETH"): "verified — weakest, live-proving",
    ("NEWS_SENTIMENT", "GOLD"): "forward-test-only, no historical backtest",
    ("NEWS_SENTIMENT", "BTC"): "forward-test-only, no historical backtest",
    # Asset Expansion Phase A metals sweep (docs/metals_phase_a_full_sweep.md,
    # docs/metals_grid_shift_verification.md): positive both backtest halves, adequate
    # sample, but grid-shift verification does not apply at 24h and NO Phase A config
    # reached SURVIVED. Wired live at the user's explicit request to accrue forward
    # evidence — must never be worded as "verified".
    ("BREAKOUT_MOMENTUM", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("TREND_PULLBACK", "SILVER"): "promising-watchlist — forward-testing, not verified",
    ("VOLATILITY_SQUEEZE", "SILVER"): "promising-watchlist — forward-testing, not verified",
}

DEFAULT_VERIFICATION_STATUS = "unverified"


def verification_status_for(strategy_id: str, asset: str) -> str:
    """Looks up the maintained status string for (strategy_id, asset). Falls back to
    DEFAULT_VERIFICATION_STATUS — never raises, never fabricates a specific-sounding
    status for a config nobody has actually annotated here yet."""
    return VERIFICATION_STATUS.get((strategy_id, asset), DEFAULT_VERIFICATION_STATUS)
