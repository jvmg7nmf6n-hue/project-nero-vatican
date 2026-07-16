"""CLI: run all three VOLATILITY_SQUEEZE trend-filter variants (ma200/ma150/ma100)
through the standard timeframe set (2h, 4h, 12h, 24h, 1week) across all 8 assets, in one
pass — reporting FULL-period, chronological TRAIN (first 70%), and TEST (last 30%)
metrics side by side per row, plus how many candles each variant's trend filter blocked.

Fee convention: crypto default fee_bps/slippage_bps for every asset except GOLD, which
gets the measured BTC/GOLD price-to-ATR fee rescaling (nero_core.strategies.
mean_reversion_gold_calibrated). Max holding is timeframe-aware: 24 candles of whichever
timeframe is being tested, same convention used to fix MEAN_REVERSION/BREAKOUT_MOMENTUM's
GOLD 1week bug (nero_core.strategies.mean_reversion_gold_calibrated_1week). Both are
derived per (asset, timeframe) via volatility_squeeze.build_params_for_run — nothing about
any registered strategy variant is mutated; these are ephemeral, honestly-derived clones
used only for this run, the same relationship VARIANT_SPECS already has with
GOLD_CALIBRATED_PARAMETERS in backtest_compare.py.

No synthetic/fabricated price data is ever used — if a fetch fails for an asset/timeframe,
that combination is reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_volatility_squeeze_sweep.py
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.mean_reversion import MeanReversionState, evaluate_exit, reset_daily_guard_if_needed
from nero_core.strategies.volatility_squeeze import (
    DEFAULT_PARAMETERS_MA100,
    DEFAULT_PARAMETERS_MA150,
    DEFAULT_PARAMETERS_MA200,
    add_indicators,
    build_params_for_run,
    evaluate_entry,
    size_entry,
)
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, BacktestMetrics, VariantSpec, compute_metrics
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import ASSETS, STANDARD_TIMEFRAMES, fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

# (key, display label, canonical/base parameters — trend_ma_period is the only field
# that differs between them; everything else, incl. the per-run timeframe/fee
# recalibration, is applied identically via build_params_for_run).
VARIANTS: list[tuple[str, str, object]] = [
    ("ma200", "VOLATILITY_SQUEEZE ma200", DEFAULT_PARAMETERS_MA200),
    ("ma150", "VOLATILITY_SQUEEZE ma150", DEFAULT_PARAMETERS_MA150),
    ("ma100", "VOLATILITY_SQUEEZE ma100", DEFAULT_PARAMETERS_MA100),
]

TREND_FILTER_REASON = "CLOSE_NOT_ABOVE_TREND_MA"


def _make_spec(label: str, params) -> VariantSpec:
    return VariantSpec(
        key=label,
        label=label,
        params=params,
        add_indicators_fn=add_indicators,
        evaluate_entry_fn=lambda candle, as_of_intraday, as_of_daily, state, p, asset: evaluate_entry(candle, state, p),
        size_entry_fn=size_entry,
        needs_daily=False,
    )


def run_backtest_with_reason_tally(
    candles: pd.DataFrame, spec: VariantSpec
) -> tuple[list, MeanReversionState, Counter, int]:
    """Same candle-by-candle loop as tools.backtest_compare.run_backtest, but also tallies
    every entry-rejection reason across all evaluated candles (not just closed trades) —
    needed to report how many candles each variant's trend filter blocked. Kept as its own
    loop (rather than changing run_backtest's return contract) since every other tool
    relies on run_backtest's existing (trades, state) signature."""
    state = MeanReversionState(equity=spec.params.initial_equity)
    enriched = spec.add_indicators_fn(candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    closed_trades: list = []
    reason_counts: Counter = Counter()

    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        reset_daily_guard_if_needed(state, candle["date"])

        exit_event = evaluate_exit(candle, state, spec.params)
        if exit_event is not None:
            closed_trades.append(exit_event)

        evaluation = spec.evaluate_entry_fn(candle, evaluable.iloc[: i + 1], None, state, spec.params, "")
        reason_counts.update(evaluation.reasons)

        if evaluation.passed:
            trade = spec.size_entry_fn(candle, state, spec.params)
            if trade is not None:
                state.open_trade = trade

    return closed_trades, state, reason_counts, len(evaluable)


def _metrics_cell(metrics: BacktestMetrics) -> dict[str, object]:
    return {
        "trades": metrics.sample_size,
        "win_rate": metrics.win_rate,
        "expectancy_r": metrics.expectancy_r,
        "profit_factor": metrics.profit_factor,
        "below_min_sample": metrics.sample_size < MIN_SAMPLE_SIZE,
    }


def _empty_cell(reason: str) -> dict[str, object]:
    return {
        "trades": 0,
        "win_rate": 0.0,
        "expectancy_r": 0.0,
        "profit_factor": 0.0,
        "below_min_sample": True,
        "skip_reason": reason,
    }


def run_sweep(
    assets: list[str],
    timeframes: list[str],
    client: MarketDataClient,
) -> tuple[list[dict[str, object]], dict[str, dict[str, int]]]:
    rows: list[dict[str, object]] = []
    trend_filter_totals = {key: {"evaluated": 0, "blocked": 0} for key, _, _ in VARIANTS}

    for asset in assets:
        for timeframe in timeframes:
            start = time.monotonic()
            try:
                candles, method = fetch_timeframe_candles(client, asset, timeframe)
            except MarketDataUnavailableError as exc:
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
                for key, label, _ in VARIANTS:
                    rows.append(_skip_row(asset, timeframe, key, label, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - one combo's failure must not lose the rest
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                for key, label, _ in VARIANTS:
                    rows.append(_skip_row(asset, timeframe, key, label, f"{exc.__class__.__name__}: {exc}"))
                continue

            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe}: {method} — {len(candles)} candles ({elapsed:.1f}s)")
            train, test = split_chronological(candles)

            for key, label, base_params in VARIANTS:
                params = build_params_for_run(base_params, timeframe, asset)
                spec = _make_spec(label, params)

                full_trades, full_state, full_reasons, full_n = run_backtest_with_reason_tally(candles, spec)
                train_trades, train_state, _, _ = run_backtest_with_reason_tally(train, spec)
                test_trades, test_state, _, _ = run_backtest_with_reason_tally(test, spec)

                trend_filter_totals[key]["evaluated"] += full_n
                trend_filter_totals[key]["blocked"] += full_reasons.get(TREND_FILTER_REASON, 0)

                rows.append(
                    {
                        "asset": asset,
                        "timeframe": timeframe,
                        "variant_key": key,
                        "variant": label,
                        "full": _metrics_cell(compute_metrics(asset, label, full_state, full_trades)),
                        "train": _metrics_cell(compute_metrics(asset, label, train_state, train_trades)),
                        "test": _metrics_cell(compute_metrics(asset, label, test_state, test_trades)),
                    }
                )

    return rows, trend_filter_totals


def _skip_row(asset: str, timeframe: str, variant_key: str, variant_label: str, reason: str) -> dict[str, object]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "variant_key": variant_key,
        "variant": variant_label,
        "full": _empty_cell(reason),
        "train": _empty_cell(reason),
        "test": _empty_cell(reason),
    }


def _fmt_cell(cell: dict[str, object]) -> str:
    if "skip_reason" in cell:
        return f"{'SKIP':>4} {'':>6} {'':>7} {'':>6}"
    pf = cell["profit_factor"]
    pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
    flag = "*" if cell["below_min_sample"] else " "
    return f"{cell['trades']:>4} {cell['win_rate'] * 100:>5.1f}% {cell['expectancy_r']:>7.3f} {pf_display:>6}{flag}"


def format_consolidated_table(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    group_header = f"{'':<6}{'':<10}{'':<26}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Asset':<6}{'TF':<10}{'Variant':<26}"
        f"{'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6}"
    )
    lines.append(group_header)
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        skip_reason = row["full"].get("skip_reason")
        if skip_reason is not None:
            lines.append(f"{row['asset']:<6}{row['timeframe']:<10}{row['variant']:<26} SKIPPED — {skip_reason}")
            continue
        lines.append(
            f"{row['asset']:<6}{row['timeframe']:<10}{row['variant']:<26}"
            f"{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def format_trend_filter_summary(trend_filter_totals: dict[str, dict[str, int]]) -> str:
    lines: list[str] = ["", "Trend filter block counts (full-period runs, all assets/timeframes combined):"]
    for key, label, _ in VARIANTS:
        totals = trend_filter_totals[key]
        evaluated = totals["evaluated"]
        blocked = totals["blocked"]
        pct = (blocked / evaluated * 100.0) if evaluated else 0.0
        lines.append(f"  {label:<26} blocked {blocked:>6} / {evaluated:>6} evaluated candles ({pct:5.1f}%)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=ASSETS)
    parser.add_argument("--timeframes", nargs="+", default=STANDARD_TIMEFRAMES, choices=STANDARD_TIMEFRAMES)
    args = parser.parse_args()

    client = MarketDataClient()
    rows, trend_filter_totals = run_sweep(args.assets, args.timeframes, client)

    print()
    print(format_consolidated_table(rows))
    print(format_trend_filter_summary(trend_filter_totals))


if __name__ == "__main__":
    main()
