"""CLI: backtest BOS_CONTINUATION (nero_core.strategies.bos_continuation) across 7
crypto assets on 4h/12h/24h timeframes, through the upgraded statistical harness
(bootstrap 95% CI + random-entry baseline), with a chronological 70/30 train/test
split, classified into SURVIVED / PROMISING-WATCHLIST / DIED
(tools.backtest_statistics.classify_verdict).

Also reports, per (asset, timeframe, half), how many closed trades used the
STRUCTURAL stop (the swing low/high preceding the broken pivot) vs the CAPPED stop
(3.0x ATR, when the structural distance would have been farther) — the task's own
"document which was used per trade in aggregate counts" requirement.

RANDOM-BASELINE ELIGIBLE POOL NOTE: same adaptation as
tools/backtest_fvg_reversion_sweep.py — BOS_CONTINUATION's size_entry needs the
specific broken pivot's preceding-extreme data (only non-NaN on an actual BOS candle),
so the random-entry pool is narrowed to "has an actual BOS signal, on the side the
trend filter allows," not an unconstrained "any candle in the regime" pool.

No synthetic/fabricated price data is ever used — if a fetch fails, that
(asset, timeframe) is reported as SKIPPED with the reason.

Usage:
    python tools/backtest_bos_continuation_sweep.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.bos_continuation import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    BosContinuationParameters,
    add_indicators,
    evaluate_exit,
    run_backtest,
    size_entry,
)
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_statistics import (
    above_ma200_mask,
    below_ma200_mask,
    bootstrap_mean_r_ci,
    classify_verdict,
    random_entry_baseline_bidirectional,
)
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR"]
TIMEFRAMES = ["4h", "12h", "24h"]


def _half_stats(half_candles, params: BosContinuationParameters) -> dict[str, object]:
    enriched = add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)

    trades, _state = run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0
    structural_count = sum(1 for t in trades if t.stop_type == "structural")
    capped_count = sum(1 for t in trades if t.stop_type == "capped")

    long_mask = above_ma200_mask(evaluable) & evaluable["bos_up_signal_pivot_value"].notna()
    short_mask = below_ma200_mask(evaluable) & evaluable["bos_down_signal_pivot_value"].notna()
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_bidirectional(
        evaluable, long_mask, short_mask, params, size_entry, evaluate_exit, expectancy_r, len(trades)
    )
    return {
        "trades": len(trades),
        "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE,
        "ci": ci,
        "baseline": baseline,
        "structural_stop_count": structural_count,
        "capped_stop_count": capped_count,
    }


def run_asset_timeframe(asset: str, timeframe: str, client: MarketDataClient) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, asset, timeframe)
    except MarketDataUnavailableError as exc:
        return {"asset": asset, "timeframe": timeframe, "error": str(exc)}

    params = build_calibrated_params(DEFAULT_PARAMETERS, timeframe, asset)
    train, test = split_chronological(candles)
    train_stats = _half_stats(train, params)
    test_stats = _half_stats(test, params)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "method": method,
        "candle_count": len(candles),
        "train": train_stats,
        "test": test_stats,
        "verdict": classify_verdict(train_stats, test_stats),
    }


def run_report() -> list[dict[str, object]]:
    client = MarketDataClient()
    return [run_asset_timeframe(asset, timeframe, client) for asset in ASSETS for timeframe in TIMEFRAMES]


def _format_half(split_name: str, stats: dict[str, object]) -> list[str]:
    lines: list[str] = []
    flag = " *** LOW SAMPLE ***" if stats["below_min_sample"] else ""
    lines.append(f"  {split_name}: N={stats['trades']} ExpR={stats['expectancy_r']:.3f}{flag}")
    lines.append(f"    Stop type: structural={stats['structural_stop_count']}, capped(3xATR)={stats['capped_stop_count']}")
    ci = stats["ci"]
    if ci is None:
        lines.append("    Bootstrap 95% CI: n/a (zero trades)")
    else:
        verdict = "CROSSES ZERO" if ci.crosses_zero else "clears zero"
        lines.append(f"    Bootstrap 95% CI on mean R: [{ci.lower_2_5:.3f}, {ci.upper_97_5:.3f}] ({verdict})")
    baseline = stats["baseline"]
    if baseline is not None:
        lines.append(f"    Edge over random-entry baseline: {baseline.edge_over_random:+.3f}")
    return lines


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['asset']} / {row['timeframe']}: SKIPPED — {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['asset']} / {row['timeframe']} — {row['method']} ({row['candle_count']} candles) — VERDICT: {row['verdict']}")
        lines.extend(_format_half("TRAIN", row["train"]))
        lines.extend(_format_half("TEST", row["test"]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_report()
    print(format_report(results))


if __name__ == "__main__":
    main()
