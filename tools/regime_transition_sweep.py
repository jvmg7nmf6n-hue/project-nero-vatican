"""CLI: REGIME_TRANSITION (Ranging-Regime Research Batch, Hypothesis R1) — asset/
timeframe sweep with the batch's mandated "upgraded harness": chronological 70/30
split, bootstrap 95% CI, AND a random-entry baseline.

RANDOM-ENTRY BASELINE FOR R1 SPECIFICALLY: R1's mechanism has two independent
components — (a) a mature range ENDING (the regime-transition condition: a >= 10
candle ADX<25 streak broken by an ADX cross to >= 25), and (b) the ENDING candle's
close actually clearing the frozen boundary (the directional trigger). The random
baseline isolates (b)'s value: `mature_range_candidates` finds every candle where (a)
alone fires — a strict SUPERSET of the real strategy's actual entries, since it drops
the boundary-clearing requirement — then `transition_random_baseline` fires a
random-direction entry (LONG/SHORT 50/50) at a random subset of that pool (matched to
the real trade count), executed and exited through the exact same mechanics
(size_transition_entry / evaluate_exit). If the real, boundary-triggered entries don't
beat this baseline, the "regime ending" alone is doing the work and the direction
check adds nothing — the same "is the entry timing beating the pure regime filter"
question RANGE_MEAN_REVERSION's own random baseline asked, adapted to R1's
mechanism.

ASSETS/TIMEFRAMES (targeted, per the task spec, not a further sweep):
  BTC, ETH:      4h, 12h, 1d(="24h")
  GOLD, SILVER:  1d(="24h"), 1week
  EURUSD, USDJPY: 4h, 1d

FEES: forex flat 0.05%/2bps (matching every prior batch's forex convention); metals
via scaled_fees_for_asset; crypto unscaled default. max_holding_hours is re-derived
per timeframe (24 candles, converted to hours) exactly like every other strategy in
this project — never left at its 1h-reference default.

No synthetic/fabricated price data — a failed fetch is reported SKIPPED with reason.

Usage:
    python -m tools.regime_transition_sweep
"""
from __future__ import annotations

import random
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.mean_reversion import reset_daily_guard_if_needed
from nero_core.strategies.regime_transition import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    PendingSignal,
    RegimeTransitionParameters,
    RegimeTransitionState,
    add_indicators,
    evaluate_exit,
    run_backtest,
    size_transition_entry,
)
from nero_core.strategies.timeframe_calibration import scaled_fees_for_asset
from tools.backtest_statistics import (
    MIN_SAMPLE_SIZE,
    RANDOM_ENTRY_RUNS,
    RANDOM_ENTRY_SEED,
    RandomBaselineResult,
    _percentile,
    bootstrap_mean_r_ci,
    classify_verdict,
)
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

FOREX_PAIR_BY_ASSET = {"EURUSD": "EUR/USD", "USDJPY": "USD/JPY"}
FOREX_ASSETS = list(FOREX_PAIR_BY_ASSET)
FOREX_FEE_BPS = 5.0  # 0.05% per side, matching every prior batch's forex convention
FOREX_SLIPPAGE_BPS = 2.0
# display timeframe -> (Twelve Data interval, hours-per-candle)
FOREX_TIMEFRAMES = {"4h": ("4h", 4), "1d": ("1day", 24)}

METALS = ["GOLD", "SILVER"]
METALS_TIMEFRAMES = {"1d": ("24h", 24), "1week": ("1week", 168)}  # display -> (pipeline key, hours/candle)

CRYPTO = ["BTC", "ETH"]
CRYPTO_TIMEFRAMES = {"4h": ("4h", 4), "12h": ("12h", 12), "1d": ("24h", 24)}


def calibrated_params_for(asset: str, hours_per_candle: int) -> RegimeTransitionParameters:
    base = replace(DEFAULT_PARAMETERS, max_holding_hours=hours_per_candle * 24)  # 24-candle cap, re-derived
    if asset in FOREX_ASSETS:
        return replace(base, fee_bps=FOREX_FEE_BPS, slippage_bps=FOREX_SLIPPAGE_BPS)
    return scaled_fees_for_asset(base, asset)  # GOLD/SILVER scaled; crypto unchanged


def mature_range_candidates(evaluable: pd.DataFrame, params: RegimeTransitionParameters) -> list[dict[str, object]]:
    """Every candle where a >= mature_range_min_candles low-ADX streak is broken by an
    ADX cross to >= threshold -- regardless of whether the close clears the frozen
    boundary. A strict superset of the real strategy's actual signals; see module
    docstring."""
    candidates: list[dict[str, object]] = []
    streak_start: int | None = None
    for i in range(len(evaluable)):
        adx_i = evaluable.iloc[i].get("adx")
        if adx_i is None or pd.isna(adx_i):
            continue
        adx_i = float(adx_i)
        if adx_i < params.adx_entry_threshold:
            if streak_start is None:
                streak_start = i
            continue
        if streak_start is not None:
            streak_len = i - streak_start
            if streak_len >= params.mature_range_min_candles:
                window = evaluable.iloc[streak_start:i]
                candidates.append({
                    "index": i,
                    "range_high": float(window["high"].max()),
                    "range_low": float(window["low"].min()),
                    "close": float(evaluable.iloc[i]["close"]),
                })
        streak_start = None
    return candidates


def _simulate_random_transition_entries(
    rows: list[pd.Series], candidates: list[dict[str, object]], params: RegimeTransitionParameters,
    entry_probability: float, rng: random.Random,
) -> list:
    """Bespoke copy of run_backtest's candle loop using RANDOM-direction, randomly-
    selected candidates instead of the deterministic boundary-break trigger. Every
    other mechanic (execution at i+1's open, ceiling/floor stop, target, failed-
    transition exit, holding cap) is identical. `rows` is pre-extracted ONCE by the
    caller (tools.backtest_range_mean_reversion_sweep's own `rows = [evaluable.iloc[i]
    for i in range(len(evaluable))]` pattern) so this — called n_runs times — never
    re-pays pandas' per-row .iloc construction cost on every run."""
    state = RegimeTransitionState(equity=params.initial_equity)
    trades = []
    candidate_by_index = {c["index"]: c for c in candidates if rng.random() < entry_probability}

    for i, candle in enumerate(rows):
        reset_daily_guard_if_needed(state, candle["date"])

        if state.pending_signal is not None:
            if state.open_trade is None:
                trade = size_transition_entry(candle, state.pending_signal, state, params)
                if trade is not None:
                    state.open_trade = trade
            state.pending_signal = None

        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            trades.append(exit_event)

        candidate = candidate_by_index.get(i)
        if candidate is not None and state.open_trade is None and state.pending_signal is None:
            direction = "LONG" if rng.random() < 0.5 else "SHORT"
            state.pending_signal = PendingSignal(
                direction=direction, range_high=candidate["range_high"],
                range_low=candidate["range_low"], breakout_close=candidate["close"],
            )
    return trades


def transition_random_baseline(
    evaluable: pd.DataFrame, candidates: list[dict[str, object]], params: RegimeTransitionParameters,
    real_expectancy_r: float, target_trade_count: int,
    n_runs: int = RANDOM_ENTRY_RUNS, seed: int = RANDOM_ENTRY_SEED,
) -> RandomBaselineResult | None:
    pool_size = len(candidates)
    if pool_size == 0 or target_trade_count <= 0:
        return None
    entry_probability = min(1.0, target_trade_count / pool_size)
    rng = random.Random(seed)
    rows = [evaluable.iloc[i] for i in range(len(evaluable))]  # pre-extracted ONCE, reused across all n_runs
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        trades = _simulate_random_transition_entries(rows, candidates, params, entry_probability, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def _half_stats(half_candles: pd.DataFrame, params: RegimeTransitionParameters) -> dict[str, object]:
    enriched = add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, _state = run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    candidates = mature_range_candidates(evaluable, params)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = transition_random_baseline(evaluable, candidates, params, expectancy_r, len(trades))

    stop_type_counts = {"midpoint": 0, "atr_ceiling": 0, "atr_floor": 0}
    for t in trades:
        stop_type_counts[t.stop_type] = stop_type_counts.get(t.stop_type, 0) + 1
    exit_reason_counts: dict[str, int] = {}
    for t in trades:
        exit_reason_counts[t.exit_reason] = exit_reason_counts.get(t.exit_reason, 0) + 1

    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
        "stop_type_counts": stop_type_counts, "exit_reason_counts": exit_reason_counts,
        "candidate_pool_size": len(candidates),
    }


def _run_config(group: str, asset: str, display_tf: str, candles: pd.DataFrame, method: str,
                 params: RegimeTransitionParameters) -> dict[str, object]:
    start = time.monotonic()
    train, test = split_chronological(candles)
    train_stats = _half_stats(train, params)
    test_stats = _half_stats(test, params)
    elapsed = time.monotonic() - start
    print(f"[{group}] {asset} / {display_tf}: done ({elapsed:.1f}s, {len(candles)} candles, "
          f"train N={train_stats['trades']} test N={test_stats['trades']})")
    return {
        "group": group, "asset": asset, "timeframe": display_tf, "method": method,
        "candle_count": len(candles), "train": train_stats, "test": test_stats,
        "verdict": classify_verdict(train_stats, test_stats),
    }


def run_sweep() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    client = MarketDataClient()

    for asset in CRYPTO:
        for display_tf, (pipeline_tf, hours) in CRYPTO_TIMEFRAMES.items():
            params = calibrated_params_for(asset, hours)
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"[crypto] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"group": "crypto", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("crypto", asset, display_tf, candles, method, params))

    for asset in METALS:
        for display_tf, (pipeline_tf, hours) in METALS_TIMEFRAMES.items():
            params = calibrated_params_for(asset, hours)
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"[metals] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"group": "metals", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("metals", asset, display_tf, candles, method, params))

    for asset in FOREX_ASSETS:
        pair = FOREX_PAIR_BY_ASSET[asset]
        for display_tf, (interval, hours) in FOREX_TIMEFRAMES.items():
            params = calibrated_params_for(asset, hours)
            try:
                result = fetch_forex_ohlcv(pair, interval)
            except ForexDataUnavailableError as exc:
                print(f"[forex] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"group": "forex", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("forex", asset, display_tf, result.prices, result.source, params))

    return rows


def find_qualifying(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        r for r in rows
        if "verdict" in r and r["train"]["trades"] >= MIN_SAMPLE_SIZE and r["test"]["trades"] >= MIN_SAMPLE_SIZE
        and r["train"]["expectancy_r"] > 0 and r["test"]["expectancy_r"] > 0
    ]


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    baseline = stats["baseline"]
    edge = f", edge_over_random={baseline.edge_over_random:.3f}" if baseline is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{edge}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== REGIME_TRANSITION (R1) sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"[{r['group']}] {r['asset']} / {r['timeframe']}: SKIPPED — {r['error']}")
            continue
        lines.append(
            f"[{r['group']}] {r['asset']} / {r['timeframe']}: {r['verdict']} — "
            f"TRAIN {_fmt_half(r['train'])} | TEST {_fmt_half(r['test'])} ({r['candle_count']} candles)"
        )
        lines.append(f"    train stop types: {r['train']['stop_type_counts']} | exit reasons: {r['train']['exit_reason_counts']}")
        lines.append(f"    test  stop types: {r['test']['stop_type_counts']} | exit reasons: {r['test']['exit_reason_counts']}")
    qualifying = find_qualifying(rows)
    lines.append("")
    lines.append(f"=== {len(qualifying)} configs qualify for grid-shift verification ===")
    for r in qualifying:
        lines.append(f"  [{r['group']}] {r['asset']} / {r['timeframe']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
