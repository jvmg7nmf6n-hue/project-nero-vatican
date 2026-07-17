"""CLI: re-verify the 3 live-scheduler survivors (see nero_core/execution/
live_scheduler.py, docs/research_phase_closure.md) through the upgraded statistical
harness (tools.backtest_statistics) — bootstrap 95% CI on mean per-trade R, and a
random-entry baseline, for BOTH the chronological train (70%) and test (30%) halves.

SURVIVORS (same resolved versions the live scheduler actually runs — see
nero_core/execution/DESIGN.md for why GOLD uses v1.2.0-gold-calibrated-1week, not the
uncorrected v1.1.0):
  1. GOLD / 1week / BREAKOUT_MOMENTUM breakout-momentum-v1.2.0-gold-calibrated-1week
  2. BNB / 12h / TREND_PULLBACK trend-pullback-v1.0.0
  3. BTC-ETH / 12h / COINTEGRATION_PAIRS cointegration-pairs-v1.0.0

Reports factually, including if a survivor looks weaker under this stricter lens — this
tool does not decide pass/fail, it reports the numbers (CI crossing zero, edge over
random) for a human to weigh alongside everything else already known about each
config (H6 robustness audit, grid-shift follow-up).

No synthetic/fabricated price data is ever used — if a fetch fails, that survivor is
reported as SKIPPED with the reason.

Usage:
    python tools/backtest_survivor_verification.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.breakout_momentum import size_entry as bm_size_entry
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import PAIR as PAIRS_ASSETS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles
from nero_core.strategies.cointegration_pairs import run_pairs_backtest
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from nero_core.strategies.trend_pullback import size_entry as tp_size_entry
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS, run_backtest
from tools.backtest_statistics import (
    bootstrap_mean_r_ci,
    breakout_momentum_regime_mask,
    random_entry_baseline_pairs,
    random_entry_baseline_single_asset,
    trend_pullback_regime_mask,
)
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

SINGLE_ASSET_SURVIVORS = [
    {
        "label": "GOLD / 1week / BREAKOUT_MOMENTUM gold-calibrated-1week",
        "asset": "GOLD",
        "timeframe": "1week",
        "variant_key": "breakout_momentum_gold_calibrated_1week",
        "size_entry_fn": bm_size_entry,
        "regime_mask_fn": breakout_momentum_regime_mask,
        # Already fully calibrated (GOLD fees + 1week holding cap baked into its
        # registered params) — re-running build_calibrated_params here would double-apply
        # the GOLD fee scale factor. Do NOT recalibrate (same rule as
        # backtest_regime_scaled_risk_report.py's COMPARISONS entry for this config).
        "needs_timeframe_calibration": False,
    },
    {
        "label": "BNB / 12h / TREND_PULLBACK",
        "asset": "BNB",
        "timeframe": "12h",
        "variant_key": "trend_pullback",
        "size_entry_fn": tp_size_entry,
        "regime_mask_fn": trend_pullback_regime_mask,
        # trend_pullback's registered params are a 1h-reference default
        # (max_holding_hours=24) — MUST be recalibrated for 12h candles before use, same
        # bug class as the GOLD 1week fix. Skipping this forces nearly every trade closed
        # via TIME after just 2 candles, corrupting the comparison (caught by re-deriving
        # this report and finding BNB/TREND_PULLBACK falsely negative before this flag
        # was added — see docs/statistical_harness_upgrade.md).
        "needs_timeframe_calibration": True,
    },
]

PAIRS_LABEL = "BTC-ETH / 12h / COINTEGRATION_PAIRS"
PAIRS_TIMEFRAME = "12h"


def _half_metrics(trades: list, ci, baseline) -> dict[str, object]:
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    return {
        "trades": len(trades),
        "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE,
        "ci": ci,
        "baseline": baseline,
    }


def _single_asset_half_stats(half_candles, spec, regime_mask_fn, size_entry_fn) -> dict[str, object]:
    trades, _state = run_backtest(half_candles, spec)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = spec.add_indicators_fn(half_candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    eligible_mask = regime_mask_fn(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, spec.params, size_entry_fn, expectancy_r, len(trades)
    )
    return _half_metrics(trades, ci, baseline)


def _pairs_half_stats(aligned_half) -> dict[str, object]:
    x_name, y_name = PAIRS_ASSETS
    enriched = pairs_add_indicators(aligned_half, PAIRS_PARAMETERS, x_name, y_name)
    evaluable = enriched.dropna(subset=["zscore"]).reset_index(drop=True)
    trades, _state = run_pairs_backtest(evaluable, PAIRS_PARAMETERS, x_name, y_name)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_pairs(
        evaluable, PAIRS_PARAMETERS, x_name, y_name, expectancy_r, len(trades)
    )
    return _half_metrics(trades, ci, baseline)


def run_single_asset_survivor(config: dict[str, object], client: MarketDataClient) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, config["asset"], config["timeframe"])
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": str(exc)}

    spec = VARIANT_SPECS[config["variant_key"]]
    if config["needs_timeframe_calibration"]:
        spec = replace(spec, params=build_calibrated_params(spec.params, config["timeframe"], config["asset"]))
    train, test = split_chronological(candles)
    return {
        "label": config["label"],
        "method": method,
        "candle_count": len(candles),
        "train": _single_asset_half_stats(train, spec, config["regime_mask_fn"], config["size_entry_fn"]),
        "test": _single_asset_half_stats(test, spec, config["regime_mask_fn"], config["size_entry_fn"]),
    }


def run_pairs_survivor(client: MarketDataClient) -> dict[str, object]:
    x_name, y_name = PAIRS_ASSETS
    try:
        x_candles, x_method = fetch_timeframe_candles(client, x_name, PAIRS_TIMEFRAME)
        y_candles, y_method = fetch_timeframe_candles(client, y_name, PAIRS_TIMEFRAME)
    except MarketDataUnavailableError as exc:
        return {"label": PAIRS_LABEL, "error": str(exc)}

    aligned = align_pair_candles(x_candles, y_candles, x_name, y_name)
    train, test = split_chronological(aligned)
    return {
        "label": PAIRS_LABEL,
        "method": f"{x_method} + {y_method}",
        "candle_count": len(aligned),
        "train": _pairs_half_stats(train),
        "test": _pairs_half_stats(test),
    }


def run_report() -> list[dict[str, object]]:
    client = MarketDataClient()
    results = [run_single_asset_survivor(config, client) for config in SINGLE_ASSET_SURVIVORS]
    results.append(run_pairs_survivor(client))
    return results


def _format_half(split_name: str, stats: dict[str, object]) -> list[str]:
    lines: list[str] = []
    flag = " *** LOW SAMPLE ***" if stats["below_min_sample"] else ""
    lines.append(f"  {split_name}: N={stats['trades']} ExpR={stats['expectancy_r']:.3f}{flag}")

    ci = stats["ci"]
    if ci is None:
        lines.append("    Bootstrap 95% CI: n/a (zero trades)")
    else:
        verdict = "CROSSES ZERO -> edge not statistically proven" if ci.crosses_zero else "clears zero"
        lines.append(f"    Bootstrap 95% CI on mean R: [{ci.lower_2_5:.3f}, {ci.upper_97_5:.3f}] ({verdict})")

    baseline = stats["baseline"]
    if baseline is None:
        lines.append("    Random-entry baseline: n/a (empty eligible pool or zero trades)")
    else:
        lines.append(
            f"    Random-entry baseline ({baseline.n_runs} runs, target N={baseline.target_trade_count}, "
            f"realized mean N={baseline.realized_mean_trade_count:.1f}): "
            f"mean ExpR={baseline.mean_random_expectancy_r:.3f}, p95 ExpR={baseline.p95_random_expectancy_r:.3f}, "
            f"edge over random={baseline.edge_over_random:+.3f}"
        )
        if baseline.caveat:
            lines.append(f"    CAVEAT: {baseline.caveat}")
    return lines


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['label']}: SKIPPED — {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['label']} — {row['method']} ({row['candle_count']} candles)")
        lines.extend(_format_half("TRAIN", row["train"]))
        lines.extend(_format_half("TEST", row["test"]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_report()
    print(format_report(results))


if __name__ == "__main__":
    main()
