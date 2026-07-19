"""RANGE_MEAN_REVERSION ADX-falling variant (v1.2.0) — RMR Variant Research Cycle,
Stage 1, variant (b) RMR_ADX_FALLING_ETH_4H.

Adds ONE extra entry condition on top of v1.0.0, everything else unchanged: ADX[t] <
ADX[t - 3 closed candles] (require_adx_falling=True, adx_falling_lookback=3) — a
genuine 3-candle decline, not 1-candle noise. Both directions (long+short) remain
enabled; only the additional falling-ADX precondition is new.
"""
from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "range-mean-reversion-v1.2.0-adx-falling"

ADX_FALLING_PARAMETERS = replace(DEFAULT_PARAMETERS, require_adx_falling=True, adx_falling_lookback=3)

STRATEGY_DESCRIPTION = (
    "Identical to RANGE_MEAN_REVERSION range-mean-reversion-v1.0.0 except entry "
    "additionally requires ADX[t] < ADX[t - 3 closed candles] (a genuine 3-candle "
    "decline, not 1-candle noise) — testing whether a DECLINING regime intensity, not "
    "merely 'currently below the ranging threshold,' is a better entry filter. Both "
    "directions still enabled. RMR Variant Research Cycle, Stage 1: ETH/4h."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the ADX-falling variant. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(ADX_FALLING_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
