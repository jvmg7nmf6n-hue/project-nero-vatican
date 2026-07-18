"""Filter-test variant of TREND_PULLBACK (trend-pullback-v1.0.0): IDENTICAL entry
conditions, disaster stop, target, and max-holding cap — see
nero_core.strategies.trend_pullback for those; `size_entry` and `evaluate_exit` are
reused completely unchanged. ONE additional entry requirement is added: at least one
OPEN bullish FVG (see nero_core.strategies.fvg_detection) whose remaining zone
overlaps the low-to-high range of the last `fvg_overlap_lookback_candles` (10) candles
— the idea being "price is currently sitting near an unfilled gap," a confluence check
layered on top of the existing pullback-to-MA50 trigger, not a replacement for it.

This is a Task C filter test (see docs/fvg_bos_research_batch_report.md): does this
filter raise per-trade quality, or does it just shrink the sample? Compared against
unfiltered v1 on identical data through the upgraded harness.

Registered as `trend-pullback-v1.3.0-fvg-filtered` — v1.1.0/v1.2.0 are already taken by
the regime-scaled-risk and trail-exit variants; this is a genuinely new version, never
a mutation of any existing one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.fvg_detection import any_bullish_gap_overlaps_range, attach_fvg_columns
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.trend_pullback import STRATEGY_ID
from nero_core.strategies.trend_pullback import TrendPullbackParameters
from nero_core.strategies.trend_pullback import add_indicators as base_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry as base_evaluate_entry
from nero_core.strategies.trend_pullback import size_entry

STRATEGY_VERSION = "trend-pullback-v1.3.0-fvg-filtered"
OVERLAP_LOOKBACK_CANDLES = 10

STRATEGY_DESCRIPTION = (
    "Filter-test variant of TREND_PULLBACK trend-pullback-v1.0.0: IDENTICAL entry "
    "conditions, disaster stop, target, and max-holding cap — size_entry and "
    "evaluate_exit are reused completely unchanged. Adds exactly ONE additional entry "
    "requirement: at least one OPEN bullish FVG (nero_core.strategies.fvg_detection) "
    "whose remaining zone overlaps the low-to-high range of the last 10 candles. Task "
    "C filter test: does this raise per-trade quality, or just shrink the sample?"
)


@dataclass(frozen=True)
class TrendPullbackFvgFilteredParameters(TrendPullbackParameters):
    fvg_overlap_lookback_candles: int = OVERLAP_LOOKBACK_CANDLES


DEFAULT_PARAMETERS = TrendPullbackFvgFilteredParameters()

INDICATOR_COLUMNS_TO_CHECK = ["ma50", "ma200", "rsi", "atr", "range_low_10", "range_high_10"]


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int


def add_indicators(candles: pd.DataFrame, params: TrendPullbackFvgFilteredParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    enriched = attach_fvg_columns(enriched)
    lookback = params.fvg_overlap_lookback_candles
    enriched["range_low_10"] = enriched["low"].rolling(lookback).min()
    enriched["range_high_10"] = enriched["high"].rolling(lookback).max()
    return enriched


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: TrendPullbackFvgFilteredParameters = DEFAULT_PARAMETERS
) -> EntryEvaluation:
    base_eval = base_evaluate_entry(candle, state, params)
    reasons = list(base_eval.reasons)

    range_low = candle.get("range_low_10")
    range_high = candle.get("range_high_10")
    if range_low is None or range_high is None or pd.isna(range_low) or pd.isna(range_high):
        reasons.append("RECENT_RANGE_NOT_YET_AVAILABLE")
    else:
        open_bullish_gaps = candle.get("fvg_open_bullish_gaps") or ()
        if not any_bullish_gap_overlaps_range(open_bullish_gaps, float(range_low), float(range_high)):
            reasons.append("NO_OPEN_FVG_OVERLAPPING_RECENT_RANGE")

    return EntryEvaluation(passed=not reasons, reasons=tuple(reasons), candle_close_time=int(candle["close_time"]))


def run_backtest(
    evaluable: pd.DataFrame, params: TrendPullbackFvgFilteredParameters = DEFAULT_PARAMETERS
):
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


def register_default_variant(registry: StrategyRegistry = default_registry) -> StrategyVariant:
    """Register the FVG-filtered variant. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry — a new version, never a mutation of any
    existing one."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
