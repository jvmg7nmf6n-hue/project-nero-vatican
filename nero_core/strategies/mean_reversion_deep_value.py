from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.0.0-deep-value"

# Ported AS-IS from the original NERO strategy lab's MR_DEEP_VALUE_V1 candidate
# (nero_app/core/strategy_lab_agent.py CandidateSpec, lines 64-70): only
# rsi_entry_below differs from the base MeanReversionConfig (a stricter, deeper-dip
# threshold than v1.0.0's 35.0) — lower_bb_buffer_atr, target_mode (FROZEN_MA20), and
# every other field are unchanged. Not GOLD fee-calibrated here; reuses
# nero_core.strategies.timeframe_calibration.build_calibrated_params at backtest-run
# time like every other strategy in the sweep.
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    rsi_entry_below=30.0,
)

STRATEGY_DESCRIPTION = (
    "Ported as-is from the original NERO strategy lab's MR_DEEP_VALUE_V1 candidate: "
    "identical to MEAN_REVERSION v1.0.0 (close below the lower Bollinger Band, close "
    "above MA200, MA20 frozen target, 1.5x ATR stop) but with a stricter RSI entry "
    "threshold — RSI below 30 (vs. 35), requiring a deeper oversold dip before "
    "entering. No other parameter differs from v1.0.0."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the MR_DEEP_VALUE_V1 port. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
