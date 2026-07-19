"""CLI: RANGE_MEAN_REVERSION — Task 2 three-tier asset test (regime-matched).

TIER 1 (range-prone): Forex EUR/USD, USD/JPY, GBP/USD, USD/CHF @ 1h/4h/1day;
                       Metals GOLD, SILVER @ 4h/1day(="24h")/1week
TIER 2 (conditional):  BTC, ETH @ 4h/12h/1day(="24h")
TIER 3 (stress-test, expected to fail — confirms the regime filter does real work):
                       SOL, NEAR @ 4h/12h

Per docs/range_mean_reversion_data_audit.md, all 28 configs cleared the adequacy bar
(no SKIPPED). Fees: forex flat 0.05%/side (matching Task B2's own convention), metals
use their own derived scale factor (scaled_fees_for_asset — GOLD/SILVER, from Asset
Expansion Phase A), crypto uses the unscaled crypto-baseline default (scaled_fees_
for_asset is a no-op for assets outside FEE_SCALE_FACTOR_BY_ASSET). No
max_holding_hours field exists on this strategy at all, so there's nothing to
re-derive per timeframe the way GOLD's 1week bug needed fixing for other strategies.

RANDOM-ENTRY BASELINE — the critical comparison this task asks for: does entering at
band-extremes beat RANDOM entry within the SAME ranging (ADX < 25) regime pool, or is
the regime filter alone doing the work? A bespoke bidirectional random-entry simulator
is used here (tools.backtest_statistics._simulate_random_entries_bidirectional is NOT
reused as-is because it hardcodes nero_core.strategies.mean_reversion.MeanReversionState,
which has no consecutive_high_adx_bars field this strategy's own evaluate_exit needs —
same class of harness-interface mismatch BOS_CONTINUATION's vol-clustering multiplier
hit earlier this project, solved the same way: a small bespoke copy using this
strategy's own state class, not a modification to the shared, widely-depended-on
harness).

Every config: chronological 70/30 split, bootstrap 95% CI + this bespoke random-entry
baseline, classify_verdict (SURVIVED / PROMISING-WATCHLIST / DIED). Grid-shift
verification (Task 3) is a separate follow-up tool.

No synthetic/fabricated price data is ever used — if a fetch fails, that combination
is reported as SKIPPED with the reason, never a substituted result.

Usage:
    python -m tools.backtest_range_mean_reversion_sweep
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
    RangeMeanReversionParameters,
    RangeMeanReversionState,
    add_indicators,
    evaluate_exit,
    range_eligible_mask,
    run_backtest,
    size_entry,
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

FOREX_PAIRS = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF"]
FOREX_TIMEFRAMES = ["1h", "4h", "1day"]
FOREX_FEE_BPS = 5.0  # 0.05% per side, matching Task B2's own convention
FOREX_SLIPPAGE_BPS = 2.0

METALS = ["GOLD", "SILVER"]
METALS_TIMEFRAMES = {"4h": "4h", "1day": "24h", "1week": "1week"}  # display -> pipeline key

TIER2_CRYPTO = ["BTC", "ETH"]
TIER2_TIMEFRAMES = {"4h": "4h", "12h": "12h", "1day": "24h"}

TIER3_CRYPTO = ["SOL", "NEAR"]
TIER3_TIMEFRAMES = {"4h": "4h", "12h": "12h"}


def calibrated_params_for(asset: str) -> RangeMeanReversionParameters:
    if asset in FOREX_PAIRS:
        return replace(DEFAULT_PARAMETERS, fee_bps=FOREX_FEE_BPS, slippage_bps=FOREX_SLIPPAGE_BPS)
    return scaled_fees_for_asset(DEFAULT_PARAMETERS, asset)  # GOLD/SILVER scaled; crypto unchanged


def _simulate_random_entries_range(
    rows: list[pd.Series], eligible_flags: list[bool], params: RangeMeanReversionParameters,
    entry_probability: float, rng: random.Random,
) -> list:
    """Bespoke copy of tools.backtest_statistics._simulate_random_entries_bidirectional
    using RangeMeanReversionState (not MeanReversionState) — see module docstring for
    why. The regime gate (ADX < entry threshold) is symmetric for both directions, so
    a single eligible_flags list drives a 50/50 random LONG/SHORT pick, matching the
    shared bidirectional simulator's own convention when its long/short masks are
    identical."""
    state = RangeMeanReversionState(equity=params.initial_equity)
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
    return trades


def range_random_baseline(
    evaluable: pd.DataFrame, eligible_mask: pd.Series, params: RangeMeanReversionParameters,
    real_expectancy_r: float, target_trade_count: int,
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
        trades = _simulate_random_entries_range(rows, flags, params, entry_probability, rng)
        trade_counts.append(len(trades))
        exp_rs.append(sum(t.r_multiple for t in trades) / len(trades) if trades else 0.0)
    exp_rs_sorted = sorted(exp_rs)
    mean_random = sum(exp_rs) / n_runs
    return RandomBaselineResult(
        real_expectancy_r=real_expectancy_r, mean_random_expectancy_r=mean_random,
        p95_random_expectancy_r=_percentile(exp_rs_sorted, 95), edge_over_random=real_expectancy_r - mean_random,
        target_trade_count=target_trade_count, realized_mean_trade_count=sum(trade_counts) / n_runs, n_runs=n_runs,
    )


def _range_half_stats(half_candles: pd.DataFrame, params: RangeMeanReversionParameters) -> dict[str, object]:
    enriched = add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, _state = run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    eligible_mask = range_eligible_mask(evaluable, params)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = range_random_baseline(evaluable, eligible_mask, params, expectancy_r, len(trades))
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _run_config(tier: str, asset: str, display_tf: str, candles: pd.DataFrame, method: str, params: RangeMeanReversionParameters) -> dict[str, object]:
    start = time.monotonic()
    train, test = split_chronological(candles)
    train_stats = _range_half_stats(train, params)
    test_stats = _range_half_stats(test, params)
    elapsed = time.monotonic() - start
    print(f"[{tier}] {asset} / {display_tf}: done ({elapsed:.1f}s, {len(candles)} candles)")
    return {
        "tier": tier, "asset": asset, "timeframe": display_tf, "method": method,
        "candle_count": len(candles), "train": train_stats, "test": test_stats,
        "verdict": classify_verdict(train_stats, test_stats),
    }


def run_sweep() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    client = MarketDataClient()

    for pair in FOREX_PAIRS:
        params = calibrated_params_for(pair)
        for timeframe in FOREX_TIMEFRAMES:
            try:
                result = fetch_forex_ohlcv(pair, timeframe)
            except ForexDataUnavailableError as exc:
                print(f"[TIER 1 (forex)] {pair} / {timeframe}: SKIPPED — {exc}")
                rows.append({"tier": "TIER 1 (forex)", "asset": pair, "timeframe": timeframe, "error": str(exc)})
                continue
            rows.append(_run_config("TIER 1 (forex)", pair, timeframe, result.prices, result.source, params))

    for asset in METALS:
        params = calibrated_params_for(asset)
        for display_tf, pipeline_tf in METALS_TIMEFRAMES.items():
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"[TIER 1 (metals)] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"tier": "TIER 1 (metals)", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("TIER 1 (metals)", asset, display_tf, candles, method, params))

    for asset in TIER2_CRYPTO:
        params = calibrated_params_for(asset)
        for display_tf, pipeline_tf in TIER2_TIMEFRAMES.items():
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"[TIER 2 (crypto)] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"tier": "TIER 2 (crypto)", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("TIER 2 (crypto)", asset, display_tf, candles, method, params))

    for asset in TIER3_CRYPTO:
        params = calibrated_params_for(asset)
        for display_tf, pipeline_tf in TIER3_TIMEFRAMES.items():
            try:
                candles, method = fetch_timeframe_candles(client, asset, pipeline_tf)
            except MarketDataUnavailableError as exc:
                print(f"[TIER 3 (stress-test)] {asset} / {display_tf}: SKIPPED — {exc}")
                rows.append({"tier": "TIER 3 (stress-test)", "asset": asset, "timeframe": display_tf, "error": str(exc)})
                continue
            rows.append(_run_config("TIER 3 (stress-test)", asset, display_tf, candles, method, params))

    return rows


def find_qualifying(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        r for r in rows
        if "verdict" in r and r["train"]["trades"] >= 20 and r["test"]["trades"] >= 20
        and r["train"]["expectancy_r"] > 0 and r["test"]["expectancy_r"] > 0
    ]


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    baseline = stats["baseline"]
    edge = f", edge_over_random={baseline.edge_over_random:.3f}" if baseline is not None else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}{edge}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== RANGE_MEAN_REVERSION Task 2: Three-Tier Sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"[{r['tier']}] {r['asset']} / {r['timeframe']}: SKIPPED — {r['error']}")
            continue
        lines.append(
            f"[{r['tier']}] {r['asset']} / {r['timeframe']}: {r['verdict']} — "
            f"TRAIN {_fmt_half(r['train'])} | TEST {_fmt_half(r['test'])} ({r['candle_count']} candles)"
        )
    qualifying = find_qualifying(rows)
    lines.append("")
    lines.append(f"=== {len(qualifying)} configs qualify for grid-shift verification ===")
    for r in qualifying:
        lines.append(f"  [{r['tier']}] {r['asset']} / {r['timeframe']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
