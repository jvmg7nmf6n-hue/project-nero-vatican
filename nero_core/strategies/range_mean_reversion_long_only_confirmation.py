"""RANGE_MEAN_REVERSION long-only + confirmation variant (v1.4.0) — RMR Variant
Research Cycle, Stage 3, Refinement 1: RMR_LONG_ONLY_CONFIRMATION_BTC_1D.

Diagnosis-justified (docs/rmr_variant_research_stage2_diagnosis.md), stacking the two
findings that independently improved BTC/1d in Stage 1:
  - (b) the short leg cost ~-0.264 R/trade on BTC/1d (substantial, not marginal) —
    v1.1.0-long-only's allow_short=False fix.
  - (d) the confirmation entry's exit-reason mix shifted dramatically toward
    REVERSION_TARGET (32% -> 68%) on BTC/1d, the clearest mechanistic evidence in the
    whole cycle that "waiting for the turn" avoids the regime-break/stop-out failure
    mode — v1.3.0-confirmation's entry pattern.

Tested ONLY on BTC/1d — the one asset/timeframe where BOTH weaknesses were
diagnosed — no scope expansion to other assets.

Reuses range_mean_reversion_confirmation's entry pattern, exit mechanics, state, and
sizing entirely unchanged — only allow_short=False differs from v1.3.0-confirmation.
"""
from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "range-mean-reversion-v1.4.0-long-only-confirmation"

LONG_ONLY_CONFIRMATION_PARAMETERS = replace(DEFAULT_PARAMETERS, allow_short=False)

STRATEGY_DESCRIPTION = (
    "Stacks v1.1.0-long-only's allow_short=False onto v1.3.0-confirmation's "
    "wait-for-the-turn entry pattern — both independently improved BTC/1d in Stage 1 "
    "(short leg cost ~-0.264 R/trade; confirmation's exit mix shifted from 32% to 68% "
    "REVERSION_TARGET). RMR Variant Research Cycle, Stage 3, Refinement 1. Tested "
    "only on BTC/1d, where both underlying weaknesses were diagnosed."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the long-only + confirmation variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(LONG_ONLY_CONFIRMATION_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
