"""CLI: GOLD_SILVER_RATIO_MR (Three New Hypothesis Batch, Hypothesis 1) — 1day/1week
sweep with the batch's upgraded harness: chronological 70/30 split, bootstrap 95%
CI, and a random-entry baseline.

RANDOM-ENTRY BASELINE DESIGN: unlike a single-asset strategy, GOLD_SILVER_RATIO_MR's
entry DIRECTION is mechanically determined by which side of the band the ratio sits
on (no direction choice to randomize) — so the meaningful null hypothesis here is
"does entering at the FIRST candle an extreme is detected beat entering at a RANDOM
candle within the SAME eligible pool (ratio outside the band, either side)?" — the
same "is timing-within-the-regime adding value beyond the regime/eligibility filter
alone" question RANGE_MEAN_REVERSION's own random baseline asks, adapted here.
Direction at the randomly-chosen candle is still mechanically determined by which
band side that candle is on (never randomized) — only WHICH eligible candle gets
the entry is randomized.

Grid-shift: 1day capped at PROMISING-WATCHLIST (per this task's own rule); 1week per
the established metals settlement-gap convention (native, not resampled, for both
GOLD via Twelve Data and SILVER via yfinance futures — NOT_APPLICABLE regardless of
outcome, matching every prior metals precedent in this project).

No synthetic/fabricated price data — a failed fetch blocks the whole hypothesis.

Usage:
    python -m tools.gold_silver_ratio_sweep
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.gold_silver_ratio_mr import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    GoldSilverRatioState,
    add_indicators,
    align_gold_silver_candles,
    evaluate_exit,
    ratio_eligible_mask,
    run_backtest,
    size_entry,
)
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

TIMEFRAMES = {"1d": "24h", "1week": "1week"}


def _simulate_random_entries_ratio(
    rows: list[pd.Series], eligible_flags: list[bool], params, entry_probability: float, rng: random.Random,
) -> list:
    """Bespoke random-entry simulator (GoldSilverRatioState needs fields no shared
    harness state class has — same class of mismatch this project has repeatedly
    solved with a small local copy). Direction at a chosen candle is mechanically
    determined by which band side that candle sits on, never randomized."""
    state = GoldSilverRatioState(equity=params.initial_equity)
    trades = []
    for row, ok in zip(rows, eligible_flags):
        exit_event = evaluate_exit(row, state, params)
        if exit_event is not None:
            trades.append(exit_event)
        if state.open_trade is None and ok and rng.random() < entry_probability:
            direction = "LONG_SILVER_SHORT_GOLD" if float(row["ratio"]) > float(row["rolling_p90"]) else "LONG_GOLD_SHORT_SILVER"
            trade = size_entry(row, state, params, direction)
            if trade is not None:
                state.open_trade = trade
    return trades


def ratio_random_baseline(
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
        trades = _simulate_random_entries_ratio(rows, flags, params, entry_probability, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def _half_stats(half_aligned: pd.DataFrame, params) -> dict[str, object]:
    enriched = add_indicators(half_aligned, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, _state = run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    eligible_mask = ratio_eligible_mask(evaluable)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = ratio_random_baseline(evaluable, eligible_mask, params, expectancy_r, len(trades))

    exit_reason_counts: dict[str, int] = {}
    for t in trades:
        exit_reason_counts[t.exit_reason] = exit_reason_counts.get(t.exit_reason, 0) + 1

    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
        "exit_reason_counts": exit_reason_counts, "eligible_pool_size": int(eligible_mask.sum()),
    }


def run_timeframe(display_tf: str) -> dict[str, object]:
    client = MarketDataClient()
    try:
        gold, gold_method = fetch_timeframe_candles(client, "GOLD", TIMEFRAMES[display_tf])
        silver, silver_method = fetch_timeframe_candles(client, "SILVER", TIMEFRAMES[display_tf])
    except MarketDataUnavailableError as exc:
        return {"timeframe": display_tf, "error": str(exc)}

    aligned = align_gold_silver_candles(gold, silver)
    if aligned.empty:
        return {"timeframe": display_tf, "error": "no aligned GOLD/SILVER candles"}

    start = time.monotonic()
    train, test = split_chronological(aligned)
    train_stats = _half_stats(train, DEFAULT_PARAMETERS)
    test_stats = _half_stats(test, DEFAULT_PARAMETERS)
    elapsed = time.monotonic() - start
    print(f"{display_tf}: done ({elapsed:.1f}s, {len(aligned)} aligned candles) — "
          f"train N={train_stats['trades']} test N={test_stats['trades']}")

    return {
        "timeframe": display_tf, "candle_count": len(aligned), "gold_method": gold_method, "silver_method": silver_method,
        "train": train_stats, "test": test_stats, "verdict": classify_verdict(train_stats, test_stats),
    }


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
    ci = stats["ci"]
    ci_str = f", CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{ci_str}{edge}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== GOLD_SILVER_RATIO_MR sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['timeframe']}: SKIPPED — {r['error']}")
            continue
        lines.append(f"{r['timeframe']}: {r['verdict']} ({r['candle_count']} candles, {r['gold_method']} | {r['silver_method']})")
        lines.append(f"  TRAIN {_fmt_half(r['train'])}")
        lines.append(f"  TEST  {_fmt_half(r['test'])}")
        lines.append(f"  train exit reasons: {r['train']['exit_reason_counts']} | eligible pool: {r['train']['eligible_pool_size']}")
        lines.append(f"  test  exit reasons: {r['test']['exit_reason_counts']} | eligible pool: {r['test']['eligible_pool_size']}")
    qualifying = find_qualifying(rows)
    lines.append("")
    lines.append(f"=== {len(qualifying)} configs qualify for grid-shift verification ===")
    for r in qualifying:
        lines.append(f"  {r['timeframe']}")
    return "\n".join(lines)


def main() -> None:
    rows = [run_timeframe(tf) for tf in TIMEFRAMES]
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
