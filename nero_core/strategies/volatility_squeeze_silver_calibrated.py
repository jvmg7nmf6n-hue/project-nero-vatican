"""VOLATILITY_SQUEEZE / SILVER, 24h (ma200/ma150/ma100) — Asset Expansion Phase A
follow-up.

Same entry/exit rules as each volatility-squeeze-v1.0.0-ma{200,150,100} variant
(Bollinger squeeze breakout, trend filter, 1.5x ATR stop, 2.0x ATR target) — only
fee_bps/slippage_bps and max_holding_hours are recalibrated for SILVER's own measured
volatility and the 24h candle duration, via build_params_for_run (the same helper
GOLD/PLATINUM sweep runs already use — see nero_core.strategies.volatility_squeeze).

STATUS: PROMISING-WATCHLIST results from the Asset Expansion Phase A sweep
(docs/metals_phase_a_full_sweep.md, docs/metals_grid_shift_verification.md) — all three
positive in both train/test halves with an adequate sample, but grid-shift verification
does not apply at 24h and NO Phase A config reached SURVIVED. Wiring these into the
live scheduler is a forward-test to accrue live evidence, per user request — none of
them is a proven edge (see nero_core/execution/verification_status.py).
"""
from __future__ import annotations

from dataclasses import asdict

from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.volatility_squeeze import (
    DEFAULT_PARAMETERS_MA100,
    DEFAULT_PARAMETERS_MA150,
    DEFAULT_PARAMETERS_MA200,
    STRATEGY_ID,
    VolatilitySqueezeParameters,
    build_params_for_run,
)

STRATEGY_VERSION_MA200 = "volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h"
STRATEGY_VERSION_MA150 = "volatility-squeeze-v1.1.0-ma150-silver-calibrated-24h"
STRATEGY_VERSION_MA100 = "volatility-squeeze-v1.1.0-ma100-silver-calibrated-24h"

SILVER_CALIBRATED_PARAMETERS_MA200 = build_params_for_run(DEFAULT_PARAMETERS_MA200, "24h", "SILVER")
SILVER_CALIBRATED_PARAMETERS_MA150 = build_params_for_run(DEFAULT_PARAMETERS_MA150, "24h", "SILVER")
SILVER_CALIBRATED_PARAMETERS_MA100 = build_params_for_run(DEFAULT_PARAMETERS_MA100, "24h", "SILVER")


def _description(params: VolatilitySqueezeParameters) -> str:
    return (
        f"Identical entry/exit rules to VOLATILITY_SQUEEZE volatility-squeeze-v1.0.0-ma"
        f"{params.trend_ma_period} (Bollinger squeeze breakout, close > MA{params.trend_ma_period}, "
        "1.5x ATR stop, 2.0x ATR target) — only fee_bps/slippage_bps (SILVER's own measured "
        "price/ATR scale factor — see nero_core.strategies.metals_calibration) and "
        "max_holding_hours (24h candle duration) are recalibrated. PROMISING-WATCHLIST per "
        "Asset Expansion Phase A (docs/metals_phase_a_full_sweep.md): positive both halves, "
        "adequate sample, but grid-shift verification does not apply at 24h and no Phase A "
        "config reached SURVIVED. Forward-testing only, not a proven edge — no entry/exit "
        f"condition differs from v1.0.0-ma{params.trend_ma_period}. fee_bps 10.0 -> "
        f"{params.fee_bps:.4f}, slippage_bps 2.0 -> {params.slippage_bps:.4f}."
    )


def _register_silver_variant(
    registry: StrategyRegistry, version: str, params: VolatilitySqueezeParameters
) -> StrategyVariant:
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=version,
        parameters=asdict(params),
        description=_description(params),
    )


def register_ma200_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the SILVER-calibrated ma200 variant. Raises StrategyAlreadyRegisteredError
    if called twice on the same registry."""
    return _register_silver_variant(registry, STRATEGY_VERSION_MA200, SILVER_CALIBRATED_PARAMETERS_MA200)


def register_ma150_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the SILVER-calibrated ma150 variant. Raises StrategyAlreadyRegisteredError
    if called twice on the same registry."""
    return _register_silver_variant(registry, STRATEGY_VERSION_MA150, SILVER_CALIBRATED_PARAMETERS_MA150)


def register_ma100_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the SILVER-calibrated ma100 variant. Raises StrategyAlreadyRegisteredError
    if called twice on the same registry."""
    return _register_silver_variant(registry, STRATEGY_VERSION_MA100, SILVER_CALIBRATED_PARAMETERS_MA100)
