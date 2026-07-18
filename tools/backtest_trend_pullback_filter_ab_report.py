"""CLI: Task C filter test — compare unfiltered TREND_PULLBACK v1 (trend-pullback-
v1.0.0) against its two filtered variants on BNB/12h, identical data, through the
upgraded statistical harness (bootstrap 95% CI + random-entry baseline):

  - trend-pullback-v1.3.0-fvg-filtered: adds "at least one OPEN bullish FVG whose
    remaining zone overlaps the last 10 candles' range" on top of the unchanged v1
    entry/stop/target/cap.
  - trend-pullback-v1.4.0-bos-filtered: adds "at least one BOS-up within the last 20
    candles" on top of the same unchanged v1 mechanics.

The question: does each filter raise per-trade quality (higher ExpR, win%, PF, lower
MaxDD), or does it just shrink the sample without improving it? Both filtered
variants' size_entry/evaluate_exit are reused UNCHANGED from v1, so the random-entry
baseline can safely use the same broad trend_pullback_regime_mask v1 itself uses (no
gap/BOS-specific zone data is ever read by their sizing, unlike FVG_REVERSION/
BOS_CONTINUATION themselves).

No synthetic/fabricated price data is ever used — if a fetch fails, this is reported
plainly, not silently substituted.

Usage:
    python tools/backtest_trend_pullback_filter_ab_report.py
"""
from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies import trend_pullback_bos_filtered as bos_filtered_module
from nero_core.strategies import trend_pullback_fvg_filtered as fvg_filtered_module
from nero_core.strategies.mean_reversion import evaluate_exit as shared_evaluate_exit
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS
from tools.backtest_compare import run_backtest as compare_run_backtest
from tools.backtest_statistics import bootstrap_mean_r_ci, random_entry_baseline_single_asset, trend_pullback_regime_mask
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
ASSET = "BNB"
TIMEFRAME = "12h"


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = -math.inf
    drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, (value - peak) / peak)
    return drawdown


def _stats_from_trades(trades: list, evaluable, params) -> dict[str, object]:
    n = len(trades)
    r_values = [t.r_multiple for t in trades]
    wins_r = [t.r_multiple for t in trades if t.net_pnl > 0]
    losses_r = [t.r_multiple for t in trades if t.net_pnl < 0]
    gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))

    expectancy_r = sum(r_values) / n if n else 0.0
    win_pct = len(wins_r) / n if n else 0.0
    avg_win_r = sum(wins_r) / len(wins_r) if wins_r else 0.0
    avg_loss_r = sum(losses_r) / len(losses_r) if losses_r else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss else (gross_win if gross_win else 0.0)
    max_dd = _max_drawdown([t.equity_after for t in trades])

    eligible_mask = trend_pullback_regime_mask(evaluable)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, tp_size_entry, expectancy_r, n, evaluate_exit_fn=shared_evaluate_exit
    )
    return {
        "trades": n,
        "expectancy_r": expectancy_r,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "win_pct": win_pct,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "below_min_sample": n < MIN_SAMPLE_SIZE,
        "ci": ci,
        "baseline": baseline,
    }


def _v1_half_stats(half_candles, spec) -> dict[str, object]:
    trades, _state = compare_run_backtest(half_candles, spec)
    enriched = spec.add_indicators_fn(half_candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    return _stats_from_trades(trades, evaluable, spec.params)


def _fvg_filtered_half_stats(half_candles, params) -> dict[str, object]:
    enriched = fvg_filtered_module.add_indicators(half_candles, params)
    dropna_columns = [c for c in fvg_filtered_module.INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    trades, _state = fvg_filtered_module.run_backtest(evaluable, params)
    return _stats_from_trades(trades, evaluable, params)


def _bos_filtered_half_stats(half_candles, params) -> dict[str, object]:
    enriched = bos_filtered_module.add_indicators(half_candles, params)
    dropna_columns = [c for c in bos_filtered_module.INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    trades, _state = bos_filtered_module.run_backtest(evaluable, params)
    return _stats_from_trades(trades, evaluable, params)


def run_report() -> dict[str, object]:
    client = MarketDataClient()
    try:
        candles, method = fetch_timeframe_candles(client, ASSET, TIMEFRAME)
    except MarketDataUnavailableError as exc:
        return {"error": str(exc)}

    v1_spec = VARIANT_SPECS["trend_pullback"]
    v1_spec = replace(v1_spec, params=build_calibrated_params(v1_spec.params, TIMEFRAME, ASSET))
    fvg_params = build_calibrated_params(fvg_filtered_module.DEFAULT_PARAMETERS, TIMEFRAME, ASSET)
    bos_params = build_calibrated_params(bos_filtered_module.DEFAULT_PARAMETERS, TIMEFRAME, ASSET)

    train, test = split_chronological(candles)
    return {
        "method": method,
        "candle_count": len(candles),
        "v1": {"train": _v1_half_stats(train, v1_spec), "test": _v1_half_stats(test, v1_spec)},
        "fvg_filtered": {
            "train": _fvg_filtered_half_stats(train, fvg_params),
            "test": _fvg_filtered_half_stats(test, fvg_params),
        },
        "bos_filtered": {
            "train": _bos_filtered_half_stats(train, bos_params),
            "test": _bos_filtered_half_stats(test, bos_params),
        },
    }


def _format_half(variant_label: str, split_name: str, stats: dict[str, object]) -> list[str]:
    lines: list[str] = []
    flag = " *** LOW SAMPLE ***" if stats["below_min_sample"] else ""
    lines.append(
        f"  [{variant_label}] {split_name}: N={stats['trades']} ExpR={stats['expectancy_r']:.3f} "
        f"AvgWinR={stats['avg_win_r']:.3f} AvgLossR={stats['avg_loss_r']:.3f} Win%={stats['win_pct'] * 100:.1f}% "
        f"PF={stats['profit_factor']:.2f} MaxDD={stats['max_drawdown'] * 100:.1f}%{flag}"
    )
    ci = stats["ci"]
    if ci is None:
        lines.append("      Bootstrap 95% CI: n/a (zero trades)")
    else:
        verdict = "CROSSES ZERO" if ci.crosses_zero else "clears zero"
        lines.append(f"      Bootstrap 95% CI on mean R: [{ci.lower_2_5:.3f}, {ci.upper_97_5:.3f}] ({verdict})")
    baseline = stats["baseline"]
    if baseline is not None:
        lines.append(f"      Edge over random-entry baseline: {baseline.edge_over_random:+.3f}")
    return lines


def format_report(result: dict[str, object]) -> str:
    if "error" in result:
        return f"{ASSET} / {TIMEFRAME}: SKIPPED — {result['error']}"

    lines = [f"{ASSET} / {TIMEFRAME} — {result['method']} ({result['candle_count']} candles)", ""]
    for label, key in (("v1 (unfiltered)", "v1"), ("fvg-filtered", "fvg_filtered"), ("bos-filtered", "bos_filtered")):
        for split_name in ("train", "test"):
            lines.extend(_format_half(label, split_name.upper(), result[key][split_name]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    result = run_report()
    print(format_report(result))


if __name__ == "__main__":
    main()
