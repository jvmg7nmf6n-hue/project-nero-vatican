"""CLI: PSX Strategy Sweep, Phase 1, Task 2 — full 9-strategy sweep across Pakistan's
top liquid blue-chips. Vatican's first emerging-market research batch, built directly
on docs/psx_data_audit.md's YELLOW-verdict findings and Task 1's data pipeline
(nero_core/data_sources/psx_data.py).

Universe: OGDC, LUCK, HBL (the audit's own recommended first-pass universe — MARI and
ENGRO/ENGROH were excluded per the audit's confirmed corporate-action/ticker-succession
caveats). Timeframe: 1day only (the audit found no evidence of PSX intraday data from
any source). Data span: the most recent 10 years of each ticker's history (see
_last_n_years), 70/30 chronological split.

Every strategy's existing entry/exit/sizing LOGIC runs UNCHANGED — only fees are
calibrated (flat 0.15% per side, reflecting current Pakistani online brokerage rates —
Meezan Invest/Arif Habib tier — per this task's own spec, NOT a derived price/ATR scale
factor like GOLD/SILVER/PLATINUM) and max_holding_hours is re-derived for the 1day
candle duration (same candle-COUNT-preservation fix used for every other asset class in
this project).

Roster (strategy: notes):
  1. MEAN_REVERSION v1
  2. BREAKOUT_MOMENTUM
  3. TREND_PULLBACK
  4. DONCHIAN_TREND
  5. VOLATILITY_SQUEEZE (x3 MA variants: ma200/ma150/ma100)
  6. FVG_REVERSION
  7. BOS_CONTINUATION
  8. COINTEGRATION_PAIRS — OGDC-LUCK, OGDC-HBL, LUCK-HBL @ 1day (same-vendor
     yfinance join, no cross-vendor timestamp issue — unlike GOLD-SILVER in the
     metals sweep, every PSX leg here is fetched the same way)
  9. MACRO_RISK_ON, Pakistan-adapted — OGDC uses
     psx_data.build_psx_regime_frame_oil_and_currency (USD/PKR rising AND oil
     rising); LUCK/HBL use psx_data.build_psx_regime_frame_currency_only (USD/PKR
     rising alone). The underlying nero_core.strategies.macro_risk_on strategy code
     is completely UNCHANGED — only the upstream regime-frame data differs, per
     psx_data.py's own documented column-name-reuse contract.

GRID-SHIFT: NOT_APPLICABLE for every config in this sweep. Grid-shift verification
requires resampling from a finer-grained (intraday) source at a shifted clock offset to
prove a config's edge survives an arbitrary bar-boundary choice — no PSX intraday data
source exists anywhere (confirmed in the audit), so there is nothing to resample from.
Per the metals/stocks precedent, any config that would otherwise qualify as SURVIVED
(positive both halves, adequate sample, bootstrap CI clears zero both halves) is
explicitly CAPPED at PROMISING-WATCHLIST in this sweep's own reporting — never silently
reported as SURVIVED, since "mandatory grid-shift verification" (this project's own
established rule) was structurally impossible to run.

All family-specific half-stats builders, regime-mask helpers, and the
_AttachedMaskSpec proxy are REUSED directly from tools.backtest_metals_phase_a_sweep —
none of that logic is asset-specific, so re-deriving it here would just be duplication
with a different universe list.

No synthetic/fabricated price or macro data is ever used — if a fetch fails or a
corporate-action break is detected, that combination is reported as SKIPPED with the
reason, never a substituted result.

Usage:
    python -m tools.backtest_psx_sweep
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.psx_data import (
    PsxCorporateActionSuspectedError,
    PsxMacroDataUnavailableError,
    build_psx_regime_frame_currency_only,
    build_psx_regime_frame_oil_and_currency,
    fetch_oil_price_daily,
    fetch_psx_stock_ohlcv,
    fetch_usd_pkr_daily,
)
from nero_core.data_sources.stock_data import StockDataUnavailableError
from nero_core.strategies.bos_continuation import DEFAULT_PARAMETERS as BOS_PARAMETERS
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import align_pair_candles
from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_DEFAULT_PARAMETERS
from nero_core.strategies.fvg_reversion import DEFAULT_PARAMETERS as FVG_PARAMETERS
from nero_core.strategies.macro_risk_on import DEFAULT_PARAMETERS as MACRO_PARAMETERS
from tools.backtest_compare import VARIANT_SPECS
from tools.backtest_metals_phase_a_sweep import (
    DONCHIAN_NO_REGIME_CAVEAT,
    _AttachedMaskSpec,
    _bos_half_stats,
    _donchian_half_stats,
    _fvg_half_stats,
    _macro_half_stats,
    _pairs_half_stats,
    _variant_half_stats,
    volatility_squeeze_regime_mask,
)
from tools.backtest_statistics import MIN_SAMPLE_SIZE, above_ma200_mask, classify_verdict
from tools.backtest_train_test_split import split_chronological

PSX_UNIVERSE = ["OGDC", "LUCK", "HBL"]

# Flat, per this task's own spec — reflects current Pakistani online brokerage rates
# (Meezan Invest / Arif Habib tier), NOT a derived price/ATR scale factor.
PSX_FEE_BPS = 15.0  # 0.15% per side
PSX_SLIPPAGE_BPS = 2.0  # unchanged crypto-baseline default; not otherwise specified

PSX_HOURS_PER_TIMEFRAME = {"1day": 24}
ORIGINAL_MAX_HOLDING_CANDLES = 24  # same baked-in candle-count convention as every other asset class

DATA_SPAN_YEARS = 10


def psx_calibrated_params(base_params, timeframe: str = "1day"):
    """Flat 0.15%/side fee, unchanged slippage, and a re-derived max_holding_hours that
    preserves the original 24-CANDLE hold cap at this timeframe's own candle duration.
    Strategies with no max_holding_hours field at all (DONCHIAN_TREND, MACRO_RISK_ON)
    are left alone on that field, matching the stocks/metals precedent exactly."""
    kwargs = {"fee_bps": PSX_FEE_BPS, "slippage_bps": PSX_SLIPPAGE_BPS}
    if hasattr(base_params, "max_holding_hours"):
        kwargs["max_holding_hours"] = ORIGINAL_MAX_HOLDING_CANDLES * PSX_HOURS_PER_TIMEFRAME[timeframe]
    return replace(base_params, **kwargs)


def _last_n_years(candles: pd.DataFrame, years: int = DATA_SPAN_YEARS) -> pd.DataFrame:
    if candles.empty:
        return candles
    cutoff = pd.to_datetime(candles["date"]).max() - pd.DateOffset(years=years)
    return candles[pd.to_datetime(candles["date"]) >= cutoff].reset_index(drop=True)


SINGLE_ASSET_ROSTER = [
    {"label": "MEAN_REVERSION v1", "variant_key": "mean_reversion_v1", "regime_mask_fn": above_ma200_mask},
    {"label": "BREAKOUT_MOMENTUM", "variant_key": "breakout_momentum", "regime_mask_fn": above_ma200_mask},
    {"label": "TREND_PULLBACK", "variant_key": "trend_pullback",
     "regime_mask_fn": lambda evaluable: (evaluable["close"] > evaluable["ma200"]) & (evaluable["ma50"] > evaluable["ma200"])},
    {"label": "VOLATILITY_SQUEEZE ma200", "variant_key": "volatility_squeeze_ma200", "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma150", "variant_key": "volatility_squeeze_ma150", "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma100", "variant_key": "volatility_squeeze_ma100", "regime_mask_fn": volatility_squeeze_regime_mask},
]

PAIRS_CONFIGS = [
    {"label": "OGDC-LUCK", "x": "OGDC", "y": "LUCK"},
    {"label": "OGDC-HBL", "x": "OGDC", "y": "HBL"},
    {"label": "LUCK-HBL", "x": "LUCK", "y": "HBL"},
]

# OGDC gets the oil+currency regime (direct oil revenue exposure); LUCK/HBL get the
# currency-only regime (cement import costs / banking-sector currency exposure).
MACRO_ASSET_REGIME_KIND = {"OGDC": "oil_and_currency", "LUCK": "currency_only", "HBL": "currency_only"}


def _cached_fetch(cache: dict, symbol: str):
    if symbol not in cache:
        result = fetch_psx_stock_ohlcv(symbol)
        cache[symbol] = (_last_n_years(result.prices), result.source)
    return cache[symbol]


def _try_fetch(cache: dict, symbol: str):
    try:
        return _cached_fetch(cache, symbol), None
    except (StockDataUnavailableError, PsxCorporateActionSuspectedError) as exc:
        return None, str(exc)


def _apply_grid_shift_cap(verdict: str) -> tuple[str, str | None]:
    """Grid-shift is structurally NOT_APPLICABLE for every PSX config in this sweep (no
    intraday PSX source exists to resample from) -- a raw SURVIVED verdict is
    downgraded to PROMISING-WATCHLIST rather than reported as-is, per this project's
    mandatory-grid-shift-verification rule."""
    if verdict == "SURVIVED":
        return "PROMISING-WATCHLIST", "grid-shift NOT_APPLICABLE (no PSX intraday data source exists); capped from raw SURVIVED"
    return verdict, None


def run_single_asset_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candle_cache: dict[str, tuple[pd.DataFrame, str]] = {}

    for entry in SINGLE_ASSET_ROSTER:
        for symbol in PSX_UNIVERSE:
            start = time.monotonic()
            fetched, error = _try_fetch(candle_cache, symbol)
            if error is not None:
                print(f"{symbol} / 1day / {entry['label']}: SKIPPED — {error}")
                rows.append({"asset": symbol, "timeframe": "1day", "strategy": entry["label"], "error": error})
                continue
            candles, method = fetched

            base_spec = VARIANT_SPECS[entry["variant_key"]]
            calibrated_params = psx_calibrated_params(base_spec.params)
            spec = replace(base_spec, params=calibrated_params, label=entry["label"])
            spec = _AttachedMaskSpec(spec, entry["regime_mask_fn"])

            train, test = split_chronological(candles)
            train_stats = _variant_half_stats(train, spec)
            test_stats = _variant_half_stats(test, spec)
            raw_verdict = classify_verdict(train_stats, test_stats)
            verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
            elapsed = time.monotonic() - start
            print(f"{symbol} / 1day / {entry['label']}: {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
            rows.append({
                "asset": symbol, "timeframe": "1day", "strategy": entry["label"], "method": method,
                "candle_count": len(candles), "train": train_stats, "test": test_stats,
                "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
            })

    for symbol in PSX_UNIVERSE:
        start = time.monotonic()
        fetched, error = _try_fetch(candle_cache, symbol)
        if error is not None:
            print(f"{symbol} / 1day / DONCHIAN_TREND: SKIPPED — {error}")
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "DONCHIAN_TREND", "error": error})
            continue
        candles, method = fetched
        params = psx_calibrated_params(DONCHIAN_DEFAULT_PARAMETERS)
        train, test = split_chronological(candles)
        train_stats = _donchian_half_stats(train, params)
        test_stats = _donchian_half_stats(test, params)
        raw_verdict = classify_verdict(train_stats, test_stats)
        verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
        elapsed = time.monotonic() - start
        print(f"{symbol} / 1day / DONCHIAN_TREND: {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": symbol, "timeframe": "1day", "strategy": "DONCHIAN_TREND", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
        })

    for symbol in PSX_UNIVERSE:
        start = time.monotonic()
        fetched, error = _try_fetch(candle_cache, symbol)
        if error is not None:
            print(f"{symbol} / 1day / FVG_REVERSION: SKIPPED — {error}")
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "FVG_REVERSION", "error": error})
            continue
        candles, method = fetched
        params = psx_calibrated_params(FVG_PARAMETERS)
        train, test = split_chronological(candles)
        train_stats = _fvg_half_stats(train, params)
        test_stats = _fvg_half_stats(test, params)
        raw_verdict = classify_verdict(train_stats, test_stats)
        verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
        elapsed = time.monotonic() - start
        print(f"{symbol} / 1day / FVG_REVERSION: {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": symbol, "timeframe": "1day", "strategy": "FVG_REVERSION", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
        })

    for symbol in PSX_UNIVERSE:
        start = time.monotonic()
        fetched, error = _try_fetch(candle_cache, symbol)
        if error is not None:
            print(f"{symbol} / 1day / BOS_CONTINUATION: SKIPPED — {error}")
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "BOS_CONTINUATION", "error": error})
            continue
        candles, method = fetched
        params = psx_calibrated_params(BOS_PARAMETERS)
        train, test = split_chronological(candles)
        train_stats = _bos_half_stats(train, params)
        test_stats = _bos_half_stats(test, params)
        raw_verdict = classify_verdict(train_stats, test_stats)
        verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
        elapsed = time.monotonic() - start
        print(f"{symbol} / 1day / BOS_CONTINUATION: {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": symbol, "timeframe": "1day", "strategy": "BOS_CONTINUATION", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
        })

    return rows


def run_pairs_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candle_cache: dict[str, tuple[pd.DataFrame, str]] = {}
    for pair in PAIRS_CONFIGS:
        label = pair["label"]
        start = time.monotonic()
        x_fetched, x_error = _try_fetch(candle_cache, pair["x"])
        y_fetched, y_error = _try_fetch(candle_cache, pair["y"])
        if x_error is not None or y_error is not None:
            reason = x_error or y_error
            print(f"{label} / 1day / COINTEGRATION_PAIRS: SKIPPED — {reason}")
            rows.append({"asset": label, "timeframe": "1day", "strategy": "COINTEGRATION_PAIRS", "error": reason})
            continue
        x_candles, x_method = x_fetched
        y_candles, y_method = y_fetched

        aligned = align_pair_candles(x_candles, y_candles, pair["x"], pair["y"])
        if aligned.empty:
            reason = "no aligned candles (exact close_time join found zero overlap)"
            print(f"{label} / 1day / COINTEGRATION_PAIRS: SKIPPED — {reason}")
            rows.append({"asset": label, "timeframe": "1day", "strategy": "COINTEGRATION_PAIRS", "error": reason})
            continue

        train, test = split_chronological(aligned)
        train_stats = _pairs_half_stats(train, pair["x"], pair["y"])
        test_stats = _pairs_half_stats(test, pair["x"], pair["y"])
        raw_verdict = classify_verdict(train_stats, test_stats)
        verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
        elapsed = time.monotonic() - start
        print(f"{label} / 1day / COINTEGRATION_PAIRS: {verdict} ({elapsed:.1f}s, {len(aligned)} aligned candles)")
        rows.append({
            "asset": label, "timeframe": "1day", "strategy": "COINTEGRATION_PAIRS",
            "method": f"NATIVE: {x_method} + {y_method}",
            "candle_count": len(aligned), "train": train_stats, "test": test_stats,
            "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
        })
    return rows


def run_macro_configs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        usdpkr_series, usdpkr_source = fetch_usd_pkr_daily()
        print(f"USD/PKR: {usdpkr_source} ({len(usdpkr_series)} business days)")
        oil_series, oil_source = fetch_oil_price_daily()
        print(f"WTI oil: {oil_source} ({len(oil_series)} business days)")
    except PsxMacroDataUnavailableError as exc:
        print(f"MACRO_RISK_ON: BLOCKED — {exc}")
        for symbol in PSX_UNIVERSE:
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": str(exc)})
        return rows

    candle_cache: dict[str, tuple[pd.DataFrame, str]] = {}
    for symbol in PSX_UNIVERSE:
        start = time.monotonic()
        fetched, error = _try_fetch(candle_cache, symbol)
        if error is not None:
            print(f"{symbol} / 1day / MACRO_RISK_ON: SKIPPED — {error}")
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": error})
            continue
        candles, method = fetched

        train_candles, test_candles = split_chronological(candles)
        if train_candles.empty or test_candles.empty:
            reason = "not enough daily history to split 70/30"
            print(f"{symbol} / 1day / MACRO_RISK_ON: SKIPPED — {reason}")
            rows.append({"asset": symbol, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "error": reason})
            continue

        if MACRO_ASSET_REGIME_KIND[symbol] == "oil_and_currency":
            train_regime = build_psx_regime_frame_oil_and_currency(train_candles, usdpkr_series, oil_series)
            test_regime = build_psx_regime_frame_oil_and_currency(test_candles, usdpkr_series, oil_series)
        else:
            train_regime = build_psx_regime_frame_currency_only(train_candles, usdpkr_series)
            test_regime = build_psx_regime_frame_currency_only(test_candles, usdpkr_series)

        train_stats = _macro_half_stats(train_regime, MACRO_PARAMETERS)
        test_stats = _macro_half_stats(test_regime, MACRO_PARAMETERS)
        raw_verdict = classify_verdict(train_stats, test_stats)
        verdict, cap_note = _apply_grid_shift_cap(raw_verdict)
        elapsed = time.monotonic() - start
        print(f"{symbol} / 1day / MACRO_RISK_ON ({MACRO_ASSET_REGIME_KIND[symbol]}): {verdict} ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": symbol, "timeframe": "1day", "strategy": "MACRO_RISK_ON", "method": method,
            "regime_kind": MACRO_ASSET_REGIME_KIND[symbol],
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": verdict, "raw_verdict": raw_verdict, "grid_shift_note": cap_note,
        })
    return rows


def run_full_sweep() -> list[dict[str, object]]:
    rows = run_single_asset_configs()
    rows.extend(run_pairs_configs())
    rows.extend(run_macro_configs())
    return rows


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    return f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== PSX Strategy Sweep, Phase 1: 9-Strategy Sweep ===", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['asset']} / {r['timeframe']} / {r['strategy']}: SKIPPED — {r['error']}")
            continue
        lines.append(
            f"{r['asset']} / {r['timeframe']} / {r['strategy']}: {r['verdict']} — "
            f"TRAIN {_fmt_half(r['train'])} | TEST {_fmt_half(r['test'])} ({r['candle_count']} candles)"
        )
        if r.get("grid_shift_note"):
            lines.append(f"    note: {r['grid_shift_note']}")

    survivors = [r for r in rows if r.get("verdict") in ("SURVIVED", "PROMISING-WATCHLIST")]
    lines.append("")
    lines.append(f"=== {len(survivors)} config(s) SURVIVED or PROMISING-WATCHLIST (promotion candidates) ===")
    for r in survivors:
        lines.append(f"  {r['asset']} / {r['timeframe']} / {r['strategy']}: {r['verdict']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_full_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
