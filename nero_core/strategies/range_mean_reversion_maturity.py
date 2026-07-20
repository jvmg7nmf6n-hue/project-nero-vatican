"""RANGE_MEAN_REVERSION range-maturity variant (v1.5.0) — Ranging-Regime Research
Batch, Hypothesis R2: RANGE_MATURITY.

MECHANISM: RMR's own closing report found its only PROMISING-WATCHLIST results were
on weekly precious metals — the slowest, most "mature" ranges the whole cycle tested.
This variant asks whether range AGE, not entry timing, is the missing variable:
identical to v1.0.0 in every other respect (SMA20/Bollinger 20-2.0 entry,
direction-aware SMA exit, ADX>=28-for-2-closed-candles regime-break exit, 2.0xATR
disaster stop), plus ONE new gate layered on top of v1.0.0's own evaluate_entry: the
regime must have been continuously RANGING (ADX < 25) for at least
mature_range_min_candles CLOSED candles immediately before the entry candle — not
merely ranging AT the entry candle, which is all v1.0.0 itself checks.

mature_range_min_candles is timeframe-scaled, per the task spec: 20 for 4h/1d configs
(the default here), 8 for 1week configs (20 weekly candles would be ~5 months of
continuous range, emptying the sample; 8 weeks is mature but achievable) — set at
call time via dataclasses.replace, exactly like every other per-timeframe
calibration in this project.

Reuses v1.0.0's add_indicators, evaluate_exit, and size_entry completely unchanged —
only entry adds the maturity gate. RangeMaturityState subclasses
RangeMeanReversionState with one extra field (consecutive_ranging_bars), updated
every candle from that candle's own ADX (mirrors v1.0.0's own
consecutive_high_adx_bars update-every-candle convention, just counting the opposite
condition: LOW adx, not high).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from nero_core.strategies.mean_reversion import reset_daily_guard_if_needed
from nero_core.strategies.range_mean_reversion import (
    DEFAULT_PARAMETERS,
    STRATEGY_ID,
    EntryEvaluation,
    RangeMeanReversionParameters,
    RangeMeanReversionState,
    evaluate_entry,
    evaluate_exit,
    size_entry,
)
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry

STRATEGY_VERSION = "range-mean-reversion-v1.5.0-range-maturity"

STRATEGY_DESCRIPTION = (
    "Adds a range-maturity gate on top of v1.0.0's own entry: requires ADX < 25 for "
    "at least mature_range_min_candles CONSECUTIVE closed candles immediately before "
    "the entry candle (not merely at the entry candle, which is all v1.0.0 checks). "
    "mature_range_min_candles=20 by default (4h/1d configs); set to 8 for 1week runs "
    "via dataclasses.replace. Everything else (bands, exits, sizing) is identical to "
    "v1.0.0. Ranging-Regime Research Batch, Hypothesis R2: does range AGE fix "
    "reversion?"
)


@dataclass(frozen=True)
class RangeMaturityParameters(RangeMeanReversionParameters):
    mature_range_min_candles: int = 20


DEFAULT_MATURITY_PARAMETERS = RangeMaturityParameters()


@dataclass
class RangeMaturityState(RangeMeanReversionState):
    consecutive_ranging_bars: int = 0


def evaluate_maturity_entry(
    candle: pd.Series, state: RangeMaturityState, params: RangeMaturityParameters = DEFAULT_MATURITY_PARAMETERS,
) -> EntryEvaluation:
    """Wraps v1.0.0's own evaluate_entry unchanged, adding exactly one new rejection
    reason (NOT_MATURE_ENOUGH) if the ranging streak preceding this candle (as
    tracked in state.consecutive_ranging_bars) is below the maturity bar. Never
    overrides any of v1.0.0's own checks or reasons."""
    base = evaluate_entry(candle, state, params)
    if state.consecutive_ranging_bars < params.mature_range_min_candles:
        reasons = base.reasons + ("NOT_MATURE_ENOUGH",)
        return replace(base, passed=False, direction=None, reasons=reasons)
    return base


def run_backtest(
    evaluable: pd.DataFrame, params: RangeMaturityParameters = DEFAULT_MATURITY_PARAMETERS,
) -> tuple[list, RangeMaturityState]:
    state = RangeMaturityState(equity=params.initial_equity)
    closed_trades: list = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)  # v1.0.0's own, unchanged
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_maturity_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params, evaluation.direction)
            if trade is not None:
                state.open_trade = trade

        # Streak counter for the NEXT candle's maturity check, from THIS candle's own
        # ADX — mirrors v1.0.0's own consecutive_high_adx_bars update-every-candle
        # convention (inverted: counts LOW adx, not high).
        adx_value = candle.get("adx")
        if adx_value is not None and not pd.isna(adx_value) and float(adx_value) < params.adx_entry_threshold:
            state.consecutive_ranging_bars += 1
        else:
            state.consecutive_ranging_bars = 0

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the range-maturity variant. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_MATURITY_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
