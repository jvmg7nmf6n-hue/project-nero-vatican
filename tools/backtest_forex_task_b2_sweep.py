"""CLI: Comprehensive Asset Expansion, Part B (Forex) — Task B2 full strategy sweep.

Universe: 10 standard pairs (see docs/forex_data_calibration_audit.md — all 10 cleared
Task B1's adequacy bar at all 4 standard forex timeframes, 0 unresolved, all native on
Twelve Data). Every strategy's existing entry/exit/sizing LOGIC runs UNCHANGED — only
fees are calibrated (flat 0.05% per side, per the task spec) and max_holding_hours is
re-derived per timeframe (same candle-COUNT-preservation fix used for every other
asset class in this project).

Roster (strategy: applicable timeframes, same mapping as Part A stocks per the task):
  1. MEAN_REVERSION v1        - 1h, 4h, 1day, 1week
  2. BREAKOUT_MOMENTUM        - 1h, 4h, 1day, 1week
  3. TREND_PULLBACK           - 1h, 4h, 1day, 1week
  4. DONCHIAN_TREND           - 1week
  5. VOLATILITY_SQUEEZE (x3 MA variants: ma200/ma150/ma100) - 1h, 4h, 1day, 1week
  6. FVG_REVERSION            - 1h, 4h, 1day
  7. BOS_CONTINUATION         - 4h, 1day, 1week
  8. COINTEGRATION_PAIRS      - USDJPY-USDCHF, EURGBP-EURJPY, AUDUSD-NZDUSD @ 1day, 1week
  9. MACRO_RISK_ON            - 1day, EUR/USD and USD/JPY only (the two most liquid,
     opposite-character USD pairs — the strategy's whole premise is a DOLLAR strength
     regime, so a small, liquid, genuinely USD-driven subset is a more honest test
     than multiplying the sweep across all 10 pairs, several of which don't even
     involve USD directly, e.g. EUR/GBP)

Every config: chronological 70/30 split, bootstrap 95% CI + random-entry baseline
(tools.backtest_statistics), classify_verdict (SURVIVED / PROMISING-WATCHLIST / DIED
per MIN_SAMPLE_SIZE=20), LOW SAMPLE flags. Grid-shift verification is mandatory for
1h/4h configs positive in both halves with an adequate sample — it must not shift a
candle-grid boundary across the real Friday-close -> Sunday/Monday-open gap (see
docs/forex_data_calibration_audit.md). 1day/1week configs are capped at
PROMISING-WATCHLIST if positive both halves, same precedent as metals/stocks.

All family-specific half-stats builders, regime-mask helpers, and the
_AttachedMaskSpec proxy are REUSED directly from tools.backtest_metals_phase_a_sweep —
none of that logic is asset-specific.

No synthetic/fabricated price data is ever used — if a fetch fails, that combination
is reported as SKIPPED with the reason, never a substituted result.

Usage:
    python -m tools.backtest_forex_task_b2_sweep
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.macro_data import (
    MacroDataUnavailableError,
    build_regime_frame,
    fetch_dfii10_daily,
    fetch_dollar_proxy_daily,
)
from nero_core.strategies.bos_continuation import DEFAULT_PARAMETERS as BOS_PARAMETERS
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import align_pair_candles
from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_DEFAULT_PARAMETERS
from nero_core.strategies.fvg_reversion import DEFAULT_PARAMETERS as FVG_PARAMETERS
from nero_core.strategies.macro_risk_on import DEFAULT_PARAMETERS as MACRO_PARAMETERS
from nero_core.strategies.timeframe_calibration import ORIGINAL_MAX_HOLDING_CANDLES
from tools.backtest_compare import VARIANT_SPECS
from tools.backtest_metals_phase_a_sweep import (
    _AttachedMaskSpec,
    _bos_half_stats,
    _donchian_half_stats,
    _fvg_half_stats,
    _macro_half_stats,
    _pairs_half_stats,
    _slice_macro_from,
    _slice_macro_until,
    _variant_half_stats,
    volatility_squeeze_regime_mask,
)
from tools.backtest_statistics import above_ma200_mask, classify_verdict
from tools.backtest_train_test_split import split_chronological

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "AUD/USD", "NZD/USD", "USD/CAD",
]

# Flat per Task B2's own spec — NOT a derived price/ATR scale factor.
FOREX_FEE_BPS = 5.0  # 0.05% per side
FOREX_SLIPPAGE_BPS = 2.0  # unchanged crypto-baseline default; not otherwise specified

FOREX_HOURS_PER_TIMEFRAME = {"1h": 1, "4h": 4, "1day": 24, "1week": 168}


def forex_calibrated_params(base_params, timeframe: str):
    """Flat 0.05%/side fee, unchanged slippage, and a re-derived max_holding_hours
    that preserves the original 24-CANDLE hold cap at this timeframe's own candle
    duration. Strategies with no max_holding_hours field (DONCHIAN_TREND,
    MACRO_RISK_ON) are left alone on that field — see tools.backtest_stocks_task_a2_
    sweep.stock_calibrated_params, the same pattern reused here for a second asset
    class."""
    kwargs = {"fee_bps": FOREX_FEE_BPS, "slippage_bps": FOREX_SLIPPAGE_BPS}
    if hasattr(base_params, "max_holding_hours"):
        kwargs["max_holding_hours"] = ORIGINAL_MAX_HOLDING_CANDLES * FOREX_HOURS_PER_TIMEFRAME[timeframe]
    return replace(base_params, **kwargs)


SINGLE_ASSET_ROSTER = [
    {"label": "MEAN_REVERSION v1", "variant_key": "mean_reversion_v1", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": above_ma200_mask},
    {"label": "BREAKOUT_MOMENTUM", "variant_key": "breakout_momentum", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": above_ma200_mask},
    {"label": "TREND_PULLBACK", "variant_key": "trend_pullback", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": lambda evaluable: (evaluable["close"] > evaluable["ma200"]) & (evaluable["ma50"] > evaluable["ma200"])},
    {"label": "VOLATILITY_SQUEEZE ma200", "variant_key": "volatility_squeeze_ma200", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma150", "variant_key": "volatility_squeeze_ma150", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma100", "variant_key": "volatility_squeeze_ma100", "timeframes": ["1h", "4h", "1day", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
]

FVG_TIMEFRAMES = ["1h", "4h", "1day"]
BOS_TIMEFRAMES = ["4h", "1day", "1week"]
DONCHIAN_TIMEFRAMES = ["1week"]

PAIRS_CONFIGS = [
    {"label": "USDJPY-USDCHF", "x": "USD/JPY", "y": "USD/CHF"},
    {"label": "EURGBP-EURJPY", "x": "EUR/GBP", "y": "EUR/JPY"},
    {"label": "AUDUSD-NZDUSD", "x": "AUD/USD", "y": "NZD/USD"},
]
PAIRS_TIMEFRAMES = ["1day", "1week"]

MACRO_ASSETS = ["EUR/USD", "USD/JPY"]  # see module docstring for why these two only


def _cached_fetch(cache: dict, pair: str, timeframe: str):
    key = (pair, timeframe)
    if key not in cache:
        result = fetch_forex_ohlcv(pair, timeframe)
        cache[key] = (result.prices, result.source)
    return cache[key]


def run_single_asset_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candle_cache: dict[tuple[str, str], tuple[pd.DataFrame, str]] = {}

    def cached_fetch(pair: str, timeframe: str):
        try:
            return _cached_fetch(candle_cache, pair, timeframe), None
        except ForexDataUnavailableError as exc:
            return None, str(exc)

    for entry in SINGLE_ASSET_ROSTER:
        for pair in FOREX_PAIRS:
            for timeframe in entry["timeframes"]:
                start = time.monotonic()
                fetched, error = cached_fetch(pair, timeframe)
                if error is not None:
                    print(f"{pair} / {timeframe} / {entry['label']}: SKIPPED — {error}")
                    rows.append({"asset": pair, "timeframe": timeframe, "strategy": entry["label"], "error": error})
                    continue
                candles, method = fetched

                base_spec = VARIANT_SPECS[entry["variant_key"]]
                calibrated_params = forex_calibrated_params(base_spec.params, timeframe)
                spec = replace(base_spec, params=calibrated_params, label=entry["label"])
                spec = _AttachedMaskSpec(spec, entry["regime_mask_fn"])

                train, test = split_chronological(candles)
                train_stats = _variant_half_stats(train, spec)
                test_stats = _variant_half_stats(test, spec)
                elapsed = time.monotonic() - start
                print(f"{pair} / {timeframe} / {entry['label']}: done ({elapsed:.1f}s, {len(candles)} candles)")
                rows.append({
                    "asset": pair, "timeframe": timeframe, "strategy": entry["label"], "method": method,
                    "candle_count": len(candles), "train": train_stats, "test": test_stats,
                    "verdict": classify_verdict(train_stats, test_stats),
                })

    for pair in FOREX_PAIRS:
        timeframe = DONCHIAN_TIMEFRAMES[0]
        start = time.monotonic()
        fetched, error = cached_fetch(pair, timeframe)
        if error is not None:
            print(f"{pair} / {timeframe} / DONCHIAN_TREND: SKIPPED — {error}")
            rows.append({"asset": pair, "timeframe": timeframe, "strategy": "DONCHIAN_TREND", "error": error})
            continue
        candles, method = fetched
        params = forex_calibrated_params(DONCHIAN_DEFAULT_PARAMETERS, timeframe)
        train, test = split_chronological(candles)
        train_stats = _donchian_half_stats(train, params)
        test_stats = _donchian_half_stats(test, params)
        elapsed = time.monotonic() - start
        print(f"{pair} / {timeframe} / DONCHIAN_TREND: done ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": pair, "timeframe": timeframe, "strategy": "DONCHIAN_TREND", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": classify_verdict(train_stats, test_stats),
        })

    for pair in FOREX_PAIRS:
        for timeframe in FVG_TIMEFRAMES:
            start = time.monotonic()
            fetched, error = cached_fetch(pair, timeframe)
            if error is not None:
                print(f"{pair} / {timeframe} / FVG_REVERSION: SKIPPED — {error}")
                rows.append({"asset": pair, "timeframe": timeframe, "strategy": "FVG_REVERSION", "error": error})
                continue
            candles, method = fetched
            params = forex_calibrated_params(FVG_PARAMETERS, timeframe)
            train, test = split_chronological(candles)
            train_stats = _fvg_half_stats(train, params)
            test_stats = _fvg_half_stats(test, params)
            elapsed = time.monotonic() - start
            print(f"{pair} / {timeframe} / FVG_REVERSION: done ({elapsed:.1f}s, {len(candles)} candles)")
            rows.append({
                "asset": pair, "timeframe": timeframe, "strategy": "FVG_REVERSION", "method": method,
                "candle_count": len(candles), "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })

    for pair in FOREX_PAIRS:
        for timeframe in BOS_TIMEFRAMES:
            start = time.monotonic()
            fetched, error = cached_fetch(pair, timeframe)
            if error is not None:
                print(f"{pair} / {timeframe} / BOS_CONTINUATION: SKIPPED — {error}")
                rows.append({"asset": pair, "timeframe": timeframe, "strategy": "BOS_CONTINUATION", "error": error})
                continue
            candles, method = fetched
            params = forex_calibrated_params(BOS_PARAMETERS, timeframe)
            train, test = split_chronological(candles)
            train_stats = _bos_half_stats(train, params)
            test_stats = _bos_half_stats(test, params)
            elapsed = time.monotonic() - start
            print(f"{pair} / {timeframe} / BOS_CONTINUATION: done ({elapsed:.1f}s, {len(candles)} candles)")
            rows.append({
                "asset": pair, "timeframe": timeframe, "strategy": "BOS_CONTINUATION", "method": method,
                "candle_count": len(candles), "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })

    return rows


def run_pairs_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pair_config in PAIRS_CONFIGS:
        for timeframe in PAIRS_TIMEFRAMES:
            label = pair_config["label"]
            start = time.monotonic()
            try:
                x_result = fetch_forex_ohlcv(pair_config["x"], timeframe)
                y_result = fetch_forex_ohlcv(pair_config["y"], timeframe)
            except ForexDataUnavailableError as exc:
                print(f"{label} / {timeframe} / COINTEGRATION_PAIRS: SKIPPED — {exc}")
                rows.append({"asset": label, "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS", "error": str(exc)})
                continue

            x_name = pair_config["x"].replace("/", "")
            y_name = pair_config["y"].replace("/", "")
            aligned = align_pair_candles(x_result.prices, y_result.prices, x_name, y_name)
            if aligned.empty:
                reason = "no aligned candles (same-vendor exact close_time join found zero overlap)"
                print(f"{label} / {timeframe} / COINTEGRATION_PAIRS: SKIPPED — {reason}")
                rows.append({"asset": label, "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS", "error": reason})
                continue

            train, test = split_chronological(aligned)
            train_stats = _pairs_half_stats(train, x_name, y_name)
            test_stats = _pairs_half_stats(test, x_name, y_name)
            elapsed = time.monotonic() - start
            print(f"{label} / {timeframe} / COINTEGRATION_PAIRS: done ({elapsed:.1f}s, {len(aligned)} aligned candles)")
            rows.append({
                "asset": label, "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS",
                "method": f"NATIVE: {x_result.source} + {y_result.source}",
                "candle_count": len(aligned), "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })
    return rows


def run_macro_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        dollar_series, dollar_source = fetch_dollar_proxy_daily()
        print(f"Dollar proxy: {dollar_source} ({len(dollar_series)} business days)")
        dfii10_series, dfii10_source = fetch_dfii10_daily()
        print(f"DFII10: {dfii10_source} ({len(dfii10_series)} business days)")
    except MacroDataUnavailableError as exc:
        print(f"MACRO_RISK_ON: BLOCKED — {exc}")
        for pair in MACRO_ASSETS:
            rows.append({"asset": pair, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": str(exc)})
        return rows

    for pair in MACRO_ASSETS:
        start = time.monotonic()
        try:
            result = fetch_forex_ohlcv(pair, "1day")
        except ForexDataUnavailableError as exc:
            print(f"{pair} / 1day / MACRO_RISK_ON: SKIPPED — {exc}")
            rows.append({"asset": pair, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": str(exc)})
            continue
        candles = result.prices

        train_candles, test_candles = split_chronological(candles)
        if train_candles.empty or test_candles.empty:
            reason = "not enough daily history to split 70/30"
            print(f"{pair} / 1day / MACRO_RISK_ON: SKIPPED — {reason}")
            rows.append({"asset": pair, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": reason})
            continue

        train_end = pd.to_datetime(train_candles["date"]).dt.tz_localize(None).max()
        test_start = pd.to_datetime(test_candles["date"]).dt.tz_localize(None).min()

        train_regime = build_regime_frame(train_candles, _slice_macro_until(dollar_series, train_end), _slice_macro_until(dfii10_series, train_end))
        test_regime = build_regime_frame(test_candles, _slice_macro_from(dollar_series, test_start), _slice_macro_from(dfii10_series, test_start))

        train_stats = _macro_half_stats(train_regime, MACRO_PARAMETERS)
        test_stats = _macro_half_stats(test_regime, MACRO_PARAMETERS)
        elapsed = time.monotonic() - start
        print(f"{pair} / 1day / MACRO_RISK_ON: done ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": pair, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "method": result.source,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": classify_verdict(train_stats, test_stats),
        })
    return rows


def run_full_sweep() -> list[dict[str, object]]:
    rows = run_single_asset_configs()
    rows.extend(run_pairs_configs())
    rows.extend(run_macro_configs())
    return rows


def find_qualifying(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        r for r in rows
        if "verdict" in r and r["train"]["trades"] >= 20 and r["test"]["trades"] >= 20
        and r["train"]["expectancy_r"] > 0 and r["test"]["expectancy_r"] > 0
    ]


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== Task B2: Forex 9-Strategy Sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['asset']} / {r['timeframe']} / {r['strategy']}: SKIPPED — {r['error']}")
            continue
        lines.append(
            f"{r['asset']} / {r['timeframe']} / {r['strategy']}: {r['verdict']} — "
            f"TRAIN {_fmt_half(r['train'])} | TEST {_fmt_half(r['test'])} ({r['candle_count']} candles)"
        )
    qualifying = find_qualifying(rows)
    lines.append("")
    lines.append(f"=== {len(qualifying)} configs qualify for grid-shift verification ===")
    for r in qualifying:
        lines.append(f"  {r['asset']} / {r['timeframe']} / {r['strategy']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_full_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
