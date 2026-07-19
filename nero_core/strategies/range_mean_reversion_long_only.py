"""RANGE_MEAN_REVERSION long-only variant (v1.1.0) — RMR Variant Research Cycle,
Stage 1, variants (a) RMR_LONG_ONLY_EURUSD_4H and (c) RMR_LONG_ONLY_BTC_1D.

Identical to v1.0.0 in every respect except allow_short=False — the SHORT side is
entirely disabled; LONG entry, exit, sizing, and the ADX regime gate are all
completely unchanged. Same STRATEGY_ID (RANGE_MEAN_REVERSION), a new version — this
is a pure parameter variant (allow_short is a v1.0.0 field precisely so this doesn't
require forking any strategy logic), registered once and run against both assets in
Stage 1 rather than registering a separate version per asset.
"""
from __future__ import annotations

from dataclasses import asdict, replace

from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS, STRATEGY_ID
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "range-mean-reversion-v1.1.0-long-only"

LONG_ONLY_PARAMETERS = replace(DEFAULT_PARAMETERS, allow_short=False)

STRATEGY_DESCRIPTION = (
    "Identical to RANGE_MEAN_REVERSION range-mean-reversion-v1.0.0 in every respect "
    "except the SHORT side is disabled entirely (allow_short=False) — LONG entry, "
    "exit, sizing, and the ADX regime gate are all unchanged. RMR Variant Research "
    "Cycle, Stage 1: tests whether the short leg is a net cost or a net contributor, "
    "on EUR/USD/4h and BTC/1d."
)


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the long-only variant. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(LONG_ONLY_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
