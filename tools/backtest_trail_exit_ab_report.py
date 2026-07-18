"""CLI: A/B compare v1 (fixed target + max-holding cap) vs v2 (ARMED EMA trail, no cap)
profit-exit variants for the two single-asset survivors, on IDENTICAL data, through the
upgraded statistical harness (tools.backtest_statistics — bootstrap 95% CI +
random-entry baseline). Only the profit-exit differs between each pair — entries and
disaster stops are byte-for-byte identical (see nero_core.strategies.ema_trail_exit and
either *_trail module's docstring for the full ARMED-TRAIL rule).

  BNB    / 12h    / TREND_PULLBACK              v1: trend-pullback-v1.0.0
                                                  v2: trend-pullback-v1.2.0-trail
  GOLD   / 1week  / BREAKOUT_MOMENTUM            v1: breakout-momentum-v1.2.0-gold-calibrated-1week
                                                  v2: breakout-momentum-v1.5.0-gold-calibrated-1week-trail

Reports, per variant per chronological train(70%)/test(30%) half: trade count, ExpR,
avg win R, avg loss R, win%, profit factor, max drawdown, bootstrap 95% CI, and the
random-entry baseline edge — factually, whichever variant looks better.

No synthetic/fabricated price data is ever used — if a fetch fails, that comparison is
reported as SKIPPED with the reason.

Usage:
    python tools/backtest_trail_exit_ab_report.py
"""
from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies import breakout_momentum_gold_calibrated_1week_trail as bm_trail_module
from nero_core.strategies import trend_pullback_trail as tp_trail_module
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.mean_reversion import evaluate_exit as shared_evaluate_exit
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS, run_backtest
from tools.backtest_statistics import (
    bootstrap_mean_r_ci,
    breakout_momentum_regime_mask,
    random_entry_baseline_single_asset,
    trend_pullback_regime_mask,
)
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

COMPARISONS = [
    {
        "label": "BNB / 12h / TREND_PULLBACK",
        "asset": "BNB",
        "timeframe": "12h",
        "v1_key": "trend_pullback",
        "needs_timeframe_calibration": True,
        "v2_module": tp_trail_module,
        "size_entry_fn": tp_size_entry,
        "regime_mask_fn": trend_pullback_regime_mask,
    },
    {
        "label": "GOLD / 1week / BREAKOUT_MOMENTUM gold-calibrated-1week",
        "asset": "GOLD",
        "timeframe": "1week",
        "v1_key": "breakout_momentum_gold_calibrated_1week",
        "needs_timeframe_calibration": False,
        "v2_module": bm_trail_module,
        "size_entry_fn": bm_size_entry,
        "regime_mask_fn": breakout_momentum_regime_mask,
    },
]


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = -math.inf
    drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, (value - peak) / peak)
    return drawdown


def _trade_stats(trades: list, size_entry_fn, evaluate_exit_fn, evaluable, regime_mask_fn, params) -> dict[str, object]:
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

    eligible_mask = regime_mask_fn(evaluable)  # a plain column comparison; works fine on an empty frame too
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, size_entry_fn, expectancy_r, n, evaluate_exit_fn=evaluate_exit_fn
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


def _v1_half_stats(half_candles, spec, size_entry_fn, regime_mask_fn) -> dict[str, object]:
    trades, _state = run_backtest(half_candles, spec)
    enriched = spec.add_indicators_fn(half_candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    return _trade_stats(trades, size_entry_fn, shared_evaluate_exit, evaluable, regime_mask_fn, spec.params)


def _v2_half_stats(half_candles, v2_module, size_entry_fn, regime_mask_fn) -> dict[str, object]:
    params = v2_module.DEFAULT_PARAMETERS
    enriched = v2_module.add_indicators(half_candles, params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns] + ["trail_ema"]
    dropna_columns = [c for c in dict.fromkeys(dropna_columns) if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    trades, _state = v2_module.run_backtest(evaluable, params)
    return _trade_stats(trades, size_entry_fn, v2_module.evaluate_exit, evaluable, regime_mask_fn, params)


def run_comparison(config: dict[str, object], client: MarketDataClient) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, config["asset"], config["timeframe"])
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": str(exc)}

    v1_spec = VARIANT_SPECS[config["v1_key"]]
    if config["needs_timeframe_calibration"]:
        v1_spec = replace(v1_spec, params=build_calibrated_params(v1_spec.params, config["timeframe"], config["asset"]))

    train, test = split_chronological(candles)
    return {
        "label": config["label"],
        "method": method,
        "candle_count": len(candles),
        "v1": {
            "train": _v1_half_stats(train, v1_spec, config["size_entry_fn"], config["regime_mask_fn"]),
            "test": _v1_half_stats(test, v1_spec, config["size_entry_fn"], config["regime_mask_fn"]),
        },
        "v2": {
            "train": _v2_half_stats(train, config["v2_module"], config["v2_module"].size_entry, config["regime_mask_fn"]),
            "test": _v2_half_stats(test, config["v2_module"], config["v2_module"].size_entry, config["regime_mask_fn"]),
        },
    }


def run_report() -> list[dict[str, object]]:
    client = MarketDataClient()
    return [run_comparison(config, client) for config in COMPARISONS]


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


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['label']}: SKIPPED — {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['label']} — {row['method']} ({row['candle_count']} candles)")
        for split_name in ("train", "test"):
            lines.extend(_format_half("v1", split_name.upper(), row["v1"][split_name]))
            lines.extend(_format_half("v2-trail", split_name.upper(), row["v2"][split_name]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_report()
    print(format_report(results))


if __name__ == "__main__":
    main()
