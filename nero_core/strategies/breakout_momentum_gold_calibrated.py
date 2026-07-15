from __future__ import annotations

from dataclasses import asdict

from nero_core.strategies.breakout_momentum import STRATEGY_ID, BreakoutMomentumParameters
from nero_core.strategies.mean_reversion_gold_calibrated import (
    BTC_MEASURED_PRICE_ATR_RATIO,
    GOLD_FEE_SCALE_FACTOR,
    GOLD_MEASURED_PRICE_ATR_RATIO,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.1.0-gold-calibrated"

# BREAKOUT_MOMENTUM's size_entry uses the exact same structural pattern as MEAN_REVERSION's
# (ATR-based stop distance, fee charged on notional): fee_to_risk_ratio = (price /
# (atr_stop_multiple * ATR)) * (fee_bps / 10000). ATR itself is computed identically in
# both strategies (same atr() function, same atr_period=14) — it's an instrument
# characteristic of GOLD vs BTC, not specific to which strategy is trading it. So this
# reuses the SAME measured price/ATR ratio and scale factor from the fee/ATR investigation
# (nero_core.strategies.mean_reversion_gold_calibrated), rather than re-deriving a second,
# strategy-specific number — see that module for the full derivation.
GOLD_CALIBRATED_PARAMETERS = BreakoutMomentumParameters(
    fee_bps=10.0 * GOLD_FEE_SCALE_FACTOR,
    slippage_bps=2.0 * GOLD_FEE_SCALE_FACTOR,
)

STRATEGY_DESCRIPTION = (
    "Identical entry/exit rules to BREAKOUT_MOMENTUM breakout-momentum-v1.0.0 (close above "
    "the prior 20-bar high, close above MA200, RSI >= 50, fixed 1.25R target, 1.2x ATR "
    "stop) — only fee_bps and slippage_bps are recalibrated for GOLD's much lower relative "
    "volatility, using the same measured BTC/GOLD price-to-ATR scale factor derived in the "
    "fee/ATR investigation via MEAN_REVERSION's entries "
    f"({BTC_MEASURED_PRICE_ATR_RATIO:.4f} / {GOLD_MEASURED_PRICE_ATR_RATIO:.4f} = "
    f"{GOLD_FEE_SCALE_FACTOR:.4f}) — ATR is computed identically in both strategies, so this "
    "is an instrument characteristic, not a Mean-Reversion-specific one: fee_bps "
    f"10.0 -> {GOLD_CALIBRATED_PARAMETERS.fee_bps:.4f}, slippage_bps "
    f"2.0 -> {GOLD_CALIBRATED_PARAMETERS.slippage_bps:.4f}. This is a cost-assumption "
    "recalibration, not a strategy-logic change — no entry/exit condition differs from v1.0.0."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the GOLD-calibrated Breakout Momentum variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(GOLD_CALIBRATED_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
