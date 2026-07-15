from __future__ import annotations

from dataclasses import asdict

from nero_core.strategies.mean_reversion import STRATEGY_ID, MeanReversionParameters
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.1.0-gold-calibrated"

# --- Derivation (from the fee/ATR investigation into GOLD's extreme negative ExpR) -------
#
# Root cause found there: fee_to_risk_ratio = (price / (atr_stop_multiple * ATR)) *
# (fee_bps / 10000). This ratio is proportional to price/ATR (i.e. inversely proportional
# to relative volatility) and to fee_bps. The original fee_bps=10.0 / slippage_bps=2.0
# assumptions were calibrated for crypto exchange fee structures in the source NERO
# project and were never adjusted for other instrument classes.
#
# Measured price/ATR, averaged over every 4h candle where MEAN_REVERSION v1 actually took
# an entry (same methodology as the original investigation, reproduced here at full
# precision instead of the 1-decimal terminal display quoted there):
GOLD_MEASURED_PRICE_ATR_RATIO = 185.18676789865873  # n=46 GOLD 4h entries
BTC_MEASURED_PRICE_ATR_RATIO = 70.20658340847632  # n=141 BTC 4h entries

# Scaling fee_bps/slippage_bps down by BTC's/GOLD's ratio brings GOLD's fee-to-risk burden
# back in line with what the strategy was originally designed and tested against, without
# touching the entry/exit rules themselves (RSI<35, close below lower Bollinger Band,
# close above MA200, MA20 frozen target, 1.5x ATR stop are all unchanged from v1.0.0).
GOLD_FEE_SCALE_FACTOR = BTC_MEASURED_PRICE_ATR_RATIO / GOLD_MEASURED_PRICE_ATR_RATIO  # ~= 0.3791

GOLD_CALIBRATED_PARAMETERS = MeanReversionParameters(
    fee_bps=10.0 * GOLD_FEE_SCALE_FACTOR,
    slippage_bps=2.0 * GOLD_FEE_SCALE_FACTOR,
)

STRATEGY_DESCRIPTION = (
    "Identical entry/exit rules to MEAN_REVERSION mean-reversion-v1.0.0 (RSI<35, close "
    "below lower Bollinger Band, close above MA200, MA20 frozen target, 1.5x ATR stop) — "
    "only fee_bps and slippage_bps are recalibrated for GOLD's much lower relative "
    "volatility. Both are scaled down by the measured BTC/GOLD average price-to-ATR ratio "
    f"at the 4h timeframe ({BTC_MEASURED_PRICE_ATR_RATIO:.4f} / {GOLD_MEASURED_PRICE_ATR_RATIO:.4f} "
    f"= {GOLD_FEE_SCALE_FACTOR:.4f}), from the fee/ATR investigation: fee_bps "
    f"10.0 -> {GOLD_CALIBRATED_PARAMETERS.fee_bps:.4f}, slippage_bps "
    f"2.0 -> {GOLD_CALIBRATED_PARAMETERS.slippage_bps:.4f}. This is a cost-assumption "
    "recalibration, not a strategy-logic change — no entry/exit condition differs from v1.0.0."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the GOLD-calibrated Mean Reversion variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(GOLD_CALIBRATED_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
