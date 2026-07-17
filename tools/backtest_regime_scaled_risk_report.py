"""CLI: H3 hypothesis — compare v1 (fixed risk_per_trade) against the regime-scaled-risk
variant (v2) on IDENTICAL data, for the two configurations named in the hypothesis:
BNB/12h TREND_PULLBACK and GOLD/1week BREAKOUT_MOMENTUM gold-calibrated. Only the
per-trade risk budget differs between each pair — entries, exits, and stops are
byte-for-byte identical (see nero_core.strategies.regime_risk and the two
*_regime_scaled_risk variant modules).

Reports, full period + chronological train(70%)/test(30%): trade count, ExpR
(expectancy in R), mean and std of per-trade R, max drawdown, and total return (net
PnL on a $10,000 starting equity).

No synthetic/fabricated price data is ever used — if a fetch fails, this is reported
plainly, not silently substituted.

Usage:
    python tools/backtest_regime_scaled_risk_report.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, VariantSpec, run_backtest
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

COMPARISONS = [
    {
        "asset": "BNB",
        "timeframe": "12h",
        "v1_key": "trend_pullback",
        "v2_key": "trend_pullback_regime_scaled_risk",
        # trend_pullback's registered params are a 1h-reference default (max_holding_hours=24)
        # — MUST be recalibrated for 12h candles before use, same lesson as the GOLD 1week fix
        # earlier this session. Skipping this would force nearly every trade closed via TIME
        # after just 2 candles, corrupting the comparison.
        "needs_timeframe_calibration": True,
    },
    {
        "asset": "GOLD",
        "timeframe": "1week",
        "v1_key": "breakout_momentum_gold_calibrated_1week",
        "v2_key": "breakout_momentum_gold_calibrated_1week_regime_scaled_risk",
        # Already fully calibrated (GOLD fees + 1week holding cap baked into its registered
        # params) — re-running build_calibrated_params here would double-apply the GOLD fee
        # scale factor. Do NOT recalibrate.
        "needs_timeframe_calibration": False,
    },
]

# The two v2 modules aren't wired into tools.backtest_compare.VARIANT_SPECS (that
# module intentionally only holds variants meant for the general-purpose sweep tools);
# build their VariantSpecs here directly, reusing the same add_indicators/evaluate_entry/
# size_entry functions as their v1 counterparts (identical entry/exit logic, only params
# differ) with each pair's `v2` params substituted in.


def _v2_spec(v1_spec: VariantSpec, v2_params) -> VariantSpec:
    return replace(v1_spec, params=v2_params)


def _build_specs() -> dict[str, VariantSpec]:
    from nero_core.strategies.breakout_momentum_gold_calibrated_1week_regime_scaled_risk import (
        PARAMETERS as BM_GOLD_1WEEK_V2_PARAMETERS,
    )
    from nero_core.strategies.trend_pullback_regime_scaled_risk import PARAMETERS as TP_V2_PARAMETERS

    return {
        "trend_pullback_regime_scaled_risk": _v2_spec(VARIANT_SPECS["trend_pullback"], TP_V2_PARAMETERS),
        "breakout_momentum_gold_calibrated_1week_regime_scaled_risk": _v2_spec(
            VARIANT_SPECS["breakout_momentum_gold_calibrated_1week"], BM_GOLD_1WEEK_V2_PARAMETERS
        ),
    }


def _trade_stats(trades: list, state) -> dict[str, object]:
    r_values = [t.r_multiple for t in trades]
    n = len(trades)
    mean_r = sum(r_values) / n if n else 0.0
    if n > 1:
        variance = sum((r - mean_r) ** 2 for r in r_values) / (n - 1)
        std_r = variance ** 0.5
    else:
        std_r = 0.0
    peak = float("-inf")
    max_dd = 0.0
    running_equity = state.equity - sum(t.net_pnl for t in trades)  # starting equity
    equity_curve = []
    equity = running_equity
    for t in trades:
        equity += t.net_pnl
        equity_curve.append(equity)
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, (value - peak) / peak)
    total_return_pct = ((state.equity / running_equity) - 1.0) * 100.0 if running_equity else 0.0
    return {
        "trades": n,
        "expectancy_r": mean_r,
        "std_r": std_r,
        "max_drawdown": max_dd,
        "net_pnl": sum(t.net_pnl for t in trades),
        "total_return_pct": total_return_pct,
        "below_min_sample": n < MIN_SAMPLE_SIZE,
    }


def run_report() -> list[dict[str, object]]:
    client = MarketDataClient()
    specs = _build_specs()
    results: list[dict[str, object]] = []

    for comparison in COMPARISONS:
        asset, timeframe = comparison["asset"], comparison["timeframe"]
        try:
            candles, method = fetch_timeframe_candles(client, asset, timeframe)
        except MarketDataUnavailableError as exc:
            results.append({"asset": asset, "timeframe": timeframe, "error": str(exc)})
            continue

        train, test = split_chronological(candles)
        v1_spec = VARIANT_SPECS[comparison["v1_key"]]
        v2_spec = specs[comparison["v2_key"]]
        if comparison["needs_timeframe_calibration"]:
            v1_spec = replace(v1_spec, params=build_calibrated_params(v1_spec.params, timeframe, asset))
            v2_spec = replace(v2_spec, params=build_calibrated_params(v2_spec.params, timeframe, asset))

        row = {"asset": asset, "timeframe": timeframe, "method": method, "candle_count": len(candles), "variants": []}
        for label, spec in (("v1 (fixed risk)", v1_spec), ("v2 (regime-scaled risk)", v2_spec)):
            full_trades, full_state = run_backtest(candles, spec)
            train_trades, train_state = run_backtest(train, spec)
            test_trades, test_state = run_backtest(test, spec)
            row["variants"].append(
                {
                    "label": label,
                    "full": _trade_stats(full_trades, full_state),
                    "train": _trade_stats(train_trades, train_state),
                    "test": _trade_stats(test_trades, test_state),
                }
            )
        results.append(row)

    return results


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['asset']} / {row['timeframe']}: SKIPPED — {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['asset']} / {row['timeframe']} — {row['method']} — {row['candle_count']} candles")
        header = f"{'Variant':<24}{'Split':<8}{'N':>5} {'ExpR(meanR)':>12} {'StdR':>8} {'MaxDD':>8} {'NetPnL':>10} {'TotRet%':>9}"
        lines.append(header)
        lines.append("-" * len(header))
        for variant in row["variants"]:
            for split_name in ("full", "train", "test"):
                stats = variant[split_name]
                flag = "*" if stats["below_min_sample"] else " "
                lines.append(
                    f"{variant['label']:<24}{split_name:<8}{stats['trades']:>5}{flag} {stats['expectancy_r']:>12.3f} "
                    f"{stats['std_r']:>8.3f} {stats['max_drawdown'] * 100:>7.1f}% "
                    f"{stats['net_pnl']:>10.2f} {stats['total_return_pct']:>8.2f}%"
                )
        lines.append("-" * len(header))
        lines.append("* = below the 20-trade minimum sample; treat that row as exploratory, not conclusive.")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_report()
    print(format_report(results))


if __name__ == "__main__":
    main()
