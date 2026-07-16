from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.mean_reversion import STRATEGY_ID
from nero_core.strategies.mean_reversion_gold_calibrated import GOLD_CALIBRATED_PARAMETERS
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.2.0-gold-calibrated-1week"

# --- Bug fix: max_holding_hours was left at the crypto default (24) inherited from
# mean-reversion-v1.1.0-gold-calibrated, which itself inherited it from v1.0.0. That
# default traces back to the original NERO mean_reversion_agent.py, which hard-codes
# interval="1h" (see nero_app/core/mean_reversion_agent.py) — so max_holding_hours=24
# was always "hold for up to 24 CANDLES", not literally "24 hours" as an instrument-
# independent wall-clock cap. On 1week candles (168h/candle), the unmodified default
# forces every trade closed via the TIME exit at the very next candle after entry —
# before stop-loss or target ever gets a chance to be hit — because a single candle's
# duration (168h) already exceeds the 24h cap. Every weekly trade was silently reduced
# to "hold exactly one candle, exit at its close," regardless of price action.
#
# Fix: preserve the ORIGINAL design intent (a 24-candle hold cap) instead of the literal
# hour count, by re-deriving max_holding_hours for the 1week candle duration:
ORIGINAL_MAX_HOLDING_CANDLES = 24  # from max_holding_hours=24 @ interval="1h" (1 candle/hour)
WEEKLY_CANDLE_HOURS = 7 * 24  # 168 hours/candle
WEEKLY_MAX_HOLDING_HOURS = ORIGINAL_MAX_HOLDING_CANDLES * WEEKLY_CANDLE_HOURS  # 4032 hours (24 weeks)

GOLD_CALIBRATED_1WEEK_PARAMETERS = replace(
    GOLD_CALIBRATED_PARAMETERS,
    max_holding_hours=WEEKLY_MAX_HOLDING_HOURS,
)

STRATEGY_DESCRIPTION = (
    "Identical to MEAN_REVERSION mean-reversion-v1.1.0-gold-calibrated (same entry/exit "
    "rules, same fee_bps/slippage_bps GOLD recalibration) — only max_holding_hours is "
    "corrected for the 1week candle timeframe. The inherited crypto default of 24 hours "
    "is shorter than a single 1week candle (168 hours), which silently turned the TIME "
    "exit into a forced one-candle exit on every trade. max_holding_hours is re-derived "
    f"to preserve the original 24-candle hold cap at weekly resolution: {ORIGINAL_MAX_HOLDING_CANDLES} "
    f"candles * {WEEKLY_CANDLE_HOURS}h/candle = {WEEKLY_MAX_HOLDING_HOURS}h. This is a "
    "timeframe-unit bug fix, not a strategy-logic change — no entry/exit condition "
    "differs from v1.1.0-gold-calibrated."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the 1week-corrected GOLD-calibrated Mean Reversion variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(GOLD_CALIBRATED_1WEEK_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
