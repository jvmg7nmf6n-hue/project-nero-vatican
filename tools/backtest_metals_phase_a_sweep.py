"""CLI: ASSET EXPANSION Phase A, Task 2 — full strategy sweep across SILVER and
PLATINUM. Every timeframe cleared Task 1's adequacy bar (see
docs/metals_data_calibration_audit.md) so nothing here is skipped for insufficient
data; a (config) can still be SKIPPED if a live fetch itself fails.

Every strategy's existing entry/exit/sizing LOGIC runs UNCHANGED — only per-asset
calibration varies (nero_core.strategies.timeframe_calibration.FEE_SCALE_FACTOR_BY_
ASSET, populated for SILVER/PLATINUM from Task 1's derivation in
nero_core/strategies/metals_calibration.py; DONCHIAN_TREND recalibrates its baked-in
GOLD default the same way for these two metals — see _donchian_params_for_asset).

Roster (strategy: applicable timeframes, per the task spec):
  1. MEAN_REVERSION v1        - 2h, 4h, 12h, 24h, 1week
  2. BREAKOUT_MOMENTUM        - 12h, 24h, 1week
  3. TREND_PULLBACK           - 2h, 4h, 12h, 24h, 1week
  4. DONCHIAN_TREND           - 1week
  5. VOLATILITY_SQUEEZE (x3 MA variants: ma200/ma150/ma100) - 2h, 4h, 12h, 24h, 1week
  6. FVG_REVERSION            - 2h, 4h, 12h
  7. BOS_CONTINUATION         - 4h, 12h, 24h
  8. COINTEGRATION_PAIRS      - Gold-Silver, Silver-Platinum @ 12h, 24h
  9. MACRO_RISK_ON            - daily (24h), both metals

Every config: chronological 70/30 split, bootstrap 95% CI + random-entry baseline
(tools.backtest_statistics), classify_verdict (SURVIVED / PROMISING-WATCHLIST /
DIED per MIN_SAMPLE_SIZE=20), LOW SAMPLE flags. Grid-shift verification (Task 3) is
a separate follow-up tool applied only to configs qualifying here as "positive both
halves, adequate sample."

RANDOM-BASELINE ELIGIBLE POOL per family (documented per-family since not every
strategy has a genuine regime/trigger split to isolate):
  - MEAN_REVERSION / BREAKOUT_MOMENTUM / TREND_PULLBACK: existing regime masks from
    tools.backtest_statistics (trend-filter precondition only, excluding the
    specific RSI/breakout/pullback trigger).
  - VOLATILITY_SQUEEZE: close > trend_ma (the trend-filter precondition; excludes
    the squeeze-streak/breakout trigger).
  - FVG_REVERSION / BOS_CONTINUATION: bidirectional MA200 trend masks narrowed to
    "has an actual signal this candle" (same adaptation as their own dedicated
    sweep tools — size_entry needs the touched zone/pivot's own data).
  - DONCHIAN_TREND: no regime precondition distinct from its own breakout trigger —
    eligible pool is every warmup-valid candle, same caveat as COINTEGRATION_PAIRS.
  - MACRO_RISK_ON: risk_on itself IS the regime (no further trigger beyond "regime
    holds and no position open"), so risk_on==True is the genuine eligible pool.
  - COINTEGRATION_PAIRS: existing PAIRS_REGIME_CAVEAT (50/50 random side, no
    regime-independent direction concept).

CROSS-VENDOR PAIR ALIGNMENT NOTE: GOLD (Twelve Data) stamps its daily close at
00:00 UTC; SILVER/PLATINUM (yfinance) stamp theirs at ~04:00 UTC for the SAME
calendar trading day — confirmed directly (GOLD 2026-07-18 close_time vs SILVER
2026-07-18 close_time differ by exactly 4 hours). An exact close_time join (the
existing cointegration_pairs.align_pair_candles, correct for same-vendor BTC-ETH)
produces ZERO aligned rows for Gold-Silver at 24h despite both series covering the
same ~10 years of calendar days. At 24h and 1week (at most one candle per calendar
day per series) this is safely fixed by joining on the normalized UTC calendar date
instead of the exact close_time (see align_pair_candles_by_date below) — used for
ALL pairs at 24h, not just cross-vendor ones, since it can only recover otherwise-
lost same-day rows, never misalign same-vendor data. At 12h (two candles per day,
each series' own bar edges an accident of wherever its underlying 1h history
happens to start — see aggregate_n_consecutive_candles) a day+half-day bucketing is
NOT provably safe, so Gold-Silver 12h is left on the standard exact-close_time join;
its practically-zero aligned-candle count (far below COINTEGRATION_PAIRS' own
window=200 rolling warmup) will self-report as 0 trades / DIED honestly, without
any special-cased skip logic.

No synthetic/fabricated price or macro data is ever used — if a fetch fails, that
combination is reported as SKIPPED with the reason, never a substituted result.

Usage:
    python tools/backtest_metals_phase_a_sweep.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
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
from nero_core.strategies.bos_continuation import DEFAULT_PARAMETERS as BOS_PARAMETERS
from nero_core.strategies.bos_continuation import INDICATOR_COLUMNS_TO_CHECK as BOS_INDICATOR_COLUMNS
from nero_core.strategies.bos_continuation import add_indicators as bos_add_indicators
from nero_core.strategies.bos_continuation import evaluate_exit as bos_evaluate_exit
from nero_core.strategies.bos_continuation import run_backtest as bos_run_backtest
from nero_core.strategies.bos_continuation import size_entry as bos_size_entry
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles, run_pairs_backtest
from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_DEFAULT_PARAMETERS
from nero_core.strategies.donchian_trend import INDICATOR_COLUMNS_TO_CHECK as DONCHIAN_INDICATOR_COLUMNS
from nero_core.strategies.donchian_trend import add_indicators as donchian_add_indicators
from nero_core.strategies.donchian_trend import evaluate_exit as donchian_evaluate_exit
from nero_core.strategies.donchian_trend import run_donchian_backtest
from nero_core.strategies.donchian_trend import size_entry as donchian_size_entry
from nero_core.strategies.fvg_reversion import DEFAULT_PARAMETERS as FVG_PARAMETERS
from nero_core.strategies.fvg_reversion import INDICATOR_COLUMNS_TO_CHECK as FVG_INDICATOR_COLUMNS
from nero_core.strategies.fvg_reversion import add_indicators as fvg_add_indicators
from nero_core.strategies.fvg_reversion import evaluate_exit as fvg_evaluate_exit
from nero_core.strategies.fvg_reversion import run_backtest as fvg_run_backtest
from nero_core.strategies.fvg_reversion import size_entry as fvg_size_entry
from nero_core.strategies.macro_risk_on import DEFAULT_PARAMETERS as MACRO_PARAMETERS
from nero_core.strategies.macro_risk_on import INDICATOR_COLUMNS_TO_CHECK as MACRO_INDICATOR_COLUMNS
from nero_core.strategies.macro_risk_on import add_indicators as macro_add_indicators
from nero_core.strategies.macro_risk_on import evaluate_exit as macro_evaluate_exit
from nero_core.strategies.macro_risk_on import run_macro_risk_on_backtest
from nero_core.strategies.macro_risk_on import size_entry as macro_size_entry
from nero_core.strategies.timeframe_calibration import FEE_SCALE_FACTOR_BY_ASSET, build_calibrated_params
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS, run_backtest
from tools.backtest_statistics import (
    MIN_SAMPLE_SIZE,
    above_ma200_mask,
    below_ma200_mask,
    bootstrap_mean_r_ci,
    classify_verdict,
    random_entry_baseline_bidirectional,
    random_entry_baseline_pairs,
    random_entry_baseline_single_asset,
)
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

METALS = ["SILVER", "PLATINUM"]

DONCHIAN_NO_REGIME_CAVEAT = (
    "DONCHIAN_TREND has no regime precondition distinct from its own breakout trigger "
    "(close > entry_channel_high IS the whole entry condition), so the eligible pool "
    "here is every warmup-valid candle rather than a regime-filtered subset — the same "
    "adaptation COINTEGRATION_PAIRS's own baseline already documents."
)

# --- per-family regime/eligible masks (see module docstring for rationale) -----------


def volatility_squeeze_regime_mask(evaluable: pd.DataFrame) -> pd.Series:
    return evaluable["close"] > evaluable["trend_ma"]


def donchian_eligible_mask(evaluable: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=evaluable.index)


def macro_risk_on_eligible_mask(evaluable: pd.DataFrame) -> pd.Series:
    return evaluable["risk_on"].fillna(False).astype(bool)


# --- family-specific half-stats builders --------------------------------------------


def _variant_half_stats(half_candles: pd.DataFrame, spec) -> dict[str, object]:
    trades, _state = run_backtest(half_candles, spec)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = spec.add_indicators_fn(half_candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    eligible_mask = spec.regime_mask_fn(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, spec.params, spec.size_entry_fn, expectancy_r, len(trades)
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _donchian_half_stats(half_candles: pd.DataFrame, params) -> dict[str, object]:
    trades, _state = run_donchian_backtest(half_candles, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = donchian_add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=DONCHIAN_INDICATOR_COLUMNS).reset_index(drop=True)
    eligible_mask = donchian_eligible_mask(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, donchian_size_entry, expectancy_r, len(trades),
        evaluate_exit_fn=donchian_evaluate_exit,
    )
    if baseline is not None:
        baseline = replace(baseline, caveat=DONCHIAN_NO_REGIME_CAVEAT)
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _fvg_half_stats(half_candles: pd.DataFrame, params) -> dict[str, object]:
    enriched = fvg_add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=FVG_INDICATOR_COLUMNS).reset_index(drop=True)
    trades, _state = fvg_run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    long_mask = above_ma200_mask(evaluable) & evaluable["fvg_bullish_signal_zone_bottom"].notna()
    short_mask = below_ma200_mask(evaluable) & evaluable["fvg_bearish_signal_zone_top"].notna()
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_bidirectional(
        evaluable, long_mask, short_mask, params, fvg_size_entry, fvg_evaluate_exit, expectancy_r, len(trades)
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _bos_half_stats(half_candles: pd.DataFrame, params) -> dict[str, object]:
    enriched = bos_add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=BOS_INDICATOR_COLUMNS).reset_index(drop=True)
    trades, _state = bos_run_backtest(evaluable, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    long_mask = above_ma200_mask(evaluable) & evaluable["bos_up_signal_pivot_value"].notna()
    short_mask = below_ma200_mask(evaluable) & evaluable["bos_down_signal_pivot_value"].notna()
    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_bidirectional(
        evaluable, long_mask, short_mask, params, bos_size_entry, bos_evaluate_exit, expectancy_r, len(trades)
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _pairs_half_stats(aligned_half: pd.DataFrame, x_name: str, y_name: str) -> dict[str, object]:
    enriched = pairs_add_indicators(aligned_half, PAIRS_PARAMETERS, x_name, y_name)
    evaluable = enriched.dropna(subset=["zscore"]).reset_index(drop=True)
    trades, _state = run_pairs_backtest(evaluable, PAIRS_PARAMETERS, x_name, y_name)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_pairs(evaluable, PAIRS_PARAMETERS, x_name, y_name, expectancy_r, len(trades))
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _macro_half_stats(half_regime_frame: pd.DataFrame, params) -> dict[str, object]:
    trades, _state = run_macro_risk_on_backtest(half_regime_frame, params)
    r_values = [t.r_multiple for t in trades]
    expectancy_r = sum(r_values) / len(r_values) if r_values else 0.0

    enriched = macro_add_indicators(half_regime_frame, params)
    evaluable = enriched.dropna(subset=MACRO_INDICATOR_COLUMNS).reset_index(drop=True)
    eligible_mask = macro_risk_on_eligible_mask(evaluable)

    ci = bootstrap_mean_r_ci(r_values)
    baseline = random_entry_baseline_single_asset(
        evaluable, eligible_mask, params, macro_size_entry, expectancy_r, len(trades),
        evaluate_exit_fn=macro_evaluate_exit,
    )
    return {
        "trades": len(trades), "expectancy_r": expectancy_r,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


SINGLE_ASSET_ROSTER = [
    {"label": "MEAN_REVERSION v1", "variant_key": "mean_reversion_v1", "timeframes": ["2h", "4h", "12h", "24h", "1week"],
     "regime_mask_fn": above_ma200_mask},
    {"label": "BREAKOUT_MOMENTUM", "variant_key": "breakout_momentum", "timeframes": ["12h", "24h", "1week"],
     "regime_mask_fn": above_ma200_mask},
    {"label": "TREND_PULLBACK", "variant_key": "trend_pullback", "timeframes": ["2h", "4h", "12h", "24h", "1week"],
     "regime_mask_fn": lambda evaluable: (evaluable["close"] > evaluable["ma200"]) & (evaluable["ma50"] > evaluable["ma200"])},
    {"label": "VOLATILITY_SQUEEZE ma200", "variant_key": "volatility_squeeze_ma200", "timeframes": ["2h", "4h", "12h", "24h", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma150", "variant_key": "volatility_squeeze_ma150", "timeframes": ["2h", "4h", "12h", "24h", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
    {"label": "VOLATILITY_SQUEEZE ma100", "variant_key": "volatility_squeeze_ma100", "timeframes": ["2h", "4h", "12h", "24h", "1week"],
     "regime_mask_fn": volatility_squeeze_regime_mask},
]

FVG_TIMEFRAMES = ["2h", "4h", "12h"]
BOS_TIMEFRAMES = ["4h", "12h", "24h"]
DONCHIAN_TIMEFRAMES = ["1week"]

PAIRS_CONFIGS = [
    {"label": "Gold-Silver", "x": "GOLD", "y": "SILVER"},
    {"label": "Silver-Platinum", "x": "SILVER", "y": "PLATINUM"},
]
PAIRS_TIMEFRAMES = ["12h", "24h"]


def _donchian_params_for_asset(asset: str):
    """DONCHIAN_TREND's registered defaults already bake in GOLD's fee scale (it has
    no crypto-scoped sibling to default to crypto fees against — see
    donchian_trend.py's docstring), so build_calibrated_params would double-apply for
    GOLD. For SILVER/PLATINUM, re-derive fresh from the crypto baseline (10.0/2.0) with
    THIS metal's own scale factor instead of reusing the GOLD-baked default."""
    scale = FEE_SCALE_FACTOR_BY_ASSET[asset]
    return replace(DONCHIAN_DEFAULT_PARAMETERS, fee_bps=10.0 * scale, slippage_bps=2.0 * scale)


def run_single_asset_configs(client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    candle_cache: dict[tuple[str, str], tuple[pd.DataFrame, str]] = {}

    def cached_fetch(asset: str, timeframe: str):
        key = (asset, timeframe)
        if key not in candle_cache:
            candle_cache[key] = fetch_timeframe_candles(client, asset, timeframe)
        return candle_cache[key]

    for entry in SINGLE_ASSET_ROSTER:
        for asset in METALS:
            for timeframe in entry["timeframes"]:
                start = time.monotonic()
                try:
                    candles, method = cached_fetch(asset, timeframe)
                except MarketDataUnavailableError as exc:
                    print(f"{asset} / {timeframe} / {entry['label']}: SKIPPED — {exc}")
                    rows.append({"asset": asset, "timeframe": timeframe, "strategy": entry["label"], "error": str(exc)})
                    continue

                base_spec = VARIANT_SPECS[entry["variant_key"]]
                calibrated_params = build_calibrated_params(base_spec.params, timeframe, asset)
                spec = replace(base_spec, params=calibrated_params, label=entry["label"])
                spec = _AttachedMaskSpec(spec, entry["regime_mask_fn"])

                train, test = split_chronological(candles)
                train_stats = _variant_half_stats(train, spec)
                test_stats = _variant_half_stats(test, spec)
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe} / {entry['label']}: done ({elapsed:.1f}s, {len(candles)} candles)")
                rows.append({
                    "asset": asset, "timeframe": timeframe, "strategy": entry["label"], "method": method,
                    "candle_count": len(candles), "train": train_stats, "test": test_stats,
                    "verdict": classify_verdict(train_stats, test_stats),
                })

    for asset in METALS:
        timeframe = DONCHIAN_TIMEFRAMES[0]
        start = time.monotonic()
        try:
            candles, method = cached_fetch(asset, timeframe)
        except MarketDataUnavailableError as exc:
            print(f"{asset} / {timeframe} / DONCHIAN_TREND: SKIPPED — {exc}")
            rows.append({"asset": asset, "timeframe": timeframe, "strategy": "DONCHIAN_TREND", "error": str(exc)})
            continue
        params = _donchian_params_for_asset(asset)
        train, test = split_chronological(candles)
        train_stats = _donchian_half_stats(train, params)
        test_stats = _donchian_half_stats(test, params)
        elapsed = time.monotonic() - start
        print(f"{asset} / {timeframe} / DONCHIAN_TREND: done ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": asset, "timeframe": timeframe, "strategy": "DONCHIAN_TREND", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": classify_verdict(train_stats, test_stats),
        })

    for asset in METALS:
        for timeframe in FVG_TIMEFRAMES:
            start = time.monotonic()
            try:
                candles, method = cached_fetch(asset, timeframe)
            except MarketDataUnavailableError as exc:
                print(f"{asset} / {timeframe} / FVG_REVERSION: SKIPPED — {exc}")
                rows.append({"asset": asset, "timeframe": timeframe, "strategy": "FVG_REVERSION", "error": str(exc)})
                continue
            params = build_calibrated_params(FVG_PARAMETERS, timeframe, asset)
            train, test = split_chronological(candles)
            train_stats = _fvg_half_stats(train, params)
            test_stats = _fvg_half_stats(test, params)
            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe} / FVG_REVERSION: done ({elapsed:.1f}s, {len(candles)} candles)")
            rows.append({
                "asset": asset, "timeframe": timeframe, "strategy": "FVG_REVERSION", "method": method,
                "candle_count": len(candles), "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })

    for asset in METALS:
        for timeframe in BOS_TIMEFRAMES:
            start = time.monotonic()
            try:
                candles, method = cached_fetch(asset, timeframe)
            except MarketDataUnavailableError as exc:
                print(f"{asset} / {timeframe} / BOS_CONTINUATION: SKIPPED — {exc}")
                rows.append({"asset": asset, "timeframe": timeframe, "strategy": "BOS_CONTINUATION", "error": str(exc)})
                continue
            params = build_calibrated_params(BOS_PARAMETERS, timeframe, asset)
            train, test = split_chronological(candles)
            train_stats = _bos_half_stats(train, params)
            test_stats = _bos_half_stats(test, params)
            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe} / BOS_CONTINUATION: done ({elapsed:.1f}s, {len(candles)} candles)")
            rows.append({
                "asset": asset, "timeframe": timeframe, "strategy": "BOS_CONTINUATION", "method": method,
                "candle_count": len(candles), "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })

    return rows


class _AttachedMaskSpec:
    """Thin wrapper: VariantSpec is a frozen dataclass without a regime_mask_fn field,
    but _variant_half_stats wants one alongside it — rather than modifying the shared
    VariantSpec dataclass (used across many other tools), attach the mask function as
    a plain attribute on a proxy object that forwards everything else."""

    def __init__(self, spec, regime_mask_fn):
        self._spec = spec
        self.regime_mask_fn = regime_mask_fn

    def __getattr__(self, name):
        return getattr(self._spec, name)


def run_pairs_configs(client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pair in PAIRS_CONFIGS:
        x_name, y_name = pair["x"], pair["y"]
        for timeframe in PAIRS_TIMEFRAMES:
            start = time.monotonic()
            try:
                x_candles, x_method = fetch_timeframe_candles(client, x_name, timeframe)
                y_candles, y_method = fetch_timeframe_candles(client, y_name, timeframe)
            except MarketDataUnavailableError as exc:
                print(f"{pair['label']} / {timeframe}: SKIPPED — {exc}")
                rows.append({"asset": pair["label"], "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS", "error": str(exc)})
                continue

            aligned = (
                align_pair_candles_by_date(x_candles, y_candles, x_name, y_name)
                if timeframe == "24h"
                else align_pair_candles(x_candles, y_candles, x_name, y_name)
            )
            if aligned.empty:
                reason = f"no overlapping candle timestamps between {x_name} and {y_name}"
                print(f"{pair['label']} / {timeframe}: SKIPPED — {reason}")
                rows.append({"asset": pair["label"], "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS", "error": reason})
                continue

            train_raw, test_raw = split_chronological(aligned)
            train_stats = _pairs_half_stats(train_raw, x_name, y_name)
            test_stats = _pairs_half_stats(test_raw, x_name, y_name)
            elapsed = time.monotonic() - start
            print(f"{pair['label']} / {timeframe}: done ({elapsed:.1f}s, {len(aligned)} aligned candles)")
            rows.append({
                "asset": pair["label"], "timeframe": timeframe, "strategy": "COINTEGRATION_PAIRS",
                "method": f"{x_method} + {y_method}", "candle_count": len(aligned),
                "train": train_stats, "test": test_stats,
                "verdict": classify_verdict(train_stats, test_stats),
            })
    return rows


def align_pair_candles_by_date(x_candles: pd.DataFrame, y_candles: pd.DataFrame, x_name: str, y_name: str) -> pd.DataFrame:
    """Cross-vendor-safe alignment for timeframes with at most one candle per
    calendar day (24h, 1week): joins on the normalized UTC calendar date instead of
    the exact close_time, then keeps the x leg's own close_time/date as the aligned
    row's canonical timestamp (an arbitrary but consistent choice — the y leg's own
    intraday stamp detail is discarded). See module docstring's CROSS-VENDOR PAIR
    ALIGNMENT NOTE for why an exact-close_time join fails here. Same output contract
    as cointegration_pairs.align_pair_candles (close_time, date, {x}_close, {y}_close)
    so add_indicators/run_pairs_backtest/split_chronological all work unchanged."""
    x = x_candles[["close_time", "date", "close"]].copy()
    x["day"] = pd.to_datetime(x["date"], utc=True).dt.normalize()
    x = x.rename(columns={"close": f"{x_name}_close"})
    y = y_candles[["date", "close"]].copy()
    y["day"] = pd.to_datetime(y["date"], utc=True).dt.normalize()
    y = y.rename(columns={"close": f"{y_name}_close"})
    merged = x.merge(y[["day", f"{y_name}_close"]], on="day", how="inner")
    return merged.drop(columns=["day"]).sort_values("close_time").reset_index(drop=True)


def _slice_macro_from(series: pd.Series, start_date: pd.Timestamp) -> pd.Series:
    return series[series.index >= start_date]


def _slice_macro_until(series: pd.Series, end_date: pd.Timestamp) -> pd.Series:
    return series[series.index <= end_date]


def run_macro_configs(client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        dollar_series, dollar_source = fetch_dollar_proxy_daily()
        print(f"Dollar proxy: {dollar_source} ({len(dollar_series)} business days)")
        dfii10_series, dfii10_source = fetch_dfii10_daily()
        print(f"DFII10: {dfii10_source} ({len(dfii10_series)} business days)")
    except MacroDataUnavailableError as exc:
        print(f"MACRO_RISK_ON: BLOCKED — {exc}")
        for asset in METALS:
            rows.append({"asset": asset, "timeframe": "24h", "strategy": "MACRO_RISK_ON", "error": str(exc)})
        return rows

    for asset in METALS:
        start = time.monotonic()
        try:
            candles, method = fetch_timeframe_candles(client, asset, "24h")
        except MarketDataUnavailableError as exc:
            print(f"{asset} / 24h / MACRO_RISK_ON: SKIPPED — {exc}")
            rows.append({"asset": asset, "timeframe": "24h", "strategy": "MACRO_RISK_ON", "error": str(exc)})
            continue

        train_candles, test_candles = split_chronological(candles)
        if train_candles.empty or test_candles.empty:
            reason = "not enough daily history to split 70/30"
            print(f"{asset} / 24h / MACRO_RISK_ON: SKIPPED — {reason}")
            rows.append({"asset": asset, "timeframe": "24h", "strategy": "MACRO_RISK_ON", "error": reason})
            continue

        train_end = pd.to_datetime(train_candles["date"]).dt.tz_localize(None).max()
        test_start = pd.to_datetime(test_candles["date"]).dt.tz_localize(None).min()

        train_regime = build_regime_frame(train_candles, _slice_macro_until(dollar_series, train_end), _slice_macro_until(dfii10_series, train_end))
        test_regime = build_regime_frame(test_candles, _slice_macro_from(dollar_series, test_start), _slice_macro_from(dfii10_series, test_start))

        train_stats = _macro_half_stats(train_regime, MACRO_PARAMETERS)
        test_stats = _macro_half_stats(test_regime, MACRO_PARAMETERS)
        elapsed = time.monotonic() - start
        print(f"{asset} / 24h / MACRO_RISK_ON: done ({elapsed:.1f}s, {len(candles)} candles)")
        rows.append({
            "asset": asset, "timeframe": "24h", "strategy": "MACRO_RISK_ON", "method": method,
            "candle_count": len(candles), "train": train_stats, "test": test_stats,
            "verdict": classify_verdict(train_stats, test_stats),
        })
    return rows


def run_full_sweep() -> list[dict[str, object]]:
    client = MarketDataClient()
    rows = run_single_asset_configs(client)
    rows.extend(run_pairs_configs(client))
    rows.extend(run_macro_configs(client))
    return rows


def find_qualifying(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Positive expectancy in BOTH halves with >= MIN_SAMPLE_SIZE trades in EACH
    half — the exact bar Task 3's grid-shift verification applies to next, per the
    task's "any config positive in both halves with adequate sample" wording."""
    qualifying = []
    for row in rows:
        if "error" in row:
            continue
        train, test = row["train"], row["test"]
        if (
            train["trades"] >= MIN_SAMPLE_SIZE and test["trades"] >= MIN_SAMPLE_SIZE
            and train["expectancy_r"] > 0 and test["expectancy_r"] > 0
        ):
            qualifying.append(row)
    return qualifying


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else " "
    ci = stats["ci"]
    ci_str = "n/a" if ci is None else ("XZERO" if ci.crosses_zero else "clear")
    return f"N={stats['trades']:>4}{flag} ExpR={stats['expectancy_r']:>7.3f} CI={ci_str:<5}"


def format_report(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    header = f"{'Asset':<16}{'TF':<7}{'Strategy':<26}{'Verdict':<22}{'TRAIN':<28}{'TEST':<28}"
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        if "error" in row:
            lines.append(f"{row['asset']:<16}{row['timeframe']:<7}{row['strategy']:<26}SKIPPED — {row['error']}")
            continue
        lines.append(
            f"{row['asset']:<16}{row['timeframe']:<7}{row['strategy']:<26}{row['verdict']:<22}"
            f"{_fmt_half(row['train']):<28}{_fmt_half(row['test']):<28}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample.")

    qualifying = find_qualifying(rows)
    lines.append("")
    lines.append(f"Configs positive in BOTH halves with >= {MIN_SAMPLE_SIZE} trades each half (Task 3 grid-shift candidates):")
    if not qualifying:
        lines.append("  None.")
    else:
        for row in qualifying:
            lines.append(f"  {row['asset']} / {row['timeframe']} / {row['strategy']}")
    return "\n".join(lines)


def main() -> None:
    rows = run_full_sweep()
    print()
    print(format_report(rows))


if __name__ == "__main__":
    main()
