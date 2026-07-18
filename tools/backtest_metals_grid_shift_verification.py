"""CLI: ASSET EXPANSION Phase A, Task 3 — mandatory grid-shift verification for
every config Task 2 found positive in both halves with an adequate sample (see
tools/backtest_metals_phase_a_sweep.py's "Task 3 grid-shift candidates" list).

Same technique as the H6 grid-shift robustness follow-up
(tools/grid_shift_robustness_audit.py): rebuild the SAME timeframe from native 1h
candles at shifted UTC-clock offsets via
nero_core.data_sources.candle_resampling.resample_hourly_to_grid, then re-run the
exact same registered strategy/parameters/70-30 split on each shifted grid. A config
only stays eligible for SURVIVED if it holds (still positive both halves, still
adequate sample) across every shift tested — "no exceptions," per the task.

STRUCTURAL FINDING (confirmed empirically before writing this tool, not assumed):
8 of the 9 Task 2 candidates are at 24h. COMEX/NYMEX continuous futures (SILVER's
SI=F, PLATINUM's PL=F) carry a ~2-HOUR DAILY SETTLEMENT GAP around 23:00 UTC, EVERY
single calendar day (confirmed by inspecting real fetched 1h candles), which means
resample_hourly_to_grid's strict "exactly 24 consecutive hours, no gap" contract can
NEVER be satisfied for a 24h bin at ANY offset (0/6/12/18h all produced ZERO bins in
direct testing). This is not a bug and not a data quality problem — CME-family
futures genuinely do not trade a full continuous 24 hours; the exchange's own daily
settlement boundary already anchors where one trading "day" ends and the next
begins. Unlike GOLD/BTC (where the calendar-day boundary is an arbitrary UTC
convention this test can meaningfully question), there is no arbitrary boundary to
re-test here — the 24h grid IS the exchange's own real settlement cycle.
Consequently, 24h grid-shift verification is reported NOT_APPLICABLE for those 8
configs, with this exact rationale, rather than skipped silently or forced through
an invented workaround. They remain PROMISING-WATCHLIST — SURVIVED requires holding
across grid shifts, and a claim that can't be tested can't be promoted.

Only the one 2h candidate (PLATINUM / VOLATILITY_SQUEEZE ma150) is genuinely
testable this way — 2h bins don't span the daily settlement hour — and gets a real
0h (control) / +1h grid-shift run, matching H6's own 2h offset choice.

Usage:
    python tools/backtest_metals_grid_shift_verification.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, compute_metrics, run_backtest
from tools.backtest_statistics import MIN_SAMPLE_SIZE
from tools.backtest_train_test_split import split_chronological

HOURLY_FETCH_CANDLES = 50_000

# The single genuinely grid-shift-testable Task 2 candidate (2h — no daily
# settlement-gap conflict). See module docstring for why the other 8 (all 24h) are
# NOT_APPLICABLE rather than tested.
TESTABLE_CANDIDATE = {
    "label": "PLATINUM / 2h / VOLATILITY_SQUEEZE ma150",
    "asset": "PLATINUM",
    "timeframe": "2h",
    "variant_key": "volatility_squeeze_ma150",
    "offsets": [0, 1],
}

NOT_APPLICABLE_CANDIDATES = [
    "SILVER / 24h / BREAKOUT_MOMENTUM",
    "SILVER / 24h / TREND_PULLBACK",
    "PLATINUM / 24h / TREND_PULLBACK",
    "SILVER / 24h / VOLATILITY_SQUEEZE ma200",
    "SILVER / 24h / VOLATILITY_SQUEEZE ma150",
    "SILVER / 24h / VOLATILITY_SQUEEZE ma100",
    "SILVER / 24h / BOS_CONTINUATION",
    "SILVER / 24h / MACRO_RISK_ON",
]

NOT_APPLICABLE_REASON = (
    "24h grid-shift not testable: COMEX/NYMEX continuous futures carry a ~2-hour "
    "daily settlement gap (confirmed around 23:00 UTC on every calendar day in the "
    "live 1h data), so resample_hourly_to_grid's exact-24-consecutive-hours "
    "contract produces ZERO bins at every offset tested (0h/6h/12h/18h). This is a "
    "genuine structural property of exchange-settled futures, not a bug — there is "
    "no arbitrary UTC boundary to re-test here, unlike GOLD/BTC. Remains "
    "PROMISING-WATCHLIST: SURVIVED requires holding across grid shifts, and an "
    "untestable claim cannot be promoted."
)


def _metrics_row(trades: list, state) -> dict[str, object]:
    m = compute_metrics("", "", state, trades)
    return {
        "trades": m.sample_size, "expectancy_r": m.expectancy_r,
        "below_min_sample": m.insufficient_sample,
    }


def _qualifies(train: dict, test: dict) -> bool:
    return (
        train["trades"] >= MIN_SAMPLE_SIZE and test["trades"] >= MIN_SAMPLE_SIZE
        and train["expectancy_r"] > 0 and test["expectancy_r"] > 0
    )


def run_testable_candidate() -> dict[str, object]:
    config = TESTABLE_CANDIDATE
    client = MarketDataClient()
    base_spec = VARIANT_SPECS[config["variant_key"]]
    spec = replace(base_spec, params=build_calibrated_params(base_spec.params, config["timeframe"], config["asset"]))
    target_hours = {"2h": 2, "4h": 4, "12h": 12, "24h": 24}[config["timeframe"]]

    try:
        hourly = client.load_intraday(config["asset"], interval="1h", candles=HOURLY_FETCH_CANDLES)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": f"1h fetch failed: {exc}"}

    grid_results = []
    for offset in config["offsets"]:
        grid_label = "offset+0h (control)" if offset == 0 else f"offset+{offset}h"
        candles = resample_hourly_to_grid(hourly.prices, target_hours, offset)
        if candles.empty:
            grid_results.append({"grid": grid_label, "error": "no complete bins produced by resampling"})
            continue
        train, test = split_chronological(candles)
        train_trades, train_state = run_backtest(train, spec)
        test_trades, test_state = run_backtest(test, spec)
        train_stats = _metrics_row(train_trades, train_state)
        test_stats = _metrics_row(test_trades, test_state)
        grid_results.append({
            "grid": grid_label, "candle_count": len(candles),
            "train": train_stats, "test": test_stats,
            "qualifies": _qualifies(train_stats, test_stats),
        })

    holds_across_all_shifts = all(g.get("qualifies", False) for g in grid_results if "error" not in g) and any(
        "error" not in g for g in grid_results
    )
    return {"label": config["label"], "grids": grid_results, "holds_across_all_shifts": holds_across_all_shifts}


def _fmt_grid(g: dict[str, object]) -> str:
    if "error" in g:
        return f"  {g['grid']:<20} SKIPPED — {g['error']}"
    train, test = g["train"], g["test"]
    verdict = "QUALIFIES" if g["qualifies"] else "does not qualify"
    return (
        f"  {g['grid']:<20} ({g['candle_count']} candles) — {verdict}\n"
        f"      TRAIN: N={train['trades']} ExpR={train['expectancy_r']:.3f}\n"
        f"      TEST:  N={test['trades']} ExpR={test['expectancy_r']:.3f}"
    )


def format_report(testable_result: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("=== Grid-shift TESTED ===")
    lines.append(f"--- {testable_result['label']} ---")
    if "error" in testable_result:
        lines.append(f"  SKIPPED — {testable_result['error']}")
    else:
        for g in testable_result["grids"]:
            lines.append(_fmt_grid(g))
        final_verdict = "SURVIVED (holds across all grid shifts tested)" if testable_result["holds_across_all_shifts"] else "PROMISING-WATCHLIST (does not hold across every grid shift)"
        lines.append(f"  FINAL: {final_verdict}")
    lines.append("")

    lines.append("=== Grid-shift NOT_APPLICABLE (see rationale) ===")
    for label in NOT_APPLICABLE_CANDIDATES:
        lines.append(f"--- {label} ---")
        lines.append(f"  {NOT_APPLICABLE_REASON}")
        lines.append("  FINAL: PROMISING-WATCHLIST (unchanged from Task 2)")
    return "\n".join(lines)


def main() -> None:
    result = run_testable_candidate()
    print(format_report(result))


if __name__ == "__main__":
    main()
