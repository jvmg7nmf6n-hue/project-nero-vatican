"""ADX(14)-gated variant of BREAKOUT_MOMENTUM breakout-momentum-v1.2.0-gold-
calibrated-1week — Ranging-Regime Research Batch, Hypothesis R3(a): REGIME_ALLOCATOR.

MECHANISM: "if regime-detection is the real skill (per R1/R2's own testing), it
should improve strategies we already trust." IDENTICAL entry conditions, GOLD fee
calibration, 1.2x ATR stop, 1.25R target, and the 1week-corrected max_holding_hours
to the already-verified, LIVE base variant — the ONLY change is one new gate: entry
additionally requires ADX(14) >= 20 at the signal candle (reusing
range_mean_reversion.adx(), not a new ADX implementation).

APPEND-ONLY, NON-DESTRUCTIVE: this is a brand new registered version
(breakout-momentum-v1.6.0-gold-calibrated-1week-adx-gated — v1.3.0-v1.5.0 already
taken by the volume-confirmed and trail-exit variants). The live, verified
breakout-momentum-v1.2.0-gold-calibrated-1week registration in
nero_core.strategies.breakout_momentum_gold_calibrated_1week is NEVER imported for
mutation here, only its parameter VALUES are copied as a starting point (dataclasses
are immutable; there is nothing to accidentally mutate) — its own registration call
is untouched.

Compared against a FRESH re-run of the ungated base variant on the SAME data window
(never a stale comparison) in tools/breakout_momentum_gold_1week_adx_gate_sweep.py.
Framed neutrally, per the task: either outcome (gating helps, or it doesn't) is
useful information.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from nero_core.strategies.breakout_momentum import STRATEGY_ID
from nero_core.strategies.breakout_momentum import BreakoutMomentumParameters
from nero_core.strategies.breakout_momentum import EntryEvaluation
from nero_core.strategies.breakout_momentum import add_indicators as base_add_indicators
from nero_core.strategies.breakout_momentum import evaluate_entry as base_evaluate_entry
from nero_core.strategies.breakout_momentum import size_entry
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import GOLD_CALIBRATED_1WEEK_PARAMETERS
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.range_mean_reversion import adx
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "breakout-momentum-v1.6.0-gold-calibrated-1week-adx-gated"


@dataclass(frozen=True)
class BreakoutMomentumAdxGatedParameters(BreakoutMomentumParameters):
    adx_period: int = 14
    adx_gate_threshold: float = 20.0


DEFAULT_PARAMETERS = BreakoutMomentumAdxGatedParameters(
    **asdict(GOLD_CALIBRATED_1WEEK_PARAMETERS), adx_period=14, adx_gate_threshold=20.0
)

STRATEGY_DESCRIPTION = (
    "Identical to breakout-momentum-v1.2.0-gold-calibrated-1week (same entry/exit "
    "rules, same GOLD fee calibration, same 1week-corrected holding cap) plus ONE new "
    "gate: entry additionally requires ADX(14) >= 20 at the signal candle (reusing "
    "range_mean_reversion.adx()). Tests whether regime-gating improves an "
    "already-verified, live survivor. Ranging-Regime Research Batch, Hypothesis "
    "R3(a): REGIME_ALLOCATOR."
)


def add_indicators(
    candles: pd.DataFrame, params: BreakoutMomentumAdxGatedParameters = DEFAULT_PARAMETERS
) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    enriched["adx"] = adx(enriched, params.adx_period)
    return enriched


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: BreakoutMomentumAdxGatedParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Wraps breakout_momentum.evaluate_entry unchanged, adding exactly one new
    rejection reason (ADX_GATE_NOT_MET) — never overrides any of the base module's
    own checks or reasons."""
    base = base_evaluate_entry(candle, state, params)
    adx_value = candle.get("adx")
    if adx_value is None or pd.isna(adx_value) or float(adx_value) < params.adx_gate_threshold:
        reasons = base.reasons + ("ADX_GATE_NOT_MET",)
        return replace(base, passed=False, reasons=reasons)
    return base


def run_backtest(
    evaluable: pd.DataFrame, params: BreakoutMomentumAdxGatedParameters = DEFAULT_PARAMETERS,
) -> tuple[list, MeanReversionState]:
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades: list = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)  # reused unchanged
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params)  # reused unchanged
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the ADX-gated GOLD/1week Breakout Momentum variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry. Does NOT
    touch the existing breakout-momentum-v1.2.0-gold-calibrated-1week registration —
    append-only."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
