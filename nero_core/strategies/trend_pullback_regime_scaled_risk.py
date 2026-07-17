from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "trend-pullback-v1.1.0-regime-scaled-risk"

# H3 hypothesis: identical entry/exit/stop rules to trend-pullback-v1.0.0 — only the
# per-trade RISK BUDGET differs. Existing fixed-fractional sizing already normalizes
# position SIZE by ATR (quantity = risk_dollars / ATR-based stop distance); this variant
# additionally scales risk_dollars itself by clamp(median_trailing_ATRpct /
# current_ATRpct, 0.5, 2.0) — see nero_core.strategies.regime_risk for the full
# derivation. median_trailing_ATRpct is the rolling median over the trailing 100 CLOSED
# candles ending at and including the entry candle (no lookahead).
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    regime_scaled_risk=True,
)

STRATEGY_DESCRIPTION = (
    "Identical to TREND_PULLBACK trend-pullback-v1.0.0 (established uptrend pullback "
    "to MA50, RSI 40-60, 1.5x ATR stop, 2.0x ATR target) — only the per-trade risk "
    "budget differs. risk_per_trade is scaled by clamp(median_trailing_ATRpct / "
    "current_ATRpct, 0.5, 2.0), median over the trailing 100 closed candles as of the "
    "entry candle (nero_core.strategies.regime_risk). This is a genuinely different "
    "variable from the existing ATR-based position-size normalization every "
    "fixed-fractional strategy in this codebase already does — this scales the RISK "
    "BUDGET by volatility regime, not just the position size for a given risk budget."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the regime-scaled-risk TREND_PULLBACK variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
