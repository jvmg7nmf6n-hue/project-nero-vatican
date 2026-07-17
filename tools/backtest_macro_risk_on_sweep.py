"""CLI: MACRO_RISK_ON (macro-risk-on-v1.0.0) — DAILY timeframe only, BTC and GOLD.
Full-history backtest plus a strict chronological 70/30 train/test split, reporting
% of days risk-on, trade counts, and standard metrics per half with LOW SAMPLE flags.

STRICT SPLIT: matching every other split tool in this codebase (see
tools.backtest_train_test_split's docstring — "no information crosses the boundary in
either direction"), the train half's regime is built using ONLY macro data up to the
train candles' own last date, and the test half's regime is built using ONLY macro data
from the test candles' own first date onward — the test half gets its own 20-day-change
warmup from scratch, discarding all pre-test macro history, even though that history is
real past data a live system would have had. This is a deliberate consistency choice
with the rest of the project's split methodology, not a lookahead concern (using
continuous macro history WOULD be legitimate for a live system — see docs).

No synthetic/fabricated price or macro data is ever used — if any fetch fails, that
half/asset is reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_macro_risk_on_sweep.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.macro_data import (
    MacroDataUnavailableError,
    build_regime_frame,
    fetch_dfii10_daily,
    fetch_dollar_proxy_daily,
)
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.macro_risk_on import DEFAULT_PARAMETERS, STRATEGY_VERSION, run_macro_risk_on_backtest
from tools.backtest_compare import compute_metrics
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
STRATEGY_LABEL = f"MACRO_RISK_ON ({STRATEGY_VERSION})"
ASSETS = ["BTC", "GOLD"]


def _pct_risk_on(regime_frame: pd.DataFrame) -> float:
    known = regime_frame.dropna(subset=["dollar_change_20d", "dfii10_change_20d"])
    if known.empty:
        return 0.0
    return float(known["risk_on"].mean() * 100.0)


def _metrics_row(trades: list, state, regime_frame: pd.DataFrame) -> dict[str, object]:
    m = compute_metrics("", STRATEGY_LABEL, state, trades)
    return {
        "candles": len(regime_frame),
        "pct_risk_on": _pct_risk_on(regime_frame),
        "trades": m.sample_size,
        "win_rate": m.win_rate,
        "expectancy_r": m.expectancy_r,
        "profit_factor": m.profit_factor,
        "max_drawdown": m.max_drawdown,
        "below_min_sample": m.insufficient_sample,
    }


def _slice_macro_from(series: pd.Series, start_date: pd.Timestamp) -> pd.Series:
    return series[series.index >= start_date]


def _slice_macro_until(series: pd.Series, end_date: pd.Timestamp) -> pd.Series:
    return series[series.index <= end_date]


def run_asset(asset: str, client: MarketDataClient, dollar_series: pd.Series, dfii10_series: pd.Series) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, asset, "24h")
    except MarketDataUnavailableError as exc:
        return {"asset": asset, "error": f"candle fetch failed: {exc}"}

    train_candles, test_candles = split_chronological(candles)
    if train_candles.empty or test_candles.empty:
        return {"asset": asset, "error": "not enough daily history to split 70/30"}

    train_end = pd.to_datetime(train_candles["date"]).dt.tz_localize(None).max()
    test_start = pd.to_datetime(test_candles["date"]).dt.tz_localize(None).min()

    full_regime = build_regime_frame(candles, dollar_series, dfii10_series)
    train_regime = build_regime_frame(train_candles, _slice_macro_until(dollar_series, train_end), _slice_macro_until(dfii10_series, train_end))
    test_regime = build_regime_frame(test_candles, _slice_macro_from(dollar_series, test_start), _slice_macro_from(dfii10_series, test_start))

    full_trades, full_state = run_macro_risk_on_backtest(full_regime, DEFAULT_PARAMETERS)
    train_trades, train_state = run_macro_risk_on_backtest(train_regime, DEFAULT_PARAMETERS)
    test_trades, test_state = run_macro_risk_on_backtest(test_regime, DEFAULT_PARAMETERS)

    return {
        "asset": asset,
        "candle_source": method,
        "full": _metrics_row(full_trades, full_state, full_regime),
        "train": _metrics_row(train_trades, train_state, train_regime),
        "test": _metrics_row(test_trades, test_state, test_regime),
    }


def run_sweep() -> list[dict[str, object]]:
    client = MarketDataClient()

    dollar_series, dollar_source = fetch_dollar_proxy_daily()
    print(f"Dollar proxy: {dollar_source} ({len(dollar_series)} business days)")
    dfii10_series, dfii10_source = fetch_dfii10_daily()
    print(f"DFII10: {dfii10_source} ({len(dfii10_series)} business days)")

    results = []
    for asset in ASSETS:
        r = run_asset(asset, client, dollar_series, dfii10_series)
        results.append(r)
        if "error" in r:
            print(f"{asset}: SKIPPED — {r['error']}")
        else:
            print(f"{asset}: OK — {r['candle_source']} ({r['full']['candles']} candles)")
    return results


def _fmt_row(label: str, cell: dict[str, object]) -> str:
    pf = cell["profit_factor"]
    pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
    flag = "*** LOW SAMPLE ***" if cell["below_min_sample"] else ""
    return (
        f"  {label:<6} candles={cell['candles']:>5}  risk-on={cell['pct_risk_on']:>5.1f}%  "
        f"N={cell['trades']:>4} Win={cell['win_rate'] * 100:>5.1f}% ExpR={cell['expectancy_r']:>7.3f} "
        f"PF={pf_display:>6} MaxDD={cell['max_drawdown'] * 100:>6.1f}%  {flag}"
    )


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for r in results:
        lines.append(f"=== {r['asset']} ===")
        if "error" in r:
            lines.append(f"  SKIPPED — {r['error']}")
            lines.append("")
            continue
        lines.append(_fmt_row("FULL", r["full"]))
        lines.append(_fmt_row("TRAIN", r["train"]))
        lines.append(_fmt_row("TEST", r["test"]))
        lines.append("")
    lines.append("* below-20-trade cells are flagged LOW SAMPLE — regime strategies trade infrequently by design.")
    return "\n".join(lines)


def main() -> None:
    try:
        results = run_sweep()
    except MacroDataUnavailableError as exc:
        print(f"BLOCKED — {exc}")
        return

    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
