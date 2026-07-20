"""CLI: REGIME_ALLOCATOR (Ranging-Regime Research Batch, Hypothesis R3) — ADX(14)>=20
regime-gated variants of two already-verified, LIVE survivors vs a FRESH ungated
baseline re-run on the SAME data window.

  (a) BREAKOUT_MOMENTUM GOLD/1week: breakout-momentum-v1.2.0-gold-calibrated-1week
      (live, wired into live_scheduler.SINGLE_ASSET_CONFIGS) vs
      breakout-momentum-v1.6.0-gold-calibrated-1week-adx-gated.
  (b) TREND_PULLBACK BNB/12h: trend-pullback-v1.0.0 (live) vs
      trend-pullback-v1.1.0-adx-gated.

Neither the live base variant's registration nor its module code is touched anywhere
in this batch — append-only, new versions only (see both *_adx_gated.py modules'
own docstrings).

NO RANDOM-ENTRY BASELINE HERE, BY DESIGN: unlike R1/R2 (which test whether a NEW
regime-detection mechanism beats a "trade randomly within the regime pool" null),
R3's question is narrower and doesn't have an equivalent null to construct — these
are already-directional, already-verified strategies; the relevant control IS the
fresh ungated baseline itself, run on the identical window. Bootstrap CI is still
applied to both sides for the same statistical-confidence read RMR/R1/R2 use.

No synthetic/fabricated price data — a failed fetch is reported SKIPPED with reason.

Usage:
    python -m tools.regime_allocator_sweep
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.breakout_momentum import add_indicators as bm_add_indicators
from nero_core.strategies.breakout_momentum import evaluate_entry as bm_evaluate_entry
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import GOLD_CALIBRATED_1WEEK_PARAMETERS
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_adx_gated import (
    DEFAULT_PARAMETERS as BM_GATED_PARAMETERS,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_adx_gated import (
    add_indicators as bm_gated_add_indicators,
)
from nero_core.strategies.breakout_momentum_gold_calibrated_1week_adx_gated import (
    run_backtest as bm_gated_run_backtest,
)
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from nero_core.strategies.trend_pullback import DEFAULT_PARAMETERS as TP_PARAMETERS
from nero_core.strategies.trend_pullback import add_indicators as tp_add_indicators
from nero_core.strategies.trend_pullback import evaluate_entry as tp_evaluate_entry
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from nero_core.strategies.trend_pullback_adx_gated import DEFAULT_PARAMETERS as TP_GATED_PARAMETERS
from nero_core.strategies.trend_pullback_adx_gated import add_indicators as tp_gated_add_indicators
from nero_core.strategies.trend_pullback_adx_gated import run_backtest as tp_gated_run_backtest

# trend_pullback's registered params are a 1h-reference default (max_holding_hours=24)
# -- MUST be recalibrated for 12h candles before use, same bug class the GOLD 1week
# fix addressed and tools.backtest_survivor_verification's own BNB/12h config already
# flags ("needs_timeframe_calibration": True) -- skipping this forces nearly every
# trade closed via TIME after just 2 candles, corrupting the comparison.
BNB_TIMEFRAME = "12h"
from tools.backtest_statistics import MIN_SAMPLE_SIZE, bootstrap_mean_r_ci, classify_verdict
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles


def _run_backtest_bm_ungated(evaluable: pd.DataFrame, params) -> tuple[list, MeanReversionState]:
    """breakout_momentum.py itself defines no run_backtest (the loop normally lives in
    a generic shared driver) — a small local loop, same shape as every sibling
    variant module's own run_backtest in this project."""
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades: list = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])
        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)
        evaluation = bm_evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = bm_size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade
    return closed_trades, state


def _run_backtest_tp_ungated(evaluable: pd.DataFrame, params) -> tuple[list, MeanReversionState]:
    state = MeanReversionState(equity=params.initial_equity)
    closed_trades: list = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])
        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            closed_trades.append(exit_event)
        evaluation = tp_evaluate_entry(candle, state, params)
        if evaluation.passed:
            trade = tp_size_entry(candle, state, params)
            if trade is not None:
                state.open_trade = trade
    return closed_trades, state


def _half_stats(half_candles: pd.DataFrame, add_indicators_fn, indicator_cols, run_backtest_fn, params) -> dict[str, object]:
    enriched = add_indicators_fn(half_candles, params)
    evaluable = enriched.dropna(subset=indicator_cols).reset_index(drop=True)
    trades, _state = run_backtest_fn(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    ci = bootstrap_mean_r_ci(r_values)
    return {"trades": len(trades), "expectancy_r": expectancy_r, "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci}


def run_breakout_momentum_gold_1week() -> dict[str, object]:
    client = MarketDataClient()
    try:
        candles, method = fetch_timeframe_candles(client, "GOLD", "1week")
    except MarketDataUnavailableError as exc:
        return {"label": "BREAKOUT_MOMENTUM GOLD/1week", "error": str(exc)}

    start = time.monotonic()
    train, test = split_chronological(candles)
    ungated_cols = ["ma200", "rsi", "atr", "breakout_high"]
    gated_cols = ungated_cols + ["adx"]

    ungated_train = _half_stats(train, bm_add_indicators, ungated_cols, _run_backtest_bm_ungated, GOLD_CALIBRATED_1WEEK_PARAMETERS)
    ungated_test = _half_stats(test, bm_add_indicators, ungated_cols, _run_backtest_bm_ungated, GOLD_CALIBRATED_1WEEK_PARAMETERS)
    gated_train = _half_stats(train, bm_gated_add_indicators, gated_cols, bm_gated_run_backtest, BM_GATED_PARAMETERS)
    gated_test = _half_stats(test, bm_gated_add_indicators, gated_cols, bm_gated_run_backtest, BM_GATED_PARAMETERS)
    elapsed = time.monotonic() - start
    print(f"BREAKOUT_MOMENTUM GOLD/1week: done ({elapsed:.1f}s, {len(candles)} candles)")

    return {
        "label": "BREAKOUT_MOMENTUM GOLD/1week", "candle_count": len(candles), "method": method,
        "ungated_train": ungated_train, "ungated_test": ungated_test,
        "ungated_verdict": classify_verdict(ungated_train, ungated_test),
        "gated_train": gated_train, "gated_test": gated_test,
        "gated_verdict": classify_verdict(gated_train, gated_test),
    }


def run_trend_pullback_bnb_12h() -> dict[str, object]:
    client = MarketDataClient()
    try:
        candles, method = fetch_timeframe_candles(client, "BNB", "12h")
    except MarketDataUnavailableError as exc:
        return {"label": "TREND_PULLBACK BNB/12h", "error": str(exc)}

    start = time.monotonic()
    train, test = split_chronological(candles)
    ungated_cols = ["ma50", "ma200", "rsi", "atr"]
    gated_cols = ungated_cols + ["adx"]

    ungated_params = build_calibrated_params(TP_PARAMETERS, BNB_TIMEFRAME, "BNB")
    gated_params = build_calibrated_params(TP_GATED_PARAMETERS, BNB_TIMEFRAME, "BNB")

    ungated_train = _half_stats(train, tp_add_indicators, ungated_cols, _run_backtest_tp_ungated, ungated_params)
    ungated_test = _half_stats(test, tp_add_indicators, ungated_cols, _run_backtest_tp_ungated, ungated_params)
    gated_train = _half_stats(train, tp_gated_add_indicators, gated_cols, tp_gated_run_backtest, gated_params)
    gated_test = _half_stats(test, tp_gated_add_indicators, gated_cols, tp_gated_run_backtest, gated_params)
    elapsed = time.monotonic() - start
    print(f"TREND_PULLBACK BNB/12h: done ({elapsed:.1f}s, {len(candles)} candles)")

    return {
        "label": "TREND_PULLBACK BNB/12h", "candle_count": len(candles), "method": method,
        "ungated_train": ungated_train, "ungated_test": ungated_test,
        "ungated_verdict": classify_verdict(ungated_train, ungated_test),
        "gated_train": gated_train, "gated_test": gated_test,
        "gated_verdict": classify_verdict(gated_train, gated_test),
    }


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    ci = stats["ci"]
    ci_str = f", CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{ci_str}"


def format_report(bm_result: dict[str, object], tp_result: dict[str, object]) -> str:
    lines = ["=== REGIME_ALLOCATOR (R3) — gated vs fresh ungated baseline ===", ""]
    for r in (bm_result, tp_result):
        if "error" in r:
            lines.append(f"{r['label']}: SKIPPED — {r['error']}")
            lines.append("")
            continue
        lines.append(f"{r['label']} ({r['candle_count']} candles, {r['method']}):")
        lines.append(f"  UNGATED: {r['ungated_verdict']} — TRAIN {_fmt_half(r['ungated_train'])} | TEST {_fmt_half(r['ungated_test'])}")
        lines.append(f"  GATED:   {r['gated_verdict']} — TRAIN {_fmt_half(r['gated_train'])} | TEST {_fmt_half(r['gated_test'])}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    bm_result = run_breakout_momentum_gold_1week()
    tp_result = run_trend_pullback_bnb_12h()
    print()
    print(format_report(bm_result, tp_result))


if __name__ == "__main__":
    main()
