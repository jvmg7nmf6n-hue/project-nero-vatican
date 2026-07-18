"""CLI: backtest FUNDING_EXTREME (nero_core.strategies.funding_extreme) across BTC,
ETH, SOL, BNB on both 8h (settlement-grid-aligned, resampled from native 1h) and 24h
(native daily) timeframes, through the upgraded statistical harness
(tools.backtest_statistics: bootstrap 95% CI + random-entry baseline), with a
chronological 70/30 train/test split — the same standard rigor every other strategy in
this codebase is held to.

8h candles are built by resampling native 1h candles onto the 00:00/08:00/16:00 UTC
settlement grid via nero_core.data_sources.candle_resampling.resample_hourly_to_grid
(offset_hours=0, target_hours=8) — the same grid-shift resample utility already
volume-sum-verified for the H6 grid-shift robustness follow-up
(tests/test_candle_resampling.py), not a new/independent resampling path.

No synthetic/fabricated price or funding data is ever used — if a fetch fails, that
(asset, timeframe) is reported as SKIPPED with the reason.

Usage:
    python tools/backtest_funding_extreme_sweep.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.funding_data import FUNDING_ASSETS, FundingDataUnavailableError, history_depth_report, load_funding_history
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.funding_extreme import (
    DEFAULT_PARAMETERS,
    FundingExtremeParameters,
    add_indicators,
    evaluate_exit,
    funding_data_available_mask,
    run_backtest,
    size_entry,
)
from tools.backtest_statistics import bootstrap_mean_r_ci, random_entry_baseline_single_asset
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
FUNDING_TIMEFRAMES = ["8h", "24h"]
HOURLY_CANDLES_FOR_8H_RESAMPLE = 50_000


def fetch_8h_candles(client: MarketDataClient, asset: str) -> tuple[object, str]:
    result = client.load_intraday(asset, interval="1h", candles=HOURLY_CANDLES_FOR_8H_RESAMPLE)
    resampled = resample_hourly_to_grid(result.prices, target_hours=8, offset_hours=0)
    return resampled, f"RESAMPLED: 8h settlement-grid candles from native 1h ({result.source})"


def _fetch_candles(client: MarketDataClient, asset: str, timeframe: str) -> tuple[object, str]:
    if timeframe == "8h":
        return fetch_8h_candles(client, asset)
    return fetch_timeframe_candles(client, asset, timeframe)


def _half_stats(half_candles, funding_settlements, timeframe: str, params: FundingExtremeParameters) -> dict[str, object]:
    enriched = add_indicators(half_candles, funding_settlements, timeframe, params)
    dropna_columns = [c for c in ("atr", "entry_funding_rate", "entry_funding_p10") if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)

    trades, _state = run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    eligible_mask = funding_data_available_mask(evaluable)
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, size_entry, expectancy_r, len(trades), evaluate_exit_fn=evaluate_exit
    )
    return {
        "trades": len(trades),
        "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE,
        "ci": ci,
        "baseline": baseline,
    }


def run_asset_timeframe(
    asset: str, timeframe: str, client: MarketDataClient, params: FundingExtremeParameters = DEFAULT_PARAMETERS
) -> dict[str, object]:
    try:
        candles, method = _fetch_candles(client, asset, timeframe)
    except MarketDataUnavailableError as exc:
        return {"asset": asset, "timeframe": timeframe, "error": f"price data unavailable: {exc}"}

    try:
        funding_result = load_funding_history(asset)
    except FundingDataUnavailableError as exc:
        return {"asset": asset, "timeframe": timeframe, "error": f"funding data unavailable: {exc}"}

    train, test = split_chronological(candles)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "method": method,
        "funding_depth": history_depth_report(asset, funding_result.settlements),
        "candle_count": len(candles),
        "train": _half_stats(train, funding_result.settlements, timeframe, params),
        "test": _half_stats(test, funding_result.settlements, timeframe, params),
    }


def run_report() -> list[dict[str, object]]:
    client = MarketDataClient()
    return [
        run_asset_timeframe(asset, timeframe, client)
        for asset in FUNDING_ASSETS
        for timeframe in FUNDING_TIMEFRAMES
    ]


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
    return lines


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for row in results:
        if "error" in row:
            lines.append(f"{row['asset']} / {row['timeframe']}: SKIPPED — {row['error']}")
            lines.append("")
            continue
        lines.append(f"{row['asset']} / {row['timeframe']} — {row['method']} ({row['candle_count']} candles)")
        lines.append(f"  Funding history: {row['funding_depth']}")
        lines.extend(_format_half("TRAIN", row["train"]))
        lines.extend(_format_half("TEST", row["test"]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_report()
    print(format_report(results))


if __name__ == "__main__":
    main()
