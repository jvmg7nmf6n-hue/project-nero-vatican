"""Filter-test variant of TREND_PULLBACK (trend-pullback-v1.0.0): IDENTICAL entry
conditions, disaster stop, target, and max-holding cap — see
nero_core.strategies.trend_pullback for those; `size_entry` and `evaluate_exit` are
reused completely unchanged. ONE additional entry requirement is added: at least one
BOS-up (see nero_core.strategies.bos_detection) occurred within the last
`bos_recency_lookback_candles` (20) candles — the idea being "the broader market
structure recently confirmed an uptrend break," a confluence check layered on top of
the existing pullback-to-MA50 trigger, not a replacement for it.

This is a Task C filter test (see docs/fvg_bos_research_batch_report.md): does this
filter raise per-trade quality, or does it just shrink the sample? Compared against
unfiltered v1 on identical data through the upgraded harness.

Registered as `trend-pullback-v1.4.0-bos-filtered` — v1.1.0/v1.2.0/v1.3.0 are already
taken by the regime-scaled-risk, trail-exit, and FVG-filtered variants; this is a
genuinely new version, never a mutation of any existing one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from nero_core.strategies.bos_detection import attach_bos_columns
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.trend_pullback import STRATEGY_ID
from nero_core.strategies.trend_pullback import TrendPullbackParameters
from nero_core.strategies.trend_pullback import add_indicators as base_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry as base_evaluate_entry
from nero_core.strategies.trend_pullback import size_entry

STRATEGY_VERSION = "trend-pullback-v1.4.0-bos-filtered"
BOS_RECENCY_LOOKBACK_CANDLES = 20

STRATEGY_DESCRIPTION = (
    "Filter-test variant of TREND_PULLBACK trend-pullback-v1.0.0: IDENTICAL entry "
    "conditions, disaster stop, target, and max-holding cap — size_entry and "
    "evaluate_exit are reused completely unchanged. Adds exactly ONE additional entry "
    "requirement: at least one BOS-up (nero_core.strategies.bos_detection) occurred "
    "within the last 20 candles. Task C filter test: does this raise per-trade "
    "quality, or just shrink the sample?"
)


@dataclass(frozen=True)
class TrendPullbackBosFilteredParameters(TrendPullbackParameters):
    bos_recency_lookback_candles: int = BOS_RECENCY_LOOKBACK_CANDLES


DEFAULT_PARAMETERS = TrendPullbackBosFilteredParameters()

INDICATOR_COLUMNS_TO_CHECK = ["ma50", "ma200", "rsi", "atr"]


@dataclass(frozen=True)
class EntryEvaluation:
    passed: bool
    reasons: tuple[str, ...]
    candle_close_time: int


def add_indicators(candles: pd.DataFrame, params: TrendPullbackBosFilteredParameters = DEFAULT_PARAMETERS) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    return attach_bos_columns(enriched)


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: TrendPullbackBosFilteredParameters = DEFAULT_PARAMETERS
) -> EntryEvaluation:
    base_eval = base_evaluate_entry(candle, state, params)
    reasons = list(base_eval.reasons)

    recent_bos_up_index = candle.get("bos_up_recent_index")
    current_index = candle.name  # positional index within the evaluable frame (set by caller via .iloc/reset_index)
    if recent_bos_up_index is None or pd.isna(recent_bos_up_index):
        reasons.append("NO_BOS_UP_YET")
    elif (current_index - recent_bos_up_index) > params.bos_recency_lookback_candles:
        reasons.append("BOS_UP_TOO_STALE")

    return EntryEvaluation(passed=not reasons, reasons=tuple(reasons), candle_close_time=int(candle["close_time"]))


def run_backtest(
    evaluable: pd.DataFrame, params: TrendPullbackBosFilteredParameters = DEFAULT_PARAMETERS
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
    """Register the BOS-filtered variant. Raises StrategyAlreadyRegisteredError if
    called twice on the same registry — a new version, never a mutation of any
    existing one."""
    return registry.register(
        strategy_id=STRATEGY_ID,
        version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS),
        description=STRATEGY_DESCRIPTION,
    )
