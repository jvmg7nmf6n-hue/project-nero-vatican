"""CLI: RANGE_MATURITY (Ranging-Regime Research Batch, Hypothesis R2) — v1.5.0's
maturity gate vs a FRESH v1.0.0 baseline, on the SAME data windows (never a stale
comparison, matching RMR Stage 1's own discipline).

ASSETS/TIMEFRAMES (targeted, per the task spec, not a further sweep):
  GOLD, SILVER: 1d(="24h"), 1week
  BTC:          1d
  EURUSD:       4h, 1d

mature_range_min_candles: 20 for 4h/1d configs, 8 for 1week configs (task-specified,
documented parameter — see range_mean_reversion_maturity.py's module docstring).

RANDOM-ENTRY BASELINE: the eligible pool for v1.5.0's random baseline is the MATURE
range pool specifically (ADX < 25 for >= mature_range_min_candles consecutive closed
candles) — a strictly narrower pool than v1.0.0's own (ADX < 25 alone) — testing
whether band-extreme timing adds value within THIS narrower, more-mature pool. v1.0.0's
own baseline (range_random_baseline, reused unchanged) still uses its original,
unfiltered ADX<25 pool for its own comparison.

Fees: forex flat 0.05%/2bps; metals via scaled_fees_for_asset; crypto unscaled. No
max_holding_hours field on either version (matching v1.0.0's own no-time-cap design).

No synthetic/fabricated price data — a failed fetch is reported SKIPPED with reason.

Usage:
    python -m tools.range_mean_reversion_maturity_sweep
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
from nero_core.strategies.range_mean_reversion import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    add_indicators,
    evaluate_exit,
    run_backtest as v1_run_backtest,
    size_entry,
)
from nero_core.strategies.range_mean_reversion_maturity import (
    DEFAULT_MATURITY_PARAMETERS,
    RangeMaturityState,
    run_backtest as maturity_run_backtest,
)
from nero_core.strategies.timeframe_calibration import scaled_fees_for_asset
from tools.backtest_range_mean_reversion_sweep import calibrated_params_for as v1_calibrated_params_for
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

FOREX_FEE_BPS = 5.0
FOREX_SLIPPAGE_BPS = 2.0

# display -> (pipeline key / Twelve Data interval, mature_range_min_candles)
GOLD_SILVER_TIMEFRAMES = {"1d": ("24h", 20), "1week": ("1week", 8)}
BTC_TIMEFRAMES = {"1d": ("24h", 20)}
EURUSD_TIMEFRAMES = {"4h": ("4h", 20), "1d": ("1day", 20)}


def maturity_params_for(asset: str, mature_n: int) -> "RangeMaturityParameters":
    base = replace(DEFAULT_MATURITY_PARAMETERS, mature_range_min_candles=mature_n)
    if asset == "EURUSD":
        return replace(base, fee_bps=FOREX_FEE_BPS, slippage_bps=FOREX_SLIPPAGE_BPS)
    return scaled_fees_for_asset(base, asset)


def _mature_eligible_mask(evaluable: pd.DataFrame, params) -> pd.Series:
    """ADX < entry threshold AND the preceding streak (as tracked candle-by-candle,
    identical to run_backtest's own counter logic) already meets the maturity bar."""
    adx = evaluable["adx"]
    below = adx < params.adx_entry_threshold
    streak = 0
    matured = []
    for ok in below:
        matured.append(streak >= params.mature_range_min_candles)
        streak = streak + 1 if bool(ok) else 0
    return pd.Series(matured, index=evaluable.index) & below


def _simulate_random_entries_maturity(
    rows: list[pd.Series], eligible_flags: list[bool], params, entry_probability: float, rng: random.Random,
) -> list:
    """Bespoke copy of the RMR random simulator using RangeMaturityState (needs the
    extra consecutive_ranging_bars field v1.0.0's own MeanReversionState/
    RangeMeanReversionState lack) — same class of harness-interface mismatch this
    project has repeatedly solved with a small local copy rather than a shared-harness
    change."""
    state = RangeMaturityState(equity=params.initial_equity)
    trades = []
    for candle, ok in zip(rows, eligible_flags):
        reset_daily_guard_if_needed(state, candle["date"])
        exit_event = evaluate_exit(candle, state, params)
        if exit_event is not None:
            trades.append(exit_event)
        if state.open_trade is None and ok and rng.random() < entry_probability:
            direction = "LONG" if rng.random() < 0.5 else "SHORT"
            trade = size_entry(candle, state, params, direction)
            if trade is not None:
                state.open_trade = trade
        adx_value = candle.get("adx")
        if adx_value is not None and not pd.isna(adx_value) and float(adx_value) < params.adx_entry_threshold:
            state.consecutive_ranging_bars += 1
        else:
            state.consecutive_ranging_bars = 0
    return trades


def maturity_random_baseline(
    evaluable: pd.DataFrame, eligible_mask: pd.Series, params, real_expectancy_r: float, target_trade_count: int,
    n_runs: int = RANDOM_ENTRY_RUNS, seed: int = RANDOM_ENTRY_SEED,
) -> RandomBaselineResult | None:
    eligible_count = int(eligible_mask.sum())
    if eligible_count == 0 or target_trade_count <= 0:
        return None
    entry_probability = min(1.0, target_trade_count / eligible_count)
    rng = random.Random(seed)
    rows = [evaluable.iloc[i] for i in range(len(evaluable))]
    flags = [bool(v) for v in eligible_mask]
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        trades = _simulate_random_entries_maturity(rows, flags, params, entry_probability, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def _v1_half_stats(half_candles: pd.DataFrame, params) -> dict[str, object]:
    from tools.backtest_range_mean_reversion_sweep import _range_half_stats
    return _range_half_stats(half_candles, params)


def _maturity_half_stats(half_candles: pd.DataFrame, params) -> dict[str, object]:
    enriched = add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, _state = maturity_run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    eligible_mask = _mature_eligible_mask(evaluable, params)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = maturity_random_baseline(evaluable, eligible_mask, params, expectancy_r, len(trades))
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
        "mature_pool_size": int(eligible_mask.sum()),
    }


def _run_config(asset: str, display_tf: str, candles: pd.DataFrame, method: str, mature_n: int) -> dict[str, object]:
    start = time.monotonic()
    train, test = split_chronological(candles)

    v1_params = v1_calibrated_params_for(asset) if asset != "EURUSD" else replace(
        DEFAULT_PARAMETERS, fee_bps=FOREX_FEE_BPS, slippage_bps=FOREX_SLIPPAGE_BPS
    )
    maturity_params = maturity_params_for(asset, mature_n)

    v1_train = _v1_half_stats(train, v1_params)
    v1_test = _v1_half_stats(test, v1_params)
    maturity_train = _maturity_half_stats(train, maturity_params)
    maturity_test = _maturity_half_stats(test, maturity_params)

    elapsed = time.monotonic() - start
    print(f"{asset} / {display_tf} (N={mature_n}): done ({elapsed:.1f}s, {len(candles)} candles) — "
          f"v1.0.0 train N={v1_train['trades']} test N={v1_test['trades']} | "
          f"maturity train N={maturity_train['trades']} test N={maturity_test['trades']}")
    return {
        "asset": asset, "timeframe": display_tf, "mature_n": mature_n, "candle_count": len(candles),
        "v1_train": v1_train, "v1_test": v1_test, "v1_verdict": classify_verdict(v1_train, v1_test),
        "maturity_train": maturity_train, "maturity_test": maturity_test,
        "maturity_verdict": classify_verdict(maturity_train, maturity_test),
    }


def run_sweep() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    client = MarketDataClient()

    for asset, timeframes in (("GOLD", GOLD_SILVER_TIMEFRAMES), ("SILVER", GOLD_SILVER_TIMEFRAMES)):
        for display_tf, (pipeline_tf, mature_n) in timeframes.items():
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"{asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config(asset, display_tf, candles, method, mature_n))

    for display_tf, (pipeline_tf, mature_n) in BTC_TIMEFRAMES.items():
        try:
            candles, method = fetch_timeframe_candles(client, "BTC", pipeline_tf)
        except MarketDataUnavailableError as exc:
            print(f"BTC / {display_tf}: SKIPPED — {exc}")
            rows.append({"asset": "BTC", "timeframe": display_tf, "error": str(exc)})
            continue
        rows.append(_run_config("BTC", display_tf, candles, method, mature_n))

    for display_tf, (interval, mature_n) in EURUSD_TIMEFRAMES.items():
        try:
            result = fetch_forex_ohlcv("EUR/USD", interval)
        except ForexDataUnavailableError as exc:
            print(f"EURUSD / {display_tf}: SKIPPED — {exc}")
            rows.append({"asset": "EURUSD", "timeframe": display_tf, "error": str(exc)})
            continue
        rows.append(_run_config("EURUSD", display_tf, result.prices, result.source, mature_n))

    return rows


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    baseline = stats.get("baseline")
    edge = f", edge_over_random={baseline.edge_over_random:.3f}" if baseline is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{edge}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== RANGE_MATURITY (R2) vs fresh v1.0.0 baseline ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['asset']} / {r['timeframe']}: SKIPPED — {r['error']}")
            continue
        lines.append(f"{r['asset']} / {r['timeframe']} (mature_range_min_candles={r['mature_n']}, {r['candle_count']} candles):")
        lines.append(f"  v1.0.0 baseline:  {r['v1_verdict']} — TRAIN {_fmt_half(r['v1_train'])} | TEST {_fmt_half(r['v1_test'])}")
        lines.append(f"  v1.5.0 maturity:  {r['maturity_verdict']} — TRAIN {_fmt_half(r['maturity_train'])} | TEST {_fmt_half(r['maturity_test'])}")
        lines.append(f"    mature pool size: train={r['maturity_train']['mature_pool_size']} test={r['maturity_test']['mature_pool_size']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
