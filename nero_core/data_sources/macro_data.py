"""Macro data sourcing for MACRO_RISK_ON: a dollar-strength proxy (market-quoted, zero
publication lag beyond the standard closed-candle rule) and the 10Y TIPS real yield
(FRED DFII10, which carries a genuine reporting lag on top of that).

PUBLICATION-LAG DESIGN (the reason this module exists separately from market_data.py):
- Dollar proxy: UUP/DXY/EUR-USD are market-quoted prices — the same day's close is
  public the moment the market closes, same as every other candle this codebase uses.
  A 1-business-day (t+1) execution buffer is still applied before a value is usable,
  matching the "act only on an already-closed candle" rule used everywhere else.
- DFII10: the Treasury publishes each business day's real yield on the NEXT business
  day (per Treasury/FRED publication practice), i.e. a genuine 1-day reporting lag on
  top of the market-quoted case. This module applies a 2-business-day (t+2) execution
  buffer for DFII10: the standard 1-day closed-candle buffer PLUS the extra day for
  the reporting lag itself.

ALIGNMENT RULE: both series live on a business-day index; BTC/GOLD candles are daily
but span all 7 days. Merging onto the candle grid is a strict FORWARD-fill (a
weekend/holiday candle sees the most recently published business day's value) — never
backward-filled or interpolated, which would leak a not-yet-published value backward
in time.

CHANGE COMPUTATION ORDER: the 20-day change is computed on each series' own native
business-day index FIRST (so the trailing window only ever sees real business-day
observations), THEN the lag buffer is applied (still on the native business-day
index, as an integer shift), and ONLY THEN is the result forward-filled onto the daily
candle grid. Computing the change directly on an already-forward-filled grid would let
duplicated weekend values distort the 20-observation window.

No synthetic/fabricated data is ever used — if a live fetch fails and no cache exists,
MacroDataUnavailableError is raised.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests

from nero_core.config import load_dotenv

load_dotenv()  # populates os.environ from a repo-root .env if present; never overrides a real env var

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "macro_cache"

FRED_SERIES_ID = "DFII10"

# Regime parameters — shared constants so the strategy and any diagnostic tooling stay
# in lockstep; not strategy-registry parameters themselves (those live in
# nero_core.strategies.macro_risk_on.MacroRiskOnParameters), but the LAG values here are
# a hard data-integrity property of each series' own publication practice, not a tunable
# strategy knob.
CHANGE_WINDOW_DAYS = 20
DOLLAR_LAG_BUSINESS_DAYS = 1
DFII10_LAG_BUSINESS_DAYS = 2


class MacroDataUnavailableError(Exception):
    """Raised when no configured source (live or cached) could return usable macro
    data. Never falls back to synthetic/fabricated values."""


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.csv"


def _read_cache(name: str) -> pd.Series | None:
    path = _cache_path(name)
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame.empty:
        return None
    return frame.set_index("date")["value"].sort_index()


def _write_cache(name: str, series: pd.Series) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame = series.rename("value").rename_axis("date").reset_index()
    frame.to_csv(_cache_path(name), index=False)


def _fetch_twelve_data_daily_series(symbol: str, api_key: str, outputsize: int = 5000, timeout: int = 8) -> pd.Series:
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": "1day", "outputsize": min(outputsize, 5000), "apikey": api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "error":
        raise ValueError(str(payload.get("message", "Twelve Data error")))
    values = payload.get("values")
    if not values:
        raise ValueError("empty Twelve Data response")
    frame = pd.DataFrame(values)
    frame["date"] = pd.to_datetime(frame["datetime"]).dt.normalize()
    frame["close"] = frame["close"].astype(float)
    return frame.set_index("date")["close"].sort_index()


def fetch_dollar_proxy_daily(api_key: str | None = None, use_cache: bool = True) -> tuple[pd.Series, str]:
    """Dollar-strength proxy where FALLING always means "dollar weakening", in every
    fallback branch:
      1. UUP (Invesco DB US Dollar Bullish Fund) — an ETF designed to move WITH dollar
         strength, so no inversion needed.
      2. DXY (US Dollar Index quote) — same natural direction as UUP.
      3. EUR/USD, INVERTED (1 / close) — EUR/USD itself RISES when the dollar weakens
         (more dollars needed per euro), the opposite of UUP/DXY's convention, so it is
         inverted via reciprocal (not negation, so the fallback stays a meaningful
         positive price-like series: USD per EUR) to preserve "falling = weakening"
         across every branch.
    """
    if use_cache:
        cached = _read_cache("dollar_proxy")
        if cached is not None:
            return cached, "CACHED: dollar proxy (source recorded at fetch time; see data/macro_cache/dollar_proxy.csv)"

    key = (api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
    if not key:
        raise MacroDataUnavailableError("Twelve Data: missing API key for dollar proxy")

    errors: list[str] = []
    for symbol, label, invert in (
        ("UUP", "Twelve Data UUP (Invesco DB US Dollar Bullish Fund) daily close", False),
        ("DXY", "Twelve Data DXY (US Dollar Index) daily close", False),
        ("EUR/USD", "Twelve Data EUR/USD daily close, INVERTED (1/close)", True),
    ):
        try:
            series = _fetch_twelve_data_daily_series(symbol, key)
            if invert:
                series = 1.0 / series
            _write_cache("dollar_proxy", series)
            return series, f"NATIVE: {label}"
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{symbol}: {exc.__class__.__name__}: {exc}")

    raise MacroDataUnavailableError("All dollar-proxy sources failed: " + "; ".join(errors))


def fetch_dfii10_daily(api_key: str | None = None, use_cache: bool = True) -> tuple[pd.Series, str]:
    """FRED DFII10 (10-Year Treasury Inflation-Indexed Security, Constant Maturity —
    the standard 10Y TIPS real yield series). Raises MacroDataUnavailableError before
    attempting anything if FRED_API_KEY is not set — this leg cannot proceed without
    it, and this module never substitutes a different series silently."""
    if use_cache:
        cached = _read_cache("dfii10")
        if cached is not None:
            return cached, "CACHED: FRED DFII10 (source recorded at fetch time; see data/macro_cache/dfii10.csv)"

    key = (api_key or os.getenv("FRED_API_KEY", "")).strip()
    if not key:
        raise MacroDataUnavailableError("FRED: missing API key (FRED_API_KEY) for DFII10 — cannot build the real-yield leg")

    response = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": FRED_SERIES_ID, "api_key": key, "file_type": "json"},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    observations = payload.get("observations")
    if not observations:
        raise MacroDataUnavailableError("FRED: empty DFII10 response")
    frame = pd.DataFrame(observations)
    frame = frame[frame["value"] != "."]  # FRED encodes a missing observation as "."
    if frame.empty:
        raise MacroDataUnavailableError("FRED: DFII10 response had no usable observations")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["value"] = frame["value"].astype(float)
    series = frame.set_index("date")["value"].sort_index()
    _write_cache("dfii10", series)
    return series, "NATIVE: FRED DFII10 (10Y TIPS real yield, api.stlouisfed.org)"


def compute_lagged_change(series: pd.Series, change_window_days: int, lag_business_days: int) -> pd.Series:
    """Compute the `change_window_days`-period change on `series`'s own native
    business-day index (value[d] - value[d - change_window_days]), THEN shift the
    result by `lag_business_days` — this represents "the most recent change value
    legitimately usable as of business day d is the one that was already true as of
    d - lag_business_days". Both operations stay on the native business-day index —
    never on a forward-filled calendar grid."""
    change = series.diff(change_window_days)
    return change.shift(lag_business_days)


def _tz_naive_normalized_dates(values) -> pd.Series:
    """Normalize a datetime-like column/index to tz-naive, midnight-truncated dates at
    a fixed (nanosecond) resolution — the common dtype both the candle grid's `date`
    column (often tz-aware, and not always the same underlying unit as a series built
    from plain date strings) and the macro series' plain business-day index need to
    share before merge_asof will accept them as comparable join keys."""
    parsed = pd.to_datetime(pd.Series(values))
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_localize(None)
    return parsed.dt.normalize().astype("datetime64[ns]")


def align_macro_to_daily_candles(candles: pd.DataFrame, macro_series: pd.Series, column_name: str) -> pd.DataFrame:
    """Forward-fill `macro_series` (already lag-shifted, still on its native
    business-day index) onto `candles`' calendar-day index. Uses merge_asof with
    direction="backward" — for each candle date, take the most recent macro-series
    date <= it. This is a strict forward-fill: a weekend/holiday candle sees the most
    recently published value, NEVER a future one; there is no backward-fill or
    interpolation path in this function at all."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    frame["_date_only"] = _tz_naive_normalized_dates(frame["date"]).values
    macro_frame = macro_series.rename(column_name).rename_axis("_macro_date").reset_index()
    macro_frame["_macro_date"] = _tz_naive_normalized_dates(macro_frame["_macro_date"]).values
    macro_frame = macro_frame.sort_values("_macro_date")
    merged = pd.merge_asof(
        frame.sort_values("_date_only"),
        macro_frame,
        left_on="_date_only",
        right_on="_macro_date",
        direction="backward",
    )
    return merged.drop(columns=["_macro_date", "_date_only"]).sort_values("close_time").reset_index(drop=True)


def build_regime_frame(candles: pd.DataFrame, dollar_series: pd.Series, dfii10_series: pd.Series) -> pd.DataFrame:
    """End-to-end: compute each leg's lagged 20-day change on its own native
    business-day index, forward-fill both onto `candles`, and derive the boolean
    `risk_on` regime column. `risk_on` is only meaningful where both change columns are
    non-NaN (see this module's docstring on warmup) — callers should dropna on
    `dollar_change_20d`/`dfii10_change_20d` before treating `risk_on` as decision-ready,
    exactly as nero_core.strategies.macro_risk_on does."""
    dollar_change = compute_lagged_change(dollar_series, CHANGE_WINDOW_DAYS, DOLLAR_LAG_BUSINESS_DAYS)
    dfii10_change = compute_lagged_change(dfii10_series, CHANGE_WINDOW_DAYS, DFII10_LAG_BUSINESS_DAYS)

    frame = align_macro_to_daily_candles(candles, dollar_change, "dollar_change_20d")
    frame = align_macro_to_daily_candles(frame, dfii10_change, "dfii10_change_20d")
    frame["risk_on"] = (frame["dollar_change_20d"] < 0) & (frame["dfii10_change_20d"] < 0)
    return frame
