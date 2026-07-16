from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum_gold_calibrated import GOLD_CALIBRATED_PARAMETERS
from nero_core.strategies.mean_reversion_gold_calibrated_1week import (
    ORIGINAL_MAX_HOLDING_CANDLES,
    WEEKLY_CANDLE_HOURS,
    WEEKLY_MAX_HOLDING_HOURS,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.2.0-gold-calibrated-1week"

# Same bug, same fix as mean_reversion_gold_calibrated_1week (see that module for the full
# derivation): max_holding_hours=24 is a 24-CANDLE hold cap inherited from the original
# NERO agent's interval="1h" assumption, not an instrument-independent wall-clock cap. On
# 1week candles (168h/candle) the unmodified default forces a TIME exit on every trade at
# the very next candle, before stop-loss or target can ever be hit. Reused here (not
# re-derived) because it's a candle-duration constant, not a strategy- or instrument-
# specific one — identical to how the GOLD fee scale factor is shared, not recomputed,
# between the two gold_calibrated modules.
GOLD_CALIBRATED_1WEEK_PARAMETERS = replace(
    GOLD_CALIBRATED_PARAMETERS,
    max_holding_hours=WEEKLY_MAX_HOLDING_HOURS,
)

STRATEGY_DESCRIPTION = (
    "Identical to BREAKOUT_MOMENTUM breakout-momentum-v1.1.0-gold-calibrated (same "
    "entry/exit rules, same fee_bps/slippage_bps GOLD recalibration) — only "
    "max_holding_hours is corrected for the 1week candle timeframe. The inherited crypto "
    "default of 24 hours is shorter than a single 1week candle (168 hours), which "
    "silently turned the TIME exit into a forced one-candle exit on every trade. "
    f"max_holding_hours is re-derived to preserve the original {ORIGINAL_MAX_HOLDING_CANDLES}-candle "
    f"hold cap at weekly resolution: {ORIGINAL_MAX_HOLDING_CANDLES} candles * "
    f"{WEEKLY_CANDLE_HOURS}h/candle = {WEEKLY_MAX_HOLDING_HOURS}h. This is a "
    "timeframe-unit bug fix, not a strategy-logic change — no entry/exit condition "
    "differs from v1.1.0-gold-calibrated."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the 1week-corrected GOLD-calibrated Breakout Momentum variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(GOLD_CALIBRATED_1WEEK_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
