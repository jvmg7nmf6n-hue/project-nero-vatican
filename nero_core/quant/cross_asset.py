"""Day 5/7 Quant Intelligence Panel, Part 2: cross-asset relationships (correlation,
volatility regime, cointegration, lead-lag). Reuses nero_core.quant.quant_intelligence
wherever its existing signature is a clean fit (log_returns, rolling_correlation,
build_garch_volatility_report) -- see Day 5's Stage 0 report for exactly what was and
wasn't reused, and why the Engle-Granger test here is written fresh against
statsmodels.tsa.stattools.coint directly rather than reusing quant_intelligence's own
engle_granger_cointegration (a different, OLS+adfuller-based implementation without
coint()'s MacKinnon-corrected p-value).

CRITICAL, CONFIRMED AGAINST REAL DATA BEFORE WRITING ANY OF THIS: candle files sharing
the same nominal TIMEFRAME TOKEN do not necessarily share the same underlying calendar
grid. SILVER's "24h" file (yfinance COMEX futures, business-days-only, 04:00 UTC
close) has ZERO overlapping timestamps with BTC/GOLD's "24h" files (24/7, 00:00 UTC
close) -- confirmed directly, not assumed. Every function here aligns a pair by their
ACTUAL SHARED TIMESTAMPS (an inner join on each candle's own `time` field), never by
list position -- correlating same-index-but-different-real-date closes would be
exactly the spurious-correlation failure mode this task's own "same timeframe only"
constraint warns about, just hidden one layer deeper than the across-timeframe case.
This is also why BTC-vs-BNB (Part D) and GOLD-vs-SILVER / BTC-vs-BNB (Part C) come back
null in this project's actual current exports: BTC only has a 24h file, BNB only a
12h one (no shared timeframe at all), and GOLD/SILVER's 24h files, despite the shared
label, share zero real dates.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nero_core.data_sources.market_data import BINANCE_SYMBOLS
from nero_core.quant.quant_intelligence import build_garch_volatility_report, log_returns, rolling_correlation

MIN_OBSERVATIONS = 30  # Part A/C's own floor; Part D uses its own (60), per the task spec.
LEAD_LAG_MIN_OBSERVATIONS = 60
LEAD_LAG_LAGS = (1, 2, 3, 4)

# GARCH regime labels (VOL_STRESS/VOL_ELEVATED/VOL_COMPRESSED/VOL_NORMAL) ->
# this task's own frontend badge vocabulary (LOW/NORMAL/HIGH/EXTREME). A direct,
# documented 1:1 relabeling of quant_intelligence._classify_garch_regime's existing
# categories -- not a new classification.
REGIME_LABEL_MAP = {
    "VOL_COMPRESSED": "LOW",
    "VOL_NORMAL": "NORMAL",
    "VOL_ELEVATED": "HIGH",
    "VOL_STRESS": "EXTREME",
    "NO_DATA": "NO_DATA",
}


@dataclass(frozen=True)
class AssetSeries:
    asset: str
    timeframe: str
    filename: str
    closes: pd.Series  # indexed by integer Unix-second `time`, sorted ascending


def load_candle_series(candles_dir: Path) -> tuple[list[AssetSeries], list[dict[str, str]]]:
    """Best-effort loader: a corrupt/unparseable file is reported in the second
    return value and simply excluded from the first -- callers (the export script,
    and every Part A-D function here) never need their own separate try/except
    around a single file's shape, matching this project's fail-independent
    convention at the loading layer instead of scattering it everywhere."""
    series: list[AssetSeries] = []
    errors: list[dict[str, str]] = []
    if not candles_dir.exists():
        return series, [{"file": str(candles_dir), "message": "candles directory does not exist"}]

    for path in sorted(candles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            candles = data["candles"]
            times = [int(c["time"]) for c in candles]
            closes = [float(c["close"]) for c in candles]
            closes_series = pd.Series(closes, index=pd.Index(times, name="time")).sort_index()
            series.append(AssetSeries(asset=data["asset"], timeframe=data["timeframe"], filename=path.name, closes=closes_series))
        except Exception as exc:  # noqa: BLE001 - one corrupt file must never abort the others
            errors.append({"file": path.name, "message": f"{exc.__class__.__name__}: {exc}"})
    return series, errors


def _aligned_closes(a: AssetSeries, b: AssetSeries) -> pd.DataFrame:
    """Inner join on the shared `time` index -- see module docstring for why this,
    not positional alignment, is mandatory even within a single timeframe group."""
    return pd.concat([a.closes.rename("a"), b.closes.rename("b")], axis=1, join="inner").sort_index()


def _group_by_timeframe(series: list[AssetSeries]) -> dict[str, list[AssetSeries]]:
    groups: dict[str, list[AssetSeries]] = {}
    for s in series:
        groups.setdefault(s.timeframe, []).append(s)
    return groups


# --------------------------------------------------------------------------------
# Part A -- rolling correlation matrix
# --------------------------------------------------------------------------------


def rolling_correlation_matrix(
    candle_files_dir: Path,
    window: int = 30,
    periods_per_year_map: dict[str, int] | None = None,
) -> dict[str, object]:
    """One entry per pair of assets sharing a timeframe (see module docstring:
    "sharing a timeframe" is necessary but NOT sufficient -- a pair must also share
    real overlapping dates, checked here via an inner join, not assumed from the
    timeframe label alone). Reuses quant_intelligence.rolling_correlation directly
    (this function only builds the 2-column aligned returns frame it expects and
    reads its most recent value) rather than re-deriving the rolling-correlation
    math.

    `periods_per_year_map` is accepted for signature compatibility with a possible
    future per-timeframe annualized-context enrichment, but genuinely unused here --
    a correlation coefficient needs no annualization factor, and the output schema
    this task specifies has no periods_per_year field. Not silently dropped, just
    documented as a no-op.
    """
    del periods_per_year_map  # intentionally unused -- see docstring
    series, load_errors = load_candle_series(candle_files_dir)
    now = datetime.now(timezone.utc)
    pairs: list[dict[str, object]] = []

    for timeframe, group in _group_by_timeframe(series).items():
        for a, b in itertools.combinations(group, 2):
            aligned = _aligned_closes(a, b)
            returns = np.log(aligned / aligned.shift(1)).dropna()
            window_used = min(window, len(returns))
            correlation = None
            if window_used >= window:
                returns_df = returns.rename(columns={"a": "a", "b": "b"})
                series_corr = rolling_correlation(returns_df, "a", "b", window)
                latest = series_corr.iloc[-1] if len(series_corr) else float("nan")
                correlation = None if pd.isna(latest) else float(latest)
            pairs.append(
                {
                    "asset_a": a.asset,
                    "asset_b": b.asset,
                    "timeframe": timeframe,
                    "correlation": correlation,
                    "window_used": window_used,
                    "computed_at": now.isoformat(),
                }
            )

    return {"pairs": pairs, "load_errors": load_errors}


# --------------------------------------------------------------------------------
# Part B -- GARCH volatility regime
# --------------------------------------------------------------------------------


def volatility_regimes(candle_files_dir: Path) -> dict[str, object]:
    """Reuses quant_intelligence.build_garch_volatility_report unchanged (its own
    arch/EWMA fallback is exactly what this task asks for -- never skipped, never
    erroring when `arch` isn't installed). One entry per candle FILE, matching Day
    4's own per-(asset,timeframe) granularity, since GOLD/SILVER's two timeframes
    genuinely have different volatility profiles."""
    series, load_errors = load_candle_series(candle_files_dir)
    now = datetime.now(timezone.utc)
    entries: list[dict[str, object]] = []
    errors: list[dict[str, str]] = list(load_errors)

    for s in series:
        try:
            price_history = pd.DataFrame({"close": s.closes.to_numpy()})
            report = build_garch_volatility_report(price_history, s.asset)
        except Exception as exc:  # noqa: BLE001 - one asset's GARCH/EWMA failure must never abort the rest
            errors.append({"file": s.filename, "message": f"{exc.__class__.__name__}: {exc}"})
            continue
        entries.append(
            {
                "asset": s.asset,
                "timeframe": s.timeframe,
                "regime": REGIME_LABEL_MAP.get(report.regime, report.regime),
                "conditional_vol": report.conditional_vol,
                "vol_ratio": report.vol_ratio,
                "shock_score": report.shock_score,
                "model_used": report.model,
                "computed_at": now.isoformat(),
            }
        )

    return {"entries": entries, "load_errors": errors}


# --------------------------------------------------------------------------------
# Part C -- cointegration (selected pairs only)
# --------------------------------------------------------------------------------

# Economically-motivated pairs per this task's own spec, keyed by (asset, timeframe)
# on each side -- NOT assumed to all have real overlapping data; see this module's
# docstring for which of these actually come back null against real exports and why.
COINTEGRATION_PAIRS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("GOLD", "24h"), ("SILVER", "24h")),
    (("BTC", "12h"), ("BNB", "12h")),
    (("EUR/USD", "1week"), ("GBP/USD", "1week")),
    (("USD/JPY", "1week"), ("GBP/USD", "1week")),
)


def _find_series(series: list[AssetSeries], asset: str, timeframe: str) -> AssetSeries | None:
    for s in series:
        if s.asset == asset and s.timeframe == timeframe:
            return s
    return None


def _cointegration_note(cointegrated: bool, pvalue: float | None) -> str:
    if pvalue is None:
        return "Insufficient overlapping history to run the test -- descriptive statistic unavailable, not a signal either way."
    if cointegrated:
        return "Cointegrated at 95% confidence -- prices tend to move together over this window. Descriptive statistic, not a trading signal."
    return "Not cointegrated at 95% confidence over this window. Descriptive statistic, not a trading signal."


def cointegration_report(candle_files_dir: Path) -> dict[str, object]:
    """Engle-Granger test via statsmodels.tsa.stattools.coint directly (see module
    docstring for why this, not quant_intelligence.engle_granger_cointegration, is
    used here). A DESCRIPTIVE STATISTIC ONLY -- every note explicitly says so."""
    from statsmodels.tsa.stattools import coint

    series, load_errors = load_candle_series(candle_files_dir)
    now = datetime.now(timezone.utc)
    entries: list[dict[str, object]] = []
    errors: list[dict[str, str]] = list(load_errors)

    for (asset_a, tf_a), (asset_b, tf_b) in COINTEGRATION_PAIRS:
        a = _find_series(series, asset_a, tf_a)
        b = _find_series(series, asset_b, tf_b)
        label = f"{asset_a} {tf_a} / {asset_b} {tf_b}"
        if a is None or b is None:
            entries.append(
                {
                    "asset_a": asset_a, "asset_b": asset_b, "timeframe_a": tf_a, "timeframe_b": tf_b,
                    "pvalue": None, "cointegrated": None, "window_used": 0,
                    "note": "No candle file available for this exact (asset, timeframe) pair.",
                    "computed_at": now.isoformat(),
                }
            )
            continue

        aligned = _aligned_closes(a, b)
        window_used = len(aligned)
        pvalue: float | None = None
        cointegrated: bool | None = None
        if window_used < MIN_OBSERVATIONS:
            note = (
                f"Only {window_used} overlapping calendar dates between these two files (need >= {MIN_OBSERVATIONS}) -- "
                "despite sharing a timeframe label, they don't share a real calendar grid. Insufficient data, not a fabricated result."
                if window_used == 0
                else f"Only {window_used} overlapping observations (need >= {MIN_OBSERVATIONS})."
            )
        else:
            try:
                _stat, pvalue_raw, _crit = coint(aligned["a"].to_numpy(), aligned["b"].to_numpy())
                pvalue = float(pvalue_raw)
                cointegrated = bool(pvalue < 0.05)
                note = _cointegration_note(cointegrated, pvalue)
            except Exception as exc:  # noqa: BLE001 - one pair's test failure must never abort the rest
                errors.append({"file": label, "message": f"{exc.__class__.__name__}: {exc}"})
                note = "Cointegration test failed to run for this pair."

        entries.append(
            {
                "asset_a": asset_a, "asset_b": asset_b, "timeframe_a": tf_a, "timeframe_b": tf_b,
                "pvalue": pvalue, "cointegrated": cointegrated, "window_used": window_used,
                "note": note, "computed_at": now.isoformat(),
            }
        )

    return {"entries": entries, "load_errors": errors}


# --------------------------------------------------------------------------------
# Part D -- lead-lag (BTC as benchmark only)
# --------------------------------------------------------------------------------


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    """Same NaN-safe pattern as quant_intelligence._safe_corr (never re-derived,
    just inlined since that helper is private to its module)."""
    value = pd.to_numeric(left, errors="coerce").corr(pd.to_numeric(right, errors="coerce"))
    return 0.0 if pd.isna(value) else float(value)


def lead_lag_report(candle_files_dir: Path, benchmark_asset: str = "BTC") -> dict[str, object]:
    """"BTC as benchmark only" -- scoped to OTHER CRYPTO-CLASS assets only (per this
    task's own "For each crypto asset (BNB) vs BTC" framing), using
    nero_core.data_sources.market_data.BINANCE_SYMBOLS as the existing, canonical
    definition of "which assets are crypto" in this codebase, rather than a fresh
    hardcoded list. In this project's current candle exports that's just BNB (the
    only other crypto asset with its own candle file) -- stocks/forex/metals are
    correctly excluded even though they're technically "other assets."

    For each in-scope asset sharing a real (timestamp-overlapping) timeframe with
    `benchmark_asset`, cross-correlates the benchmark's return shifted back by 1-4
    periods against the asset's own return (a positive shift lag means "does the
    benchmark's move from `lag` periods ago line up with the asset's move now" --
    i.e. does the benchmark LEAD). Reports whichever of lags 1-4 has the highest
    absolute correlation. Null (with a clear reason) below LEAD_LAG_MIN_OBSERVATIONS
    overlapping returns, including the "no shared timeframe at all" case -- see
    module docstring: BTC (24h) and BNB (12h) currently share literally zero real
    dates, which is exactly the honest null result this produces, not a
    resampled/fabricated one.
    """
    series, load_errors = load_candle_series(candle_files_dir)
    now = datetime.now(timezone.utc)
    entries: list[dict[str, object]] = []

    crypto_assets = set(BINANCE_SYMBOLS)
    benchmark_candidates = [s for s in series if s.asset == benchmark_asset]
    others = [s for s in series if s.asset != benchmark_asset and s.asset in crypto_assets]

    for other in others:
        benchmark = next((b for b in benchmark_candidates if b.timeframe == other.timeframe), None)
        if benchmark is None:
            entries.append(
                {
                    "asset": other.asset, "benchmark": benchmark_asset, "timeframe": other.timeframe,
                    "best_lag": None, "correlation": None, "window_used": 0,
                    "note": f"No {benchmark_asset} candle file shares this asset's timeframe ({other.timeframe}).",
                    "computed_at": now.isoformat(),
                }
            )
            continue

        aligned = _aligned_closes(benchmark, other)
        returns = np.log(aligned / aligned.shift(1)).dropna()
        window_used = len(returns)
        if window_used < LEAD_LAG_MIN_OBSERVATIONS:
            entries.append(
                {
                    "asset": other.asset, "benchmark": benchmark_asset, "timeframe": other.timeframe,
                    "best_lag": None, "correlation": None, "window_used": window_used,
                    "note": f"Only {window_used} overlapping returns (need >= {LEAD_LAG_MIN_OBSERVATIONS}).",
                    "computed_at": now.isoformat(),
                }
            )
            continue

        best_lag = None
        best_corr = 0.0
        for lag in LEAD_LAG_LAGS:
            lagged_benchmark = returns["a"].shift(lag)
            pair = pd.concat([returns["b"], lagged_benchmark], axis=1).dropna()
            if pair.empty:
                continue
            corr = _safe_corr(pair.iloc[:, 0], pair.iloc[:, 1])
            if best_lag is None or abs(corr) > abs(best_corr):
                best_lag = lag
                best_corr = corr

        entries.append(
            {
                "asset": other.asset, "benchmark": benchmark_asset, "timeframe": other.timeframe,
                "best_lag": best_lag, "correlation": None if best_lag is None else best_corr,
                "window_used": window_used,
                "note": (
                    f"{benchmark_asset} leads {other.asset} by {best_lag} period(s), correlation {best_corr:.2f}."
                    if best_lag is not None
                    else "No lag produced a usable overlapping sample."
                ),
                "computed_at": now.isoformat(),
            }
        )

    return {"entries": entries, "load_errors": load_errors}
