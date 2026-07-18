"""Statistical rigor add-ons for the backtest verification harness.

Two tools, both deterministic (fixed seeds — re-running produces byte-identical
numbers, since this is a verification harness, not a live simulation):

1. `bootstrap_mean_r_ci` — a percentile bootstrap 95% CI on the mean per-trade R
   multiple. Answers "how much would this expectancy estimate wobble under resampling
   noise alone?" A CI that crosses zero means the edge is not statistically
   distinguishable from zero at this sample size, regardless of how positive the point
   estimate looks.
2. `random_entry_baseline_single_asset` / `random_entry_baseline_pairs` — "would ANY
   entry timing within the same regime have done about as well?" Answers a different
   question than the bootstrap: not "is this number noisy," but "is the specific entry
   TRIGGER (breakout, pullback, z-score cross) actually doing anything beyond what the
   regime filter and exit/sizing rules alone already capture?"

Both intentionally reuse the exact same `evaluate_exit` / `size_entry_fn` / sizing
mechanics the real strategies use — only the ENTRY TIMING is randomized. Nothing about
exits, stops, fees, or position sizing changes between the real and random-entry runs,
so any expectancy gap is attributable to entry timing alone, not incidental mechanics
differences.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Sequence

import pandas as pd

from nero_core.strategies.cointegration_pairs import (
    CointegrationPairsParameters,
    OpenTrade as PairsOpenTrade,
    PairsState,
    determine_exit_reason,
)
from nero_core.strategies.mean_reversion import MeanReversionState, apply_slippage, evaluate_exit, reset_daily_guard_if_needed

BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 20260718
RANDOM_ENTRY_RUNS = 200
RANDOM_ENTRY_SEED = 20260718

PAIRS_REGIME_CAVEAT = (
    "COINTEGRATION_PAIRS has no separate regime/trend precondition distinct from its "
    "own z-score trigger, so the eligible pool here is every warmup-valid candle "
    "(zscore not NaN) rather than a regime-filtered subset, and entry side (long the x "
    "leg vs the y leg) is chosen 50/50 at random rather than following the real "
    "z-score's sign. This is a weaker null hypothesis than the single-asset baselines "
    "below, which do isolate a genuine regime filter from the entry trigger."
)


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (the standard "type 7" definition pandas/numpy
    also default to) over an already-sorted sequence."""
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    return float(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


@dataclass(frozen=True)
class BootstrapCI:
    sample_size: int
    mean_r: float
    lower_2_5: float
    upper_97_5: float
    crosses_zero: bool  # True -> "edge not statistically proven" at this sample size


def bootstrap_mean_r_ci(
    r_values: Sequence[float], iterations: int = BOOTSTRAP_ITERATIONS, seed: int = BOOTSTRAP_SEED
) -> BootstrapCI | None:
    """Percentile bootstrap (resample r_values with replacement, `iterations` times,
    take the [2.5th, 97.5th] percentile of the resampled means) 95% CI on the mean
    per-trade R multiple. Deterministic for a given (r_values, seed). None if there are
    zero trades — there is nothing to resample."""
    n = len(r_values)
    if n == 0:
        return None
    values = list(r_values)
    rng = random.Random(seed)
    means = [sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations)]
    means.sort()
    lower = _percentile(means, 2.5)
    upper = _percentile(means, 97.5)
    mean_r = sum(values) / n
    return BootstrapCI(sample_size=n, mean_r=mean_r, lower_2_5=lower, upper_97_5=upper, crosses_zero=(lower <= 0.0 <= upper))


@dataclass(frozen=True)
class RandomBaselineResult:
    real_expectancy_r: float
    mean_random_expectancy_r: float
    p95_random_expectancy_r: float
    edge_over_random: float
    target_trade_count: int
    realized_mean_trade_count: float
    n_runs: int
    caveat: str | None = None


def breakout_momentum_regime_mask(evaluable: pd.DataFrame) -> pd.Series:
    """BREAKOUT_MOMENTUM's trend PRECONDITION only (close > MA200) — deliberately
    excludes the specific breakout-high/RSI TRIGGER, which is exactly what "random
    entry timing within the same regime" needs to isolate."""
    return evaluable["close"] > evaluable["ma200"]


def trend_pullback_regime_mask(evaluable: pd.DataFrame) -> pd.Series:
    """TREND_PULLBACK's established-uptrend PRECONDITION only (close > MA200 AND MA50 >
    MA200) — excludes the specific pullback-to-MA50/RSI-band TRIGGER."""
    return (evaluable["close"] > evaluable["ma200"]) & (evaluable["ma50"] > evaluable["ma200"])


def _simulate_random_entries_single_asset(
    rows: list[pd.Series],
    eligible_flags: list[bool],
    params,
    size_entry_fn: Callable,
    entry_probability: float,
    rng: random.Random,
    evaluate_exit_fn: Callable = evaluate_exit,
) -> list:
    """One random-entry pass: identical to a real backtest loop (same evaluate_exit_fn,
    same size_entry_fn, same params) except the entry TRIGGER is replaced by "eligible
    (regime holds) AND a Bernoulli(entry_probability) draw," so it never opens a second
    position while one is already open, exactly like the real strategy.

    `evaluate_exit_fn` defaults to the shared mean_reversion.evaluate_exit (what every
    ATR-stop-and-target strategy in this codebase uses) but accepts any function with
    the same (candle, state, params) -> ExitEvent | None contract — e.g. a strategy
    with a genuinely different exit shape (no target, no max-holding cap) that defines
    its own, like FUNDING_EXTREME.

    Takes pre-extracted `rows`/`eligible_flags` (built once by the caller, outside the
    n_runs loop) rather than a DataFrame + `.iloc[i]` per access — repeating `.iloc`
    hundreds of times per row across hundreds of runs is the dominant cost of this
    simulation; materializing each row's Series exactly once and reusing it across
    every run is a pure performance optimization with no effect on the result."""
    state = MeanReversionState(equity=params.initial_equity)
    trades = []
    for candle, eligible in zip(rows, eligible_flags):
        reset_daily_guard_if_needed(state, candle["date"])
        exit_event = evaluate_exit_fn(candle, state, params)
        if exit_event is not None:
            trades.append(exit_event)
        if state.open_trade is None and eligible and rng.random() < entry_probability:
            trade = size_entry_fn(candle, state, params)
            if trade is not None:
                state.open_trade = trade
    return trades


def random_entry_baseline_single_asset(
    evaluable: pd.DataFrame,
    eligible_mask: pd.Series,
    params,
    size_entry_fn: Callable,
    real_expectancy_r: float,
    target_trade_count: int,
    n_runs: int = RANDOM_ENTRY_RUNS,
    seed: int = RANDOM_ENTRY_SEED,
    evaluate_exit_fn: Callable = evaluate_exit,
) -> RandomBaselineResult | None:
    """`entry_probability` is calibrated so E[trades per run] == target_trade_count (the
    real strategy's trade count in this half) — individual runs' realized counts vary
    around that target by chance, matching how permutation-style random baselines are
    conventionally built; `realized_mean_trade_count` reports the achieved average as a
    sanity check. None if the eligible pool or target count is empty."""
    eligible_count = int(eligible_mask.sum())
    if eligible_count == 0 or target_trade_count <= 0:
        return None
    entry_probability = min(1.0, target_trade_count / eligible_count)
    rng = random.Random(seed)
    rows = [evaluable.iloc[i] for i in range(len(evaluable))]
    eligible_flags = [bool(v) for v in eligible_mask]
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        trades = _simulate_random_entries_single_asset(
            rows, eligible_flags, params, size_entry_fn, entry_probability, rng, evaluate_exit_fn
        )
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r,
        mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95),
        edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count,
        realized_mean_trade_count=sum(trade_counts) / n_runs,
        n_runs=n_runs,
    )


@dataclass(frozen=True)
class _RandomPairsTrade:
    r_multiple: float


def _simulate_random_entries_pairs(
    rows: list[pd.Series],
    params: CointegrationPairsParameters,
    x_name: str,
    y_name: str,
    entry_probability: float,
    rng: random.Random,
) -> list[_RandomPairsTrade]:
    """Same idea as `_simulate_random_entries_single_asset` but for the pairs state
    machine: same exit rule (determine_exit_reason), same sizing (notional_fraction),
    same fee/slippage mechanics — only entry timing AND entry side (which leg is long)
    are randomized, since there's no regime-independent "direction" concept here (see
    PAIRS_REGIME_CAVEAT). Takes a pre-extracted `rows` list for the same performance
    reason `_simulate_random_entries_single_asset` does."""
    state = PairsState(equity=params.initial_equity)
    trades: list[_RandomPairsTrade] = []
    for row in rows:
        z = float(row["zscore"])
        if state.open_trade is not None:
            trade = state.open_trade
            exit_reason = determine_exit_reason(trade.entry_side, z, params.exit_z, params.stop_z)
            if exit_reason is not None:
                price_now = float(row[f"{trade.asset}_close"])
                exit_price = apply_slippage(price_now, params.slippage_bps, "sell")
                gross_pnl = (exit_price - trade.entry_price) * trade.quantity
                exit_fee = exit_price * trade.quantity * params.fee_bps / 10000.0
                net_pnl = gross_pnl - trade.entry_fee - exit_fee
                state.equity += net_pnl
                trades.append(_RandomPairsTrade(r_multiple=net_pnl / max(trade.notional, 1e-9)))
                state.open_trade = None
        if state.open_trade is None and rng.random() < entry_probability:
            side = 1 if rng.random() < 0.5 else -1
            asset = x_name if side == 1 else y_name
            raw_entry = float(row[f"{asset}_close"])
            entry_price = apply_slippage(raw_entry, params.slippage_bps, "buy")
            notional = min(state.equity * params.notional_fraction, state.equity * params.max_notional_pct)
            quantity = notional / entry_price
            entry_fee = notional * params.fee_bps / 10000.0
            state.open_trade = PairsOpenTrade(
                asset=asset, entry_side=side, entry_price=entry_price, quantity=quantity,
                notional=notional, entry_fee=entry_fee, open_close_time=int(row["close_time"]), entry_zscore=z,
            )
    return trades


def random_entry_baseline_pairs(
    evaluable: pd.DataFrame,
    params: CointegrationPairsParameters,
    x_name: str,
    y_name: str,
    real_expectancy_r: float,
    target_trade_count: int,
    n_runs: int = RANDOM_ENTRY_RUNS,
    seed: int = RANDOM_ENTRY_SEED,
) -> RandomBaselineResult | None:
    eligible_count = len(evaluable)
    if eligible_count == 0 or target_trade_count <= 0:
        return None
    entry_probability = min(1.0, target_trade_count / eligible_count)
    rng = random.Random(seed)
    rows = [evaluable.iloc[i] for i in range(len(evaluable))]
    exp_rs: list[float] = []
    trade_counts: list[int] = []
    for _ in range(n_runs):
        trades = _simulate_random_entries_pairs(rows, params, x_name, y_name, entry_probability, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r,
        mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95),
        edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count,
        realized_mean_trade_count=sum(trade_counts) / n_runs,
        n_runs=n_runs,
        caveat=PAIRS_REGIME_CAVEAT,
    )
