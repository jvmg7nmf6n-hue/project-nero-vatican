"""Backtest integration hook for the H2 volatility-clustering position-sizing
hypothesis (nero_core.quant.vol_regime) — lets any existing single-asset strategy
(a tools.backtest_compare.VariantSpec) be run multiplier-on vs multiplier-off through
the same candle-by-candle loop backtest_compare.run_backtest already uses, so the two
runs are otherwise byte-for-byte identical except for position sizing at entry.

Only risk_per_trade is scaled by the multiplier at the moment of sizing — stop
distance (atr_stop_multiple, or whatever a given strategy's own stop rule is) is
completely untouched, since it's derived from ATR/price structure, not risk_per_trade.
evaluate_exit is always called with the strategy's own unscaled params for the same
reason. No lookahead: the cluster score at candle i is computed only from closes up to
and including i.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from nero_core.quant.vol_regime import position_multiplier, volatility_cluster_score
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, BacktestMetrics, VariantSpec, compute_metrics

DEFAULT_CLUSTER_LOOKBACK = 100


def run_variant_with_multiplier(
    intraday: pd.DataFrame,
    spec: VariantSpec,
    multiplier_on: bool,
    daily: pd.DataFrame | None = None,
    asset: str = "",
    cluster_lookback: int = DEFAULT_CLUSTER_LOOKBACK,
) -> tuple[list[Any], MeanReversionState]:
    """Same loop shape as backtest_compare.run_backtest. When `multiplier_on` is True,
    every entry's sizing call gets a params clone with risk_per_trade scaled by
    position_multiplier(volatility_cluster_score(...)) computed from closes strictly
    up to and including the entry candle — evaluate_exit and entry evaluation both still
    use the strategy's own unscaled params."""
    state = MeanReversionState(equity=spec.params.initial_equity)
    enriched = spec.add_indicators_fn(intraday, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list[Any] = []
    use_daily = spec.needs_daily and daily is not None

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, spec.params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        as_of_intraday = evaluable.iloc[: i + 1]
        as_of_daily = daily[daily["close_time"] <= candle["close_time"]] if use_daily else None
        evaluation = spec.evaluate_entry_fn(candle, as_of_intraday, as_of_daily, state, spec.params, asset)

        if evaluation.passed:
            sizing_params = spec.params
            if multiplier_on:
                closes_as_of = evaluable["close"].iloc[max(0, i + 1 - cluster_lookback) : i + 1]
                score = volatility_cluster_score(closes_as_of, lookback=cluster_lookback)
                multiplier = position_multiplier(score)
                sizing_params = replace(spec.params, risk_per_trade=spec.params.risk_per_trade * multiplier)
            trade = spec.size_entry_fn(candle, state, sizing_params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state


@dataclass(frozen=True)
class MultiplierComparison:
    asset: str
    variant: str
    off: BacktestMetrics
    on: BacktestMetrics

    @property
    def expectancy_r_delta(self) -> float:
        return self.on.expectancy_r - self.off.expectancy_r

    @property
    def win_rate_delta(self) -> float:
        return self.on.win_rate - self.off.win_rate

    @property
    def max_drawdown_delta(self) -> float:
        return self.on.max_drawdown - self.off.max_drawdown


def compare_multiplier_on_off(
    intraday: pd.DataFrame,
    spec: VariantSpec,
    daily: pd.DataFrame | None = None,
    asset: str = "",
    cluster_lookback: int = DEFAULT_CLUSTER_LOOKBACK,
) -> MultiplierComparison:
    """Runs the same variant/data twice (multiplier off, then on) and returns both
    BacktestMetrics plus the deltas a comparative report needs."""
    off_trades, off_state = run_variant_with_multiplier(
        intraday, spec, multiplier_on=False, daily=daily, asset=asset, cluster_lookback=cluster_lookback
    )
    on_trades, on_state = run_variant_with_multiplier(
        intraday, spec, multiplier_on=True, daily=daily, asset=asset, cluster_lookback=cluster_lookback
    )
    off_metrics = compute_metrics(asset, f"{spec.label} (multiplier OFF)", off_state, off_trades)
    on_metrics = compute_metrics(asset, f"{spec.label} (multiplier ON)", on_state, on_trades)
    return MultiplierComparison(asset=asset, variant=spec.label, off=off_metrics, on=on_metrics)
