"""CLI: CARRY_MOMENTUM (Three New Hypothesis Batch, Hypothesis 2) — 1day/1week
sweep with the batch's upgraded harness: chronological 70/30 split, bootstrap 95%
CI, and a random-entry baseline.

RANDOM-ENTRY BASELINE DESIGN: CARRY_MOMENTUM's entry direction is mechanically
determined (no direction to randomize) and its distinctive mechanism is the
RANKING step — among all momentum-passing candidates on a given day, only the
top `max_concurrent_positions` by |rate differential| are actually taken. The
random baseline mirrors run_backtest's exact loop but replaces the ranking step
with a random shuffle of the SAME momentum-passing candidate pool, keeping every
other mechanic (sizing, stop, target, holding cap, concurrent-position limit)
identical — isolating whether picking the LARGEST differential adds value beyond
simply trading trending forex when a carry candidate exists at all.

Grid-shift: 1day capped at watch-list (per this task's own rule); 1week per the
established forex Friday-close-gap convention (native Twelve Data 1week, not
resampled from finer data in this sweep — NOT_APPLICABLE regardless of outcome).

No synthetic/fabricated price or rate data — a failed fetch blocks the hypothesis.

Usage:
    python -m tools.carry_momentum_sweep
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.fred_rates import fetch_policy_rate
from nero_core.data_sources.forex_data import fetch_forex_ohlcv
from nero_core.strategies.carry_momentum import (
    CURRENCIES,
    DEFAULT_PARAMETERS,
    PAIR_BASE_QUOTE,
    PAIRS,
    CarryMomentumState,
    add_indicators,
    build_master_calendar,
    evaluate_carry_signal,
    evaluate_exit,
    size_entry,
)
from nero_core.strategies.carry_momentum import _check_time_exit  # reused for the random-baseline loop too
from nero_core.strategies.mean_reversion import reset_daily_guard_if_needed
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

INDICATOR_COLUMNS_NEEDED = [c for pair in PAIRS for c in (f"{pair}_sma50", f"{pair}_atr")] + [f"rate_{c}" for c in CURRENCIES]


def _simulate_random_carry_selection(rows: list[pd.Series], params, rng: random.Random) -> list:
    """Exact copy of carry_momentum.run_backtest's own loop, except the ranking
    step (sort by |differential| descending) is replaced by a random shuffle of
    the SAME momentum-passing candidate pool -- every other mechanic (sizing,
    stop, target, holding cap, concurrent-position limit) is identical. `rows` is
    pre-extracted ONCE by the caller (the established `rows = [evaluable.iloc[i]
    for i in range(len(evaluable))]` pattern already used by every other random-
    baseline tool in this project) so this -- called n_runs times -- never
    re-pays pandas' per-row .iloc construction cost on every run."""
    state = CarryMomentumState(equity=params.initial_equity)
    closed_trades: list = []
    open_index: dict[str, int] = {}
    pending_entries: dict[str, str] = {}

    for i, row in enumerate(rows):
        reset_daily_guard_if_needed(state, row["date"])

        for pair, direction in list(pending_entries.items()):
            if pair not in state.open_positions and len(state.open_positions) < params.max_concurrent_positions:
                trade = size_entry(row, pair, direction, state, params)
                if trade is not None:
                    state.open_positions[pair] = trade
                    open_index[pair] = i
        pending_entries.clear()

        for pair in list(state.open_positions.keys()):
            sessions_held = i - open_index.get(pair, i)
            exit_event = evaluate_exit(row, pair, state, params)
            if exit_event is None:
                exit_event = _check_time_exit(row, pair, state, params, sessions_held)
            if exit_event is not None:
                from dataclasses import replace as _replace
                exit_event = _replace(exit_event, holding_sessions=sessions_held)
                closed_trades.append(exit_event)
                open_index.pop(pair, None)

        if len(state.open_positions) < params.max_concurrent_positions and state.daily_r > params.daily_loss_guard_r:
            candidates: list[tuple[str, str]] = []
            for pair in PAIRS:
                if pair in state.open_positions:
                    continue
                evaluation = evaluate_carry_signal(row, pair, params)
                if evaluation.passed:
                    candidates.append((pair, evaluation.direction))
            rng.shuffle(candidates)  # the ONLY difference from run_backtest: random order, not ranked by |differential|
            slots_available = params.max_concurrent_positions - len(state.open_positions)
            for pair, direction in candidates[:slots_available]:
                pending_entries[pair] = direction

    return closed_trades


def carry_random_baseline(
    evaluable: pd.DataFrame, params, real_expectancy_r: float, n_runs: int = RANDOM_ENTRY_RUNS, seed: int = RANDOM_ENTRY_SEED,
) -> RandomBaselineResult | None:
    rng = random.Random(seed)
    rows = [evaluable.iloc[i] for i in range(len(evaluable))]  # pre-extracted ONCE, reused across all n_runs
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        trades = _simulate_random_carry_selection(rows, params, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    if not any(trade_counts):
        return None
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=0, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def fetch_all_data(timeframe: str) -> tuple[dict[str, pd.DataFrame], dict[str, tuple[pd.Series, str]]]:
    pair_candles = {pair: fetch_forex_ohlcv(pair, timeframe).prices for pair in PAIRS}
    rate_series = {ccy: (lambda r: (r[0], r[2]))(fetch_policy_rate(ccy)) for ccy in CURRENCIES}
    return pair_candles, rate_series


def _half_stats(half_master_enriched: pd.DataFrame, params) -> dict[str, object]:
    from nero_core.strategies.carry_momentum import run_backtest
    evaluable = half_master_enriched.dropna(subset=INDICATOR_COLUMNS_NEEDED).reset_index(drop=True)
    trades, _state = run_backtest(evaluable, None, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    ci = bootstrap_mean_r_ci(r_values)
    baseline = carry_random_baseline(evaluable, params, expectancy_r)

    exit_reason_counts: dict[str, int] = {}
    pair_counts: dict[str, int] = {}
    for t in trades:
        exit_reason_counts[t.exit_reason] = exit_reason_counts.get(t.exit_reason, 0) + 1
        pair_counts[t.pair] = pair_counts.get(t.pair, 0) + 1

    return {
        "trades": len(trades), "expectancy_r": expectancy_r, "below_min_sample": len(trades) < MIN_SAMPLE_SIZE,
        "ci": ci, "baseline": baseline, "exit_reason_counts": exit_reason_counts, "pair_counts": pair_counts,
    }


def run_timeframe(display_tf: str, twelve_data_timeframe: str) -> dict[str, object]:
    pair_candles, rate_series = fetch_all_data(twelve_data_timeframe)
    master = build_master_calendar(pair_candles)
    enriched = add_indicators(master, rate_series, DEFAULT_PARAMETERS)

    start = time.monotonic()
    train, test = split_chronological(enriched)
    train_stats = _half_stats(train, DEFAULT_PARAMETERS)
    test_stats = _half_stats(test, DEFAULT_PARAMETERS)
    elapsed = time.monotonic() - start
    print(f"{display_tf}: done ({elapsed:.1f}s, {len(enriched)} master-calendar candles) — "
          f"train N={train_stats['trades']} test N={test_stats['trades']}")

    return {
        "timeframe": display_tf, "candle_count": len(enriched),
        "train": train_stats, "test": test_stats, "verdict": classify_verdict(train_stats, test_stats),
    }


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    baseline = stats["baseline"]
    edge = f", edge_over_random={baseline.edge_over_random:.3f}" if baseline is not None else ""
    ci = stats["ci"]
    ci_str = f", CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{ci_str}{edge}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== CARRY_MOMENTUM sweep ===", ""]
    for r in rows:
        lines.append(f"{r['timeframe']}: {r['verdict']} ({r['candle_count']} candles)")
        lines.append(f"  TRAIN {_fmt_half(r['train'])} | pairs: {r['train']['pair_counts']} | exits: {r['train']['exit_reason_counts']}")
        lines.append(f"  TEST  {_fmt_half(r['test'])} | pairs: {r['test']['pair_counts']} | exits: {r['test']['exit_reason_counts']}")
    return "\n".join(lines)


def main() -> None:
    rows = [
        run_timeframe("1d", "1day"),
        run_timeframe("1week", "1week"),
    ]
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
