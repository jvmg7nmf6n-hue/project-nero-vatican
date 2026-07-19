"""CLI: RMR Variant Research Cycle — Stage 3, refine (max 2, diagnosis-justified,
same-scope) + grid-shift where applicable.

REFINEMENT 1 — RMR_LONG_ONLY_CONFIRMATION_BTC_1D (range-mean-reversion-v1.4.0-long-
only-confirmation): stacks v1.1.0-long-only's allow_short=False onto v1.3.0-
confirmation's entry pattern, citing Stage 2(b)'s short-leg-cost finding (~-0.264
R/trade on BTC/1d) and Stage 2(d)'s exit-mix finding (confirmation shifted BTC/1d
from 32% to 68% REVERSION_TARGET) — BOTH diagnosed on BTC/1d specifically. Tested
ONLY on BTC/1d.

REFINEMENT 2 — apply the EXISTING range-mean-reversion-v1.1.0-long-only variant to
ETH/4h (no new strategy code/version needed — the same diagnosis-backed filter
already registered in Stage 1, applied to the one asset where Stage 1's OTHER
filter, adx-falling, was diagnosed as weakest/most inconsistent). Citing Stage 2(b)'s
finding that the short leg was substantially costly on the two assets actually
measured (EUR/USD, BTC) — this refinement tests whether ETH's own short leg carries
the same real cost, which its adx-falling variant never addressed. Tested ONLY on
ETH/4h.

GRID-SHIFT: BTC/1d is structurally limited (native daily data, per this task's own
rule) — capped at PROMISING-WATCHLIST if positive both halves, not tested. ETH/4h IS
resample-testable (crypto trades continuously — confirmed directly: resample_hourly_
to_grid produces a full, identical bin count for every offset 0-3h, unlike forex's
Friday-close gap or metals' daily settlement gap) — tested for real if it qualifies.

Usage:
    python -m tools.rmr_variant_research_stage3
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.range_mean_reversion import run_backtest as v1_run_backtest
from nero_core.strategies.range_mean_reversion_confirmation import run_backtest as confirmation_run_backtest
from nero_core.strategies.range_mean_reversion_long_only import LONG_ONLY_PARAMETERS
from nero_core.strategies.range_mean_reversion_long_only_confirmation import LONG_ONLY_CONFIRMATION_PARAMETERS
from tools.backtest_statistics import MIN_SAMPLE_SIZE
from tools.backtest_train_test_split import split_chronological
from tools.rmr_variant_research_stage1 import _half_stats
from tools.timeframe_data import fetch_timeframe_candles

GRID_SHIFT_OFFSETS = [0, 1, 2, 3]


def _qualifies(train: dict, test: dict) -> bool:
    return (
        train["trades"] >= MIN_SAMPLE_SIZE and test["trades"] >= MIN_SAMPLE_SIZE
        and train["expectancy_r"] > 0 and test["expectancy_r"] > 0
    )


def run_refinement1_btc_1d() -> dict[str, object]:
    """RMR_LONG_ONLY_CONFIRMATION_BTC_1D — grid-shift NOT_APPLICABLE (native daily)."""
    client = MarketDataClient()
    try:
        btc, _method = fetch_timeframe_candles(client, "BTC", "24h")
    except MarketDataUnavailableError as exc:
        return {"label": "BTC/1d v1.4.0-long-only-confirmation", "error": str(exc)}

    start = time.monotonic()
    train, test = split_chronological(btc)
    train_stats = _half_stats(train, LONG_ONLY_CONFIRMATION_PARAMETERS, confirmation_run_backtest)
    test_stats = _half_stats(test, LONG_ONLY_CONFIRMATION_PARAMETERS, confirmation_run_backtest)
    elapsed = time.monotonic() - start
    print(f"BTC/1d v1.4.0-long-only-confirmation: done ({elapsed:.1f}s)")

    positive_both_halves = train_stats["expectancy_r"] > 0 and test_stats["expectancy_r"] > 0
    grid_shift_note = (
        "NOT_APPLICABLE — native daily data, structurally limited per this task's own "
        "grid-shift rule for 1d configs; capped at PROMISING-WATCHLIST if positive "
        "both halves, not tested."
    )
    return {
        "label": "BTC/1d v1.4.0-long-only-confirmation (RMR_LONG_ONLY_CONFIRMATION_BTC_1D)",
        "candle_count": len(btc), "train": train_stats, "test": test_stats,
        "positive_both_halves": positive_both_halves, "grid_shift": grid_shift_note,
    }


def run_refinement2_eth_4h() -> dict[str, object]:
    """v1.1.0-long-only applied to ETH/4h — grid-shift genuinely testable (crypto
    trades continuously, no structural gap unlike forex/metals)."""
    client = MarketDataClient()
    try:
        hourly = client.load_intraday("ETH", interval="1h", candles=50_000)
    except MarketDataUnavailableError as exc:
        return {"label": "ETH/4h v1.1.0-long-only", "error": str(exc)}

    start = time.monotonic()
    control = resample_hourly_to_grid(hourly.prices, 4, 0)
    train, test = split_chronological(control)
    train_stats = _half_stats(train, LONG_ONLY_PARAMETERS, v1_run_backtest)
    test_stats = _half_stats(test, LONG_ONLY_PARAMETERS, v1_run_backtest)
    elapsed = time.monotonic() - start
    print(f"ETH/4h v1.1.0-long-only (control grid): done ({elapsed:.1f}s)")

    qualifies = _qualifies(train_stats, test_stats)
    grid_results = []
    if qualifies:
        for offset in GRID_SHIFT_OFFSETS:
            g_start = time.monotonic()
            candles = resample_hourly_to_grid(hourly.prices, 4, offset)
            g_train, g_test = split_chronological(candles)
            g_train_stats = _half_stats(g_train, LONG_ONLY_PARAMETERS, v1_run_backtest)
            g_test_stats = _half_stats(g_test, LONG_ONLY_PARAMETERS, v1_run_backtest)
            print(f"  ETH/4h offset+{offset}h: done ({time.monotonic()-g_start:.1f}s, {len(candles)} candles)")
            grid_results.append({
                "offset": offset, "candle_count": len(candles),
                "train": g_train_stats, "test": g_test_stats,
                "qualifies": _qualifies(g_train_stats, g_test_stats),
            })

    return {
        "label": "ETH/4h v1.1.0-long-only (Stage 3 Refinement 2)",
        "candle_count": len(control), "train": train_stats, "test": test_stats,
        "qualifies_control": qualifies, "grid_results": grid_results,
    }


def format_report(refinement1: dict[str, object], refinement2: dict[str, object]) -> str:
    lines = ["=== RMR Variant Research Cycle — Stage 3 ===", ""]

    lines.append("--- Refinement 1: RMR_LONG_ONLY_CONFIRMATION_BTC_1D ---")
    if "error" in refinement1:
        lines.append(f"  SKIPPED — {refinement1['error']}")
    else:
        r = refinement1
        lines.append(f"  {r['label']} ({r['candle_count']} candles)")
        lines.append(f"    TRAIN: N={r['train']['trades']}{'*' if r['train']['below_min_sample'] else ''} ExpR={r['train']['expectancy_r']:.3f}")
        lines.append(f"    TEST:  N={r['test']['trades']}{'*' if r['test']['below_min_sample'] else ''} ExpR={r['test']['expectancy_r']:.3f}")
        lines.append(f"    Positive both halves: {r['positive_both_halves']}")
        lines.append(f"    Grid-shift: {r['grid_shift']}")
    lines.append("")

    lines.append("--- Refinement 2: v1.1.0-long-only on ETH/4h ---")
    if "error" in refinement2:
        lines.append(f"  SKIPPED — {refinement2['error']}")
    else:
        r = refinement2
        lines.append(f"  {r['label']} — control grid ({r['candle_count']} candles)")
        lines.append(f"    TRAIN: N={r['train']['trades']}{'*' if r['train']['below_min_sample'] else ''} ExpR={r['train']['expectancy_r']:.3f}")
        lines.append(f"    TEST:  N={r['test']['trades']}{'*' if r['test']['below_min_sample'] else ''} ExpR={r['test']['expectancy_r']:.3f}")
        lines.append(f"    Qualifies for grid-shift: {r['qualifies_control']}")
        if r["grid_results"]:
            for g in r["grid_results"]:
                lines.append(
                    f"    offset+{g['offset']}h ({g['candle_count']} candles): "
                    f"TRAIN N={g['train']['trades']} ExpR={g['train']['expectancy_r']:.3f} | "
                    f"TEST N={g['test']['trades']} ExpR={g['test']['expectancy_r']:.3f} -> "
                    f"{'QUALIFIES' if g['qualifies'] else 'does not qualify'}"
                )
            holds = all(g["qualifies"] for g in r["grid_results"])
            lines.append(f"    Holds across all grid shifts: {holds}")
        else:
            lines.append("    (control grid did not qualify — no grid-shift run)")
    return "\n".join(lines)


def main() -> None:
    refinement1 = run_refinement1_btc_1d()
    refinement2 = run_refinement2_eth_4h()
    print()
    print(format_report(refinement1, refinement2))


if __name__ == "__main__":
    main()
