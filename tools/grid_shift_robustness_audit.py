"""CLI: H6 follow-up — grid-shift robustness audit.

H6 found that several previously-qualifying configs' closed trades cluster heavily on
specific days/hours (e.g. one config had 100% of its trades close at hour 11 UTC). This
tool asks the direct follow-up question: does each config's positive expectancy survive
moving the candle grid's boundaries in wall-clock time, or does it vanish/flip — i.e. is
the edge a market effect or a candle-alignment artifact?

For the 6 previously-qualifying single/pair configs plus H5's positive LEADLAG_FOLLOW
pairs (excluding the one 24h pair — only 12h and 2h offsets were specified, so a 24h
shift is out of scope and reported as such, not invented), this rebuilds the SAME
timeframe from native 1h candles at multiple UTC-clock offsets (0h/+3h/+6h for 12h grids,
0h/+1h for 2h grids) via nero_core.data_sources.candle_resampling.resample_hourly_to_grid,
then reruns the exact same registered strategy/parameters/70-30 split on each shifted
grid. The native exchange-provided grid is fetched independently too, as a
reference/sanity check against the offset+0h resampled control (both should be very
close if the resampling pipeline itself is correct).

No synthetic/fabricated price data is ever used — if a fetch fails, that configuration
(or that specific grid within a configuration) is reported as SKIPPED with the reason,
not silently substituted.

Usage:
    python tools/grid_shift_robustness_audit.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles, run_pairs_backtest
from nero_core.strategies.leadlag_follow import DEFAULT_PARAMETERS as LEADLAG_DEFAULT_PARAMETERS
from nero_core.strategies.leadlag_follow import align_leadlag_candles, run_leadlag_backtest
from nero_core.strategies.timeframe_calibration import HOURS_PER_TIMEFRAME, build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, compute_metrics, run_backtest
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

OFFSETS_BY_TIMEFRAME = {"12h": [0, 3, 6], "2h": [0, 1]}
HOURLY_FETCH_CANDLES = 100_000  # far past any of these assets' Binance listing history

SINGLE_ASSET_CONFIGS = [
    {"label": "BTC / 12h / MEAN_REVERSION relaxed-pullback", "asset": "BTC", "timeframe": "12h", "variant_key": "mean_reversion_relaxed_pullback"},
    {"label": "BNB / 12h / TREND_PULLBACK", "asset": "BNB", "timeframe": "12h", "variant_key": "trend_pullback"},
    {"label": "BNB / 12h / MEAN_REVERSION relaxed-pullback", "asset": "BNB", "timeframe": "12h", "variant_key": "mean_reversion_relaxed_pullback"},
    {"label": "XRP / 2h / MEAN_REVERSION deep-value", "asset": "XRP", "timeframe": "2h", "variant_key": "mean_reversion_deep_value"},
    {"label": "NEAR / 2h / MEAN_REVERSION deep-value", "asset": "NEAR", "timeframe": "2h", "variant_key": "mean_reversion_deep_value"},
]

PAIRS_CONFIG = {"label": "BTC-ETH / 12h / COINTEGRATION_PAIRS", "timeframe": "12h", "x": "BTC", "y": "ETH"}

# The 5 of H5's 7 Bonferroni-significant pairs that also passed the "positive in both
# train and test, >= 20 trades each half" filter in the H5 sweep.
LEADLAG_CONFIGS = [
    {"label": "BTC-SOL / 12h lag5 / LEADLAG_FOLLOW", "alt": "SOL", "timeframe": "12h", "lag": 5},
    {"label": "BTC-XRP / 12h lag3 / LEADLAG_FOLLOW", "alt": "XRP", "timeframe": "12h", "lag": 3},
    {"label": "BTC-DOGE / 12h lag3 / LEADLAG_FOLLOW", "alt": "DOGE", "timeframe": "12h", "lag": 3},
    {"label": "BTC-NEAR / 12h lag5 / LEADLAG_FOLLOW", "alt": "NEAR", "timeframe": "12h", "lag": 5},
]

# The 6th H5-positive pair (BTC-BNB / 24h lag1) is deliberately NOT retested here: the
# task specified 12h and 2h offsets only, no 24h offset — inventing one would not be a
# faithful re-test of the specified hypothesis.
LEADLAG_OUT_OF_SCOPE = {
    "label": "BTC-BNB / 24h lag1 / LEADLAG_FOLLOW",
    "reason": "only 12h (+3h/+6h) and 2h (+1h) offsets were specified for this grid-shift test; no 24h offset was given, so this pair is out of scope rather than assigned an arbitrary shift.",
}


def _fetch_hourly(client: MarketDataClient, asset: str, cache: dict) -> tuple[pd.DataFrame, str]:
    if asset not in cache:
        result = client.load_intraday(asset, interval="1h", candles=HOURLY_FETCH_CANDLES)
        cache[asset] = (result.prices, result.source)
    return cache[asset]


def _metrics_row(trades: list, state, label: str) -> dict[str, object]:
    m = compute_metrics(label, label, state, trades)
    return {
        "trades": m.sample_size,
        "win_rate": m.win_rate,
        "expectancy_r": m.expectancy_r,
        "profit_factor": m.profit_factor,
        "below_min_sample": m.insufficient_sample,
    }


def _empty_row(reason: str) -> dict[str, object]:
    return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "below_min_sample": True, "skip_reason": reason}


def _build_grid_defs(timeframe: str) -> list[tuple[str, int]]:
    """Returns [(grid_label, offset_hours), ...] for the offsets to test at this timeframe."""
    return [(f"offset+{o}h (control)" if o == 0 else f"offset+{o}h", o) for o in OFFSETS_BY_TIMEFRAME[timeframe]]


def run_single_asset_config(config: dict, client: MarketDataClient, hourly_cache: dict) -> dict[str, object]:
    asset, timeframe, variant_key = config["asset"], config["timeframe"], config["variant_key"]
    base_spec = VARIANT_SPECS[variant_key]
    spec = replace(base_spec, params=build_calibrated_params(base_spec.params, timeframe, asset))
    target_hours = HOURS_PER_TIMEFRAME[timeframe]

    grids: list[dict[str, object]] = []

    try:
        native_candles, native_method = fetch_timeframe_candles(client, asset, timeframe)
        grids.append({"grid": "native (exchange-provided)", "method": native_method, "candles": native_candles})
    except MarketDataUnavailableError as exc:
        grids.append({"grid": "native (exchange-provided)", "error": str(exc)})

    try:
        hourly_df, hourly_source = _fetch_hourly(client, asset, hourly_cache)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": f"1h fetch failed: {exc}"}

    for grid_label, offset in _build_grid_defs(timeframe):
        grid_candles = resample_hourly_to_grid(hourly_df, target_hours, offset)
        grids.append({"grid": grid_label, "method": f"RESAMPLED from {hourly_source} (1h)", "candles": grid_candles})

    grid_results = []
    for g in grids:
        if "error" in g:
            grid_results.append({"grid": g["grid"], "error": g["error"]})
            continue
        candles = g["candles"]
        if candles.empty:
            grid_results.append({"grid": g["grid"], "error": "no complete bins produced by resampling"})
            continue
        train, test = split_chronological(candles)
        full_trades, full_state = run_backtest(candles, spec)
        train_trades, train_state = run_backtest(train, spec)
        test_trades, test_state = run_backtest(test, spec)
        grid_results.append(
            {
                "grid": g["grid"],
                "method": g["method"],
                "candle_count": len(candles),
                "full": _metrics_row(full_trades, full_state, spec.label),
                "train": _metrics_row(train_trades, train_state, spec.label),
                "test": _metrics_row(test_trades, test_state, spec.label),
            }
        )

    return {"label": config["label"], "strategy": spec.label, "grids": grid_results}


def run_pairs_config(config: dict, client: MarketDataClient, hourly_cache: dict) -> dict[str, object]:
    timeframe, x_name, y_name = config["timeframe"], config["x"], config["y"]
    target_hours = HOURS_PER_TIMEFRAME[timeframe]

    grid_pairs: list[dict[str, object]] = []

    try:
        native_x, native_x_method = fetch_timeframe_candles(client, x_name, timeframe)
        native_y, native_y_method = fetch_timeframe_candles(client, y_name, timeframe)
        grid_pairs.append({"grid": "native (exchange-provided)", "method": f"{native_x_method} + {native_y_method}", "x": native_x, "y": native_y})
    except MarketDataUnavailableError as exc:
        grid_pairs.append({"grid": "native (exchange-provided)", "error": str(exc)})

    try:
        hourly_x, src_x = _fetch_hourly(client, x_name, hourly_cache)
        hourly_y, src_y = _fetch_hourly(client, y_name, hourly_cache)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": f"1h fetch failed: {exc}"}

    for grid_label, offset in _build_grid_defs(timeframe):
        grid_x = resample_hourly_to_grid(hourly_x, target_hours, offset)
        grid_y = resample_hourly_to_grid(hourly_y, target_hours, offset)
        grid_pairs.append({"grid": grid_label, "method": f"RESAMPLED {x_name} from {src_x} + {y_name} from {src_y} (1h)", "x": grid_x, "y": grid_y})

    grid_results = []
    for g in grid_pairs:
        if "error" in g:
            grid_results.append({"grid": g["grid"], "error": g["error"]})
            continue
        if g["x"].empty or g["y"].empty:
            grid_results.append({"grid": g["grid"], "error": "no complete bins produced by resampling for one or both legs"})
            continue
        aligned = align_pair_candles(g["x"], g["y"], x_name, y_name)
        if aligned.empty:
            grid_results.append({"grid": g["grid"], "error": "no overlapping candles between legs after alignment"})
            continue
        train_raw, test_raw = split_chronological(aligned)
        full_enriched = pairs_add_indicators(aligned, PAIRS_PARAMETERS, x_name, y_name)
        train_enriched = pairs_add_indicators(train_raw, PAIRS_PARAMETERS, x_name, y_name)
        test_enriched = pairs_add_indicators(test_raw, PAIRS_PARAMETERS, x_name, y_name)

        full_trades, full_state = run_pairs_backtest(full_enriched, PAIRS_PARAMETERS, x_name, y_name)
        train_trades, train_state = run_pairs_backtest(train_enriched, PAIRS_PARAMETERS, x_name, y_name)
        test_trades, test_state = run_pairs_backtest(test_enriched, PAIRS_PARAMETERS, x_name, y_name)

        label = "COINTEGRATION_PAIRS (cointegration-pairs-v1.0.0)"
        grid_results.append(
            {
                "grid": g["grid"],
                "method": g["method"],
                "candle_count": len(aligned),
                "full": _metrics_row(full_trades, full_state, label),
                "train": _metrics_row(train_trades, train_state, label),
                "test": _metrics_row(test_trades, test_state, label),
            }
        )

    return {"label": config["label"], "strategy": "COINTEGRATION_PAIRS (cointegration-pairs-v1.0.0)", "grids": grid_results}


def run_leadlag_config(config: dict, client: MarketDataClient, hourly_cache: dict) -> dict[str, object]:
    alt, timeframe, lag = config["alt"], config["timeframe"], config["lag"]
    target_hours = HOURS_PER_TIMEFRAME[timeframe]
    params = build_calibrated_params(replace(LEADLAG_DEFAULT_PARAMETERS, lag=lag), timeframe, alt)
    label = "LEADLAG_FOLLOW (leadlag-follow-v1.0.0)"

    grid_pairs: list[dict[str, object]] = []

    try:
        native_btc, native_btc_method = fetch_timeframe_candles(client, "BTC", timeframe)
        native_alt, native_alt_method = fetch_timeframe_candles(client, alt, timeframe)
        grid_pairs.append({"grid": "native (exchange-provided)", "method": f"{native_btc_method} + {native_alt_method}", "btc": native_btc, "alt": native_alt})
    except MarketDataUnavailableError as exc:
        grid_pairs.append({"grid": "native (exchange-provided)", "error": str(exc)})

    try:
        hourly_btc, src_btc = _fetch_hourly(client, "BTC", hourly_cache)
        hourly_alt, src_alt = _fetch_hourly(client, alt, hourly_cache)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": f"1h fetch failed: {exc}"}

    for grid_label, offset in _build_grid_defs(timeframe):
        grid_btc = resample_hourly_to_grid(hourly_btc, target_hours, offset)
        grid_alt = resample_hourly_to_grid(hourly_alt, target_hours, offset)
        grid_pairs.append({"grid": grid_label, "method": f"RESAMPLED BTC from {src_btc} + {alt} from {src_alt} (1h)", "btc": grid_btc, "alt": grid_alt})

    grid_results = []
    for g in grid_pairs:
        if "error" in g:
            grid_results.append({"grid": g["grid"], "error": g["error"]})
            continue
        if g["btc"].empty or g["alt"].empty:
            grid_results.append({"grid": g["grid"], "error": "no complete bins produced by resampling for one or both legs"})
            continue
        aligned = align_leadlag_candles(g["btc"], g["alt"], "BTC", alt)
        if aligned.empty:
            grid_results.append({"grid": g["grid"], "error": "no overlapping candles between BTC and alt after alignment"})
            continue
        train_raw, test_raw = split_chronological(aligned)

        full_trades, full_state = run_leadlag_backtest(aligned, params, "BTC", alt)
        train_trades, train_state = run_leadlag_backtest(train_raw, params, "BTC", alt)
        test_trades, test_state = run_leadlag_backtest(test_raw, params, "BTC", alt)

        grid_results.append(
            {
                "grid": g["grid"],
                "method": g["method"],
                "candle_count": len(aligned),
                "full": _metrics_row(full_trades, full_state, label),
                "train": _metrics_row(train_trades, train_state, label),
                "test": _metrics_row(test_trades, test_state, label),
            }
        )

    return {"label": config["label"], "strategy": label, "grids": grid_results}


def run_all() -> dict[str, object]:
    client = MarketDataClient()
    hourly_cache: dict[str, tuple[pd.DataFrame, str]] = {}

    single_results = []
    for c in SINGLE_ASSET_CONFIGS:
        start = time.monotonic()
        r = run_single_asset_config(c, client, hourly_cache)
        single_results.append(r)
        print(f"{c['label']}: done in {time.monotonic() - start:.1f}s")

    pairs_result = run_pairs_config(PAIRS_CONFIG, client, hourly_cache)
    print(f"{PAIRS_CONFIG['label']}: done")

    leadlag_results = []
    for c in LEADLAG_CONFIGS:
        start = time.monotonic()
        r = run_leadlag_config(c, client, hourly_cache)
        leadlag_results.append(r)
        print(f"{c['label']}: done in {time.monotonic() - start:.1f}s")

    return {
        "single_asset": single_results,
        "pairs": [pairs_result],
        "leadlag": leadlag_results,
        "out_of_scope": [LEADLAG_OUT_OF_SCOPE],
    }


def _fmt_cell(cell: dict[str, object]) -> str:
    if "skip_reason" in cell:
        return "SKIP"
    pf = cell["profit_factor"]
    pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
    flag = "*" if cell["below_min_sample"] else " "
    return f"N={cell['trades']:>4} Win={cell['win_rate'] * 100:>5.1f}% ExpR={cell['expectancy_r']:>7.3f} PF={pf_display:>6}{flag}"


def format_report(results: dict[str, object]) -> str:
    lines: list[str] = []
    for group_name, group in (("SINGLE-ASSET", results["single_asset"]), ("PAIRS", results["pairs"]), ("LEADLAG_FOLLOW", results["leadlag"])):
        lines.append(f"=== {group_name} ===")
        for r in group:
            lines.append(f"--- {r['label']} ---")
            if "error" in r:
                lines.append(f"  SKIPPED — {r['error']}")
                lines.append("")
                continue
            for g in r["grids"]:
                if "error" in g:
                    lines.append(f"  {g['grid']:<24} SKIPPED — {g['error']}")
                    continue
                lines.append(f"  {g['grid']:<24} ({g['candle_count']} candles, {g['method']})")
                lines.append(f"      FULL:  {_fmt_cell(g['full'])}")
                lines.append(f"      TRAIN: {_fmt_cell(g['train'])}")
                lines.append(f"      TEST:  {_fmt_cell(g['test'])}")
            lines.append("")

    lines.append("=== OUT OF SCOPE ===")
    for oos in results["out_of_scope"]:
        lines.append(f"  {oos['label']}: {oos['reason']}")
    lines.append("")
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def main() -> None:
    results = run_all()
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
