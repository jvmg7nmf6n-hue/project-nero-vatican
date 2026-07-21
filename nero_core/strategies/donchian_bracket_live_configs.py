"""DONCHIAN_TREND bracket-exit, 4 live-wiring configs — Donchian Cross-Asset Deep-Dive
promotion list (docs/donchian_deep_dive_closing_report.md). Same entry/exit MECHANISM
as donchian_breakout_bracket.py (bidirectional N-period channel breakout, 2.0x ATR
stop, fixed 2.0R target, N-matched real-time holding cap) — only the N preset,
asset-class fee/slippage, and asset differ per config, via build_parameters_for_n.

NOT survivors. Every one of these 4 is watchlist/forward-testing, matching the
closing report's own explicit refusal to claim "Vatican's first new verified
strategy family": GOLD/1week/N20's raw SURVIVED-quality result is capped to
PROMISING-WATCHLIST by grid-shift being structurally unavailable at 1week (a
verification-method limitation, not a data/CI shortfall) — see
nero_core/execution/verification_status.py for the exact status wording wired for
each of these 4 configs.
"""
from __future__ import annotations

from dataclasses import asdict

from nero_core.strategies.donchian_breakout_bracket import (
    STRATEGY_ID,
    DonchianBracketParameters,
    build_parameters_for_n,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION_GOLD_N20 = "donchian-trend-v2.0.0-bracket-gold-n20-1week"
STRATEGY_VERSION_EURUSD_N20 = "donchian-trend-v2.0.0-bracket-eurusd-n20-1week"
STRATEGY_VERSION_GBPUSD_N20 = "donchian-trend-v2.0.0-bracket-gbpusd-n20-1week"
STRATEGY_VERSION_USDJPY_N40 = "donchian-trend-v2.0.0-bracket-usdjpy-n40-1week"

# Metals convention: 10 bps fee / 2 bps slippage. Forex convention: 5 bps fee / 2 bps
# slippage — both match the exact fee_bps values used for these asset classes in
# tools/backtest_donchian_deep_dive.py's own FEE_BPS_BY_CLASS, so the live-wired
# parameters are identical to what was actually backtested, not a fresh guess.
GOLD_N20_PARAMETERS = build_parameters_for_n("N20", "1week", fee_bps=10.0, slippage_bps=2.0)
EURUSD_N20_PARAMETERS = build_parameters_for_n("N20", "1week", fee_bps=5.0, slippage_bps=2.0)
GBPUSD_N20_PARAMETERS = build_parameters_for_n("N20", "1week", fee_bps=5.0, slippage_bps=2.0)
USDJPY_N40_PARAMETERS = build_parameters_for_n("N40", "1week", fee_bps=5.0, slippage_bps=2.0)


def _description(asset: str, n_key: str, params: DonchianBracketParameters) -> str:
    holding_weeks = params.max_holding_hours // 168
    return (
        f"Bidirectional Donchian channel breakout ({n_key}, channel_period="
        f"{params.channel_period} candles), 2.0x ATR(14) stop, fixed 2.0R target, "
        f"{params.max_holding_hours}h ({holding_weeks}-week) holding cap. Donchian "
        "Cross-Asset Deep-Dive promotion list (docs/donchian_deep_dive_closing_report.md) "
        f"— {asset}/1week/{n_key}. Watchlist, not a survivor — see "
        "nero_core/execution/verification_status.py for this config's exact status wording."
    )


def _register(
    registry: StrategyRegistry, version: str, params: DonchianBracketParameters, asset: str, n_key: str
) -> StrategyVariant:
    return registry.register(
        strategy_id=STRATEGY_ID, version=version, parameters=asdict(params),
        description=_description(asset, n_key, params),
    )


def register_gold_n20_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Raises StrategyAlreadyRegisteredError if called twice on the same registry."""
    return _register(registry, STRATEGY_VERSION_GOLD_N20, GOLD_N20_PARAMETERS, "GOLD", "N20")


def register_eurusd_n20_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Raises StrategyAlreadyRegisteredError if called twice on the same registry."""
    return _register(registry, STRATEGY_VERSION_EURUSD_N20, EURUSD_N20_PARAMETERS, "EUR/USD", "N20")


def register_gbpusd_n20_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Raises StrategyAlreadyRegisteredError if called twice on the same registry."""
    return _register(registry, STRATEGY_VERSION_GBPUSD_N20, GBPUSD_N20_PARAMETERS, "GBP/USD", "N20")


def register_usdjpy_n40_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Raises StrategyAlreadyRegisteredError if called twice on the same registry."""
    return _register(registry, STRATEGY_VERSION_USDJPY_N40, USDJPY_N40_PARAMETERS, "USD/JPY", "N40")
