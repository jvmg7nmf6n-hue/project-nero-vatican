from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import GOLD_CALIBRATED_1WEEK_PARAMETERS
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.3.0-gold-calibrated-1week-regime-scaled-risk"

# H3 hypothesis: identical entry/exit/stop rules and GOLD fee/1week-holding-cap
# calibration to breakout-momentum-v1.2.0-gold-calibrated-1week — only the per-trade
# RISK BUDGET differs, scaled by clamp(median_trailing_ATRpct / current_ATRpct, 0.5,
# 2.0) (see nero_core.strategies.regime_risk for the full derivation). This is a
# different variable from the existing ATR-based position-SIZE normalization every
# fixed-fractional strategy in this codebase already does.
PARAMETERS = replace(
    GOLD_CALIBRATED_1WEEK_PARAMETERS,
    regime_scaled_risk=True,
)

STRATEGY_DESCRIPTION = (
    "Identical to BREAKOUT_MOMENTUM breakout-momentum-v1.2.0-gold-calibrated-1week "
    "(same entry/exit rules, same GOLD fee recalibration, same 1week-timeframe holding "
    "cap fix) — only the per-trade risk budget differs. risk_per_trade is scaled by "
    "clamp(median_trailing_ATRpct / current_ATRpct, 0.5, 2.0), median over the trailing "
    "100 closed candles as of the entry candle (nero_core.strategies.regime_risk)."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the regime-scaled-risk GOLD-calibrated-1week BREAKOUT_MOMENTUM
    variant. Raises StrategyAlreadyRegisteredError if called twice on the same
    registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
