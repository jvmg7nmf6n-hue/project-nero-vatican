"""ADX(14)-gated variant of TREND_PULLBACK trend-pullback-v1.0.0 — Ranging-Regime
Research Batch, Hypothesis R3(b): REGIME_ALLOCATOR.

MECHANISM: same as R3(a) (breakout_momentum_gold_calibrated_1week_adx_gated.py) —
"if regime-detection is the real skill, it should improve strategies we already
trust." IDENTICAL entry conditions (established uptrend, pullback-to-MA50, RSI
40-60), 1.5x ATR stop, 2.0x ATR target, and timeframe-aware holding cap to the
already-verified, LIVE trend-pullback-v1.0.0 — the ONLY change is one new gate:
entry additionally requires ADX(14) >= 20 at the signal candle (reusing
range_mean_reversion.adx()).

APPEND-ONLY, NON-DESTRUCTIVE: a brand new registered version
(trend-pullback-v1.1.0-adx-gated). The live trend-pullback-v1.0.0 registration in
nero_core.strategies.trend_pullback is never touched — only its parameter VALUES are
copied as a starting point.

Compared against a FRESH re-run of the ungated base variant on the SAME data window
in tools/trend_pullback_adx_gate_sweep.py. Framed neutrally: either outcome is useful.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import pandas as pd

from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.range_mean_reversion import adx
from nero_core.strategies.registry import StrategyRegistry, StrategyVariant, default_registry
from nero_core.strategies.trend_pullback import STRATEGY_ID
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as BASE_PARAMETERS
from nero_core.strategies.trend_pullback import EntryEvaluation
from nero_core.strategies.trend_pullback import TrendPullbackParameters
from nero_core.strategies.trend_pullback import add_indicators as base_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry as base_evaluate_entry
from nero_core.strategies.trend_pullback import size_entry

STRATEGY_VERSION = "trend-pullback-v1.1.0-adx-gated"


@dataclass(frozen=True)
class TrendPullbackAdxGatedParameters(TrendPullbackParameters):
    adx_period: int = 14
    adx_gate_threshold: float = 20.0


DEFAULT_PARAMETERS = TrendPullbackAdxGatedParameters(
    **asdict(BASE_PARAMETERS), adx_period=14, adx_gate_threshold=20.0
)

STRATEGY_DESCRIPTION = (
    "Identical to trend-pullback-v1.0.0 (same entry/exit rules, same sizing) plus ONE "
    "new gate: entry additionally requires ADX(14) >= 20 at the signal candle "
    "(reusing range_mean_reversion.adx()). Tests whether regime-gating improves an "
    "already-verified, live survivor. Ranging-Regime Research Batch, Hypothesis "
    "R3(b): REGIME_ALLOCATOR."
)


def add_indicators(
    candles: pd.DataFrame, params: TrendPullbackAdxGatedParameters = DEFAULT_PARAMETERS
) -> pd.DataFrame:
    enriched = base_add_indicators(candles, params)
    enriched["adx"] = adx(enriched, params.adx_period)
    return enriched


def evaluate_entry(
    candle: pd.Series, state: MeanReversionState, params: TrendPullbackAdxGatedParameters = DEFAULT_PARAMETERS,
) -> EntryEvaluation:
    """Wraps trend_pullback.evaluate_entry unchanged, adding exactly one new
    rejection reason (ADX_GATE_NOT_MET)."""
    base = base_evaluate_entry(candle, state, params)
    adx_value = candle.get("adx")
    if adx_value is None or pd.isna(adx_value) or float(adx_value) < params.adx_gate_threshold:
        reasons = base.reasons + ("ADX_GATE_NOT_MET",)
        return replace(base, passed=False, reasons=reasons)
    return base


def run_backtest(
    evaluable: pd.DataFrame, params: TrendPullbackAdxGatedParameters = DEFAULT_PARAMETERS,
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
    """Register the ADX-gated Trend Pullback variant. Raises
    StrategyAlreadyRegisteredError if called twice on the same registry. Does NOT
    touch the existing trend-pullback-v1.0.0 registration — append-only."""
    return registry.register(
        strategy_id=STRATEGY_ID, version=STRATEGY_VERSION,
        parameters=asdict(DEFAULT_PARAMETERS), description=STRATEGY_DESCRIPTION,
    )
