"""BREAKOUT_MOMENTUM / SILVER, 24h — Asset Expansion Phase A follow-up.

Same entry/exit rules as breakout-momentum-v1.0.0 (20-bar breakout, close > MA200,
RSI >= 50, 1.25R target, 1.2x ATR stop) — only fee_bps/slippage_bps and
max_holding_hours are recalibrated for SILVER's own measured volatility and the 24h
candle duration, via the shared nero_core.strategies.timeframe_calibration helpers
(the same mechanism GOLD's own *_gold_calibrated variants use).

STATUS: this is a PROMISING-WATCHLIST result from the Asset Expansion Phase A sweep
(docs/metals_phase_a_full_sweep.md, docs/metals_grid_shift_verification.md) — positive
in both train/test halves with an adequate sample, but grid-shift verification does not
apply at 24h (COMEX/NYMEX daily settlement gap — see
docs/metals_grid_shift_verification.md) and NO Phase A config reached SURVIVED. Wiring
this into the live scheduler is a forward-test to accrue live evidence, per user
request — it is NOT a proven edge and must not be presented as one anywhere in the UI
or docs (see nero_core/execution/verification_status.py).
"""
from __future__ import annotations

from dataclasses import asdict

from nero_core.strategies.breakout_momentum import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.timeframe_calibration import build_calibrated_params

STRATEGY_VERSION = "breakout-momentum-v1.6.0-silver-calibrated-24h"

SILVER_CALIBRATED_PARAMETERS = build_calibrated_params(DEFAULT_PARAMETERS, "24h", "SILVER")

STRATEGY_DESCRIPTION = (
    "Identical entry/exit rules to BREAKOUT_MOMENTUM breakout-momentum-v1.0.0 (20-bar "
    "breakout, close > MA200, RSI >= 50, 1.25R target, 1.2x ATR stop) — only "
    "fee_bps/slippage_bps (SILVER's own measured price/ATR scale factor, NOT reused from "
    "GOLD — see nero_core.strategies.metals_calibration) and max_holding_hours (24h "
    "candle duration) are recalibrated. PROMISING-WATCHLIST per Asset Expansion Phase A "
    "(docs/metals_phase_a_full_sweep.md): positive both halves, adequate sample, but "
    "grid-shift verification does not apply at 24h and no Phase A config reached "
    "SURVIVED. Forward-testing only, not a proven edge — no entry/exit condition differs "
    f"from v1.0.0. fee_bps 10.0 -> {SILVER_CALIBRATED_PARAMETERS.fee_bps:.4f}, slippage_bps "
    f"2.0 -> {SILVER_CALIBRATED_PARAMETERS.slippage_bps:.4f}."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the SILVER-calibrated Breakout Momentum variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(SILVER_CALIBRATED_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
