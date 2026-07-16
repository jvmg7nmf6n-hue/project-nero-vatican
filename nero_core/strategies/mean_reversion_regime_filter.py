from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "mean-reversion-v1.0.0-regime-filter"

# Ported AS-IS from the original NERO strategy lab's MR_REGIME_FILTER_V1 candidate
# (nero_app/core/strategy_lab_agent.py CandidateSpec, lines 63-71): only
# lower_bb_buffer_atr differs from the base MeanReversionConfig — rsi_entry_below (35.0)
# and target_mode (FROZEN_MA20) are unchanged from v1.0.0.
#
# NAMING WARNING, verified directly against the source: despite being called
# "Regime-filtered pullback" in the original CandidateSpec's `title`, this candidate does
# NOT actually filter by any regime. CandidateSpec has a `quant_gate: float | None = None`
# field, but MR_REGIME_FILTER_V1's spec never sets it (stays None), and — checked across
# the entire source file — `quant_gate` is never read anywhere else either; it's a dead
# field. So this port's only real behavioral difference from v1.0.0 is the slightly
# relaxed lower-Bollinger-Band buffer (0.1x ATR). This is NOT the same thing as this
# codebase's own MEAN_REVERSION v2.0.0-regime-filtered (nero_core.strategies.
# mean_reversion_v2), which genuinely gates entries on a GARCH/EWMA volatility regime and
# a higher-timeframe daily trend check — that one is real; this one, despite its name, is
# just a marginally looser band threshold. Ported faithfully, including the misleading
# name, rather than silently "fixing" or renaming what the original candidate was.
PARAMETERS = replace(
    DEFAULT_PARAMETERS,
    lower_bb_buffer_atr=0.1,
)

STRATEGY_DESCRIPTION = (
    "Ported as-is from the original NERO strategy lab's MR_REGIME_FILTER_V1 candidate "
    "('Regime-filtered pullback'): identical to MEAN_REVERSION v1.0.0 (RSI<35, close "
    "above MA200, MA20 frozen target, 1.5x ATR stop) with the lower-Bollinger-Band check "
    "relaxed by 0.1x ATR (close < bb_lower + 0.1*atr). Despite the candidate's name, it "
    "does NOT gate on any market regime — the original CandidateSpec's quant_gate field "
    "is left at its None default and is unused anywhere in the source file this was "
    "ported from. Not to be confused with this codebase's own genuinely regime-gated "
    "mean-reversion-v2.0.0-regime-filtered (nero_core.strategies.mean_reversion_v2)."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the MR_REGIME_FILTER_V1 port. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
