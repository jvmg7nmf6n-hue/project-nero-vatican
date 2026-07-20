"""CLI: PEAD (Three New Hypothesis Batch, Hypothesis 3) — 6 configs (3 surprise
thresholds x 2 holding windows), pooled across all 7 tickers, with the batch's
upgraded harness: 70/30 split BY CALENDAR TIME (not by event count -- each
ticker's own candle history is split chronologically, then events are assigned
to whichever half their announcement falls in), bootstrap 95% CI, and a
random-entry baseline.

RANDOM-ENTRY BASELINE DESIGN: uses `direction_override` to keep the EXACT SAME
eligible event pool (|surprise| >= threshold) but assign a random 50/50 LONG/
SHORT direction instead of the surprise-implied one — isolating whether the
surprise DIRECTION itself carries the edge, vs just elevated event-day
volatility (either direction would do equally well on these days).

PERFORMANCE: each ticker's own daily candle history (up to ~11,500 rows for
AAPL) is pandas-row-extracted ONCE per half, up front — reused across all 6
configs' real backtests AND all of their 200-run random baselines (1200+ reruns
per ticker/half). Re-extracting rows on every one of those reruns (the naive
approach) turned earlier sweeps in this project into multi-minute-per-config
slogs; this sweep never repeats that mistake.

Grid-shift: 1day capped at watch-list per this task's own rule (the only
timeframe tested here — the task specifies 1day only for PEAD).

Earnings are quarterly -> every config WILL be LOW SAMPLE. Per the task's own
explicit instruction, thin-but-positive is NOT auto-failed here — it is exactly
what routes to PROMISING-WATCHLIST, since quarterly data can only accumulate live.

No synthetic/fabricated data — a ticker that fails the data audit is excluded,
never silently substituted.

Usage:
    python -m tools.pead_sweep
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.earnings_data import EarningsDataUnavailableError, fetch_earnings_surprises
from nero_core.data_sources.stock_data import StockDataUnavailableError, fetch_stock_ohlcv
from nero_core.strategies.pead import (
    HOLDING_WINDOWS_SESSIONS,
    SURPRISE_THRESHOLDS_PCT,
    TICKERS,
    PeadParameters,
    add_atr,
    build_entry_plan,
    run_pead_backtest_rows,
    strategy_version_for,
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
from tools.backtest_train_test_split import TRAIN_FRACTION


def fetch_ticker_data(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    try:
        events = fetch_earnings_surprises(ticker, limit=100)
        candles = fetch_stock_ohlcv(ticker, "1day").prices
    except (EarningsDataUnavailableError, StockDataUnavailableError):
        return None
    return add_atr(candles), events


def split_ticker_by_calendar_time(candles: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """70/30 split BY CALENDAR TIME: the candle frame is split chronologically
    at the TRAIN_FRACTION mark, and events are assigned to whichever half their
    OWN announcement date falls in -- never split by event count."""
    frame = candles.sort_values("close_time").reset_index(drop=True)
    split_index = int(len(frame) * TRAIN_FRACTION)
    train_candles = frame.iloc[:split_index].reset_index(drop=True)
    test_candles = frame.iloc[split_index:].reset_index(drop=True)
    boundary_date = train_candles["date"].iloc[-1] if not train_candles.empty else frame["date"].iloc[0]

    train_events = events[events.index <= boundary_date]
    test_events = events[events.index > boundary_date]
    return train_candles, test_candles, train_events, test_events


class TickerHalf:
    """Pre-extracted, reusable state for one (ticker, half): the row list is
    built ONCE and shared across every config's real backtest and every one of
    its random-baseline reruns."""

    def __init__(self, ticker: str, frame: pd.DataFrame, events: pd.DataFrame) -> None:
        self.ticker = ticker
        self.frame = frame.sort_values("close_time").reset_index(drop=True)
        self.events = events
        # Plain dicts, not pandas Series -- several times faster for the
        # dict-style [] / .get() access run_pead_backtest_rows does, and built in
        # one vectorized pass instead of N individual .iloc constructions.
        self.rows = self.frame.to_dict("records")


def _simulate_random_pead_direction(half: TickerHalf, params: PeadParameters, rng: random.Random) -> list:
    override: dict[pd.Timestamp, str] = {}
    for event_time, row in half.events.iterrows():
        surprise_fraction = float(row["surprise_pct"]) / 100.0
        if abs(surprise_fraction) < params.surprise_threshold_pct:
            continue
        override[event_time] = "LONG" if rng.random() < 0.5 else "SHORT"
    entry_plan = build_entry_plan(half.frame, half.events, params, direction_override=override)
    trades, _state = run_pead_backtest_rows(half.rows, entry_plan, half.ticker, params)
    return trades


def pead_random_baseline(
    halves: list[TickerHalf], params: PeadParameters, real_expectancy_r: float,
    n_runs: int = RANDOM_ENTRY_RUNS, seed: int = RANDOM_ENTRY_SEED,
) -> RandomBaselineResult | None:
    rng = random.Random(seed)
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        all_trades = []
        for half in halves:
            all_trades.extend(_simulate_random_pead_direction(half, params, rng))
        trade_counts.append(len(all_trades))
        exp_rs.append(sum(t.r_multiple for t in all_trades) / len(all_trades) if all_trades else 0.0)
    if not any(trade_counts):
        return None
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=0, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def _pooled_half_stats(halves: list[TickerHalf], params: PeadParameters) -> dict[str, object]:
    all_trades = []
    for half in halves:
        entry_plan = build_entry_plan(half.frame, half.events, params)
        trades, _state = run_pead_backtest_rows(half.rows, entry_plan, half.ticker, params)
        all_trades.extend(trades)
    r_values = [t.r_multiple for t in all_trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    ci = bootstrap_mean_r_ci(r_values)
    baseline = pead_random_baseline(halves, params, expectancy_r)

    exit_reason_counts: dict[str, int] = {}
    ticker_counts: dict[str, int] = {}
    for t in all_trades:
        exit_reason_counts[t.exit_reason] = exit_reason_counts.get(t.exit_reason, 0) + 1
        ticker_counts[t.ticker] = ticker_counts.get(t.ticker, 0) + 1

    return {
        "trades": len(all_trades), "expectancy_r": expectancy_r, "below_min_sample": len(all_trades) < MIN_SAMPLE_SIZE,
        "ci": ci, "baseline": baseline, "exit_reason_counts": exit_reason_counts, "ticker_counts": ticker_counts,
    }


def run_config(threshold_pct: float, holding_window: int, train_halves: list[TickerHalf], test_halves: list[TickerHalf]) -> dict[str, object]:
    params = PeadParameters(surprise_threshold_pct=threshold_pct, holding_window_sessions=holding_window)
    version = strategy_version_for(threshold_pct, holding_window)

    start = time.monotonic()
    train_stats = _pooled_half_stats(train_halves, params)
    test_stats = _pooled_half_stats(test_halves, params)
    elapsed = time.monotonic() - start
    print(f"{version}: done ({elapsed:.1f}s) — train N={train_stats['trades']} test N={test_stats['trades']}")

    return {
        "version": version, "threshold_pct": threshold_pct, "holding_window": holding_window,
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
    lines = ["=== PEAD sweep: 6 configs ===", ""]
    for r in rows:
        lines.append(f"{r['version']}: {r['verdict']}")
        lines.append(f"  TRAIN {_fmt_half(r['train'])} | tickers: {r['train']['ticker_counts']} | exits: {r['train']['exit_reason_counts']}")
        lines.append(f"  TEST  {_fmt_half(r['test'])} | tickers: {r['test']['ticker_counts']} | exits: {r['test']['exit_reason_counts']}")
    return "\n".join(lines)


def main() -> None:
    train_halves: list[TickerHalf] = []
    test_halves: list[TickerHalf] = []
    for ticker in TICKERS:
        result = fetch_ticker_data(ticker)
        if result is None:
            print(f"{ticker}: SKIPPED — data fetch failed")
            continue
        candles, events = result
        train_c, test_c, train_e, test_e = split_ticker_by_calendar_time(candles, events)
        train_halves.append(TickerHalf(ticker, train_c, train_e))
        test_halves.append(TickerHalf(ticker, test_c, test_e))
        print(f"{ticker}: fetched ({len(events)} resolved earnings events, {len(candles)} candles)")

    rows = []
    for threshold in SURPRISE_THRESHOLDS_PCT:
        for window in HOLDING_WINDOWS_SESSIONS:
            rows.append(run_config(threshold, window, train_halves, test_halves))

    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
