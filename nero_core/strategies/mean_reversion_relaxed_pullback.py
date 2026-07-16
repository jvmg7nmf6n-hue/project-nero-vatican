from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.0.0-relaxed-pullback"

# Ported AS-IS from the original NERO strategy lab's MR_RELAXED_PULLBACK_V1 candidate
# (nero_app/core/strategy_lab_agent.py CandidateSpec, lines 49-55): only
# rsi_entry_below and lower_bb_buffer_atr differ from the base MeanReversionConfig —
# entry/exit mechanics, fee/slippage, sizing, and target_mode (FROZEN_MA20) are all
# otherwise identical to MEAN_REVERSION v1.0.0. This is a genuinely lower-priority port
# (not GOLD fee-calibrated, not timeframe-holding-cap-corrected here) — it reuses
# nero_core.strategies.timeframe_calibration.build_calibrated_params at backtest-run
# time for both of those corrections, same as every other strategy in the sweep.
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    rsi_entry_below=40.0,
    lower_bb_buffer_atr=0.25,
)

STRATEGY_DESCRIPTION = (
    "Ported as-is from the original NERO strategy lab's MR_RELAXED_PULLBACK_V1 "
    "candidate: identical to MEAN_REVERSION v1.0.0 (close above MA200, MA20 frozen "
    "target, 1.5x ATR stop) but with a loosened entry trigger — RSI below 40 (vs. 35) "
    "and the lower-Bollinger-Band check relaxed by 0.25x ATR (close < bb_lower + "
    "0.25*atr, catching pullbacks that come close to the band without quite touching "
    "it). No other parameter differs from v1.0.0."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the MR_RELAXED_PULLBACK_V1 port. Raises StrategyAlreadyRegisteredError
    if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
