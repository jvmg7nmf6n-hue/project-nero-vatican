from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.0.0-target-1r"

# Ported AS-IS from the original NERO strategy lab's MR_TARGET_1R_V1 candidate
# (nero_app/core/strategy_lab_agent.py CandidateSpec, lines 71-78): identical
# rsi_entry_below (35.0) and lower_bb_buffer_atr (0.0) to v1.0.0 — the only real
# difference is target_mode="FIXED_1R" (target = entry + 1x risk-per-unit) instead of
# v1.0.0's FROZEN_MA20 floating target. Not GOLD fee-calibrated here; reuses
# nero_core.strategies.timeframe_calibration.build_calibrated_params at backtest-run
# time like every other strategy in the sweep.
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    target_mode="FIXED_1R",
)

STRATEGY_DESCRIPTION = (
    "Ported as-is from the original NERO strategy lab's MR_TARGET_1R_V1 candidate: "
    "identical entry rules to MEAN_REVERSION v1.0.0 (RSI<35, close below the lower "
    "Bollinger Band, close above MA200, 1.5x ATR stop) but with a fixed 1R target "
    "(entry + 1x risk-per-unit) instead of v1.0.0's floating MA20 target. No other "
    "parameter differs from v1.0.0."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the MR_TARGET_1R_V1 port. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
