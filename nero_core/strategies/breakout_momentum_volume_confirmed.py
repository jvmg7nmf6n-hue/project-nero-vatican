from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.breakout_momentum import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.4.0-volume-confirmed"

# H4 hypothesis: identical rules to breakout-momentum-v1.0.0 PLUS one additional entry
# condition — the entry candle's own volume must exceed 1.5x the average volume of the
# PRIOR 20 candles (excluding the entry candle itself). Crypto only (GOLD volume from
# Twelve Data is unreliable/frequently zero — see nero_core.data_sources.market_data).
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    volume_confirmed=True,
)

STRATEGY_DESCRIPTION = (
    "Identical to BREAKOUT_MOMENTUM breakout-momentum-v1.0.0 (close above the prior "
    "20-bar high, close above MA200, RSI >= 50, fixed 1.25R target, 1.2x ATR stop) plus "
    "one additional entry condition: the entry candle's own volume must exceed 1.5x "
    "the average volume of the prior 20 candles (excluding the entry candle itself). "
    "Crypto only — GOLD volume from Twelve Data is unreliable for this check. Question "
    "this variant exists to answer: does the volume filter improve per-trade "
    "expectancy, or does it just cut the trade count without a quality gain?"
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the volume-confirmed BREAKOUT_MOMENTUM variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
