"""FRED policy-rate / short-term-yield sourcing for CARRY_MOMENTUM — Three New
Hypothesis Batch, Hypothesis 2 (Forex).

SERIES SELECTION — verified directly against the live FRED API (not assumed):
every candidate series ID was queried via /fred/series before being chosen. Three
currencies have a genuine DAILY central-bank/overnight-rate series; the other
five have NO daily series on FRED at all — confirmed by testing multiple
candidates per currency and rejecting every one that was stale (years out of
date) or missing, per the task's own "document any bond-yield substitutions"
instruction:

  USD: DFF     (Federal Funds Effective Rate, daily)
  EUR: ECBDFR  (ECB Deposit Facility Rate, daily)
  GBP: IUDSOIA (SONIA, daily)
  JPY: IR3TIB01JPM156N (OECD 3-month interbank rate, MONTHLY -- substitution;
       INTDSRJPM193N and IRSTCB01JPM156N were both tested and rejected as stale,
       last updated 2019 and 2024 respectively with no recent observations)
  CHF: IR3TIB01CHM156N (OECD 3-month interbank rate, MONTHLY -- substitution;
       no other CHF series found on FRED)
  AUD: IR3TIB01AUM156N (OECD 3-month interbank rate, MONTHLY -- substitution;
       IRSTCI01AUM156N also exists and is current, but the 3-month interbank
       series is used for consistency with JPY/CHF/NZD/CAD's own choice)
  NZD: IR3TIB01NZM156N (OECD 3-month interbank rate, MONTHLY -- substitution;
       IRSTCI01NZM156N was tested and rejected as stale, last updated 2025-01
       with no observations past 2024-12)
  CAD: IR3TIB01CAM156N (OECD 3-month interbank rate, MONTHLY -- substitution;
       IRSTCB01CAM156N was tested and rejected as stale, last updated 2024-01)

PUBLICATION LAG (same "compute change/level on the native index, THEN lag, THEN
forward-fill" discipline as nero_core.data_sources.macro_data, generalized here
to a genuine rate LEVEL rather than macro_data's own 20-day CHANGE):
  - Daily series (USD/EUR/GBP): DAILY_LAG_BUSINESS_DAYS = 2, matching macro_data's
    own DFII10_LAG_BUSINESS_DAYS precedent (t+1 closed-candle buffer + 1 extra day
    for real-world reporting lag).
  - Monthly series (JPY/CHF/AUD/NZD/CAD): empirically confirmed via `last_updated`
    vs `observation_end` on the live series metadata that these OECD interbank
    series lag by MORE than one month in practice -- JPY's worst-observed case
    was ~2.5 months (an observation dated 2026-05-01 was still the newest
    available as of a 2026-07-16 refresh). MONTHLY_LAG_DAYS = 90 is a
    deliberately conservative buffer (a full 3 calendar months past the
    observation date) that safely covers even that worst-observed case with
    margin, applied to each monthly observation's own timestamp before
    forward-filling onto the daily candle grid.

No synthetic/fabricated data — MacroDataUnavailableError (reused from
nero_core.data_sources.macro_data, the same class of failure) is raised if a
live fetch fails and no cache exists.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests

from nero_core.config import load_dotenv
from nero_core.data_sources.macro_data import MacroDataUnavailableError

load_dotenv()

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "macro_cache"

FRED_SERIES_BY_CURRENCY: dict[str, tuple[str, str]] = {
    "USD": ("DFF", "D"),
    "EUR": ("ECBDFR", "D"),
    "GBP": ("IUDSOIA", "D"),
    "JPY": ("IR3TIB01JPM156N", "M"),
    "CHF": ("IR3TIB01CHM156N", "M"),
    "AUD": ("IR3TIB01AUM156N", "M"),
    "NZD": ("IR3TIB01NZM156N", "M"),
    "CAD": ("IR3TIB01CAM156N", "M"),
}

DAILY_LAG_BUSINESS_DAYS = 2
MONTHLY_LAG_DAYS = 90


def _cache_path(currency: str) -> Path:
    return CACHE_DIR / f"fred_rate_{currency.lower()}.csv"


def _read_cache(currency: str) -> pd.Series | None:
    path = _cache_path(currency)
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame.empty:
        return None
    return frame.set_index("date")["value"].sort_index()


def _write_cache(currency: str, series: pd.Series) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame = series.rename("value").rename_axis("date").reset_index()
    frame.to_csv(_cache_path(currency), index=False)


def fetch_policy_rate(currency: str, api_key: str | None = None, use_cache: bool = True) -> tuple[pd.Series, str, str]:
    """Returns (series, source_label, frequency) where frequency is "D" or "M".
    Raises MacroDataUnavailableError (never fabricates) if FRED_API_KEY is
    missing or the live fetch fails and no cache exists. Raises KeyError for a
    currency not in FRED_SERIES_BY_CURRENCY -- never silently substitutes a
    different currency's series."""
    series_id, frequency = FRED_SERIES_BY_CURRENCY[currency]

    if use_cache:
        cached = _read_cache(currency)
        if cached is not None:
            return cached, f"CACHED: FRED {series_id} (source recorded at fetch time)", frequency

    key = (api_key or os.getenv("FRED_API_KEY", "")).strip()
    if not key:
        raise MacroDataUnavailableError(f"FRED: missing API key (FRED_API_KEY) for {currency} ({series_id})")

    response = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": key, "file_type": "json"},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    observations = payload.get("observations")
    if not observations:
        raise MacroDataUnavailableError(f"FRED: empty response for {currency} ({series_id})")
    frame = pd.DataFrame(observations)
    frame = frame[frame["value"] != "."]  # FRED encodes a missing observation as "."
    if frame.empty:
        raise MacroDataUnavailableError(f"FRED: no usable observations for {currency} ({series_id})")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["value"] = frame["value"].astype(float)
    series = frame.set_index("date")["value"].sort_index()
    _write_cache(currency, series)
    return series, f"NATIVE: FRED {series_id}", frequency


def lagged_usable_rate(series: pd.Series, frequency: str) -> pd.Series:
    """Shifts `series` (on its own native index) forward in time by the
    appropriate publication-lag buffer for its frequency, so the returned series
    only ever reports a rate value as of the date it was ACTUALLY usable, never
    the date it describes. Daily series: DAILY_LAG_BUSINESS_DAYS integer shift on
    the native business-day index (matches macro_data.compute_lagged_change's own
    convention). Monthly series: MONTHLY_LAG_DAYS calendar-day shift on the
    native monthly index's own timestamps (each observation's own date + 90 days
    becomes its usable-from date) -- these two are genuinely different
    operations (integer position shift vs calendar-day timestamp shift) because
    a monthly series' own index isn't evenly spaced in business days the way a
    daily series' is."""
    if frequency == "D":
        return series.shift(DAILY_LAG_BUSINESS_DAYS)
    if frequency == "M":
        shifted = series.copy()
        shifted.index = shifted.index + pd.Timedelta(days=MONTHLY_LAG_DAYS)
        return shifted
    raise ValueError(f"unrecognized frequency: {frequency!r}")


def align_rate_to_daily_candles(candles: pd.DataFrame, lagged_rate: pd.Series, column_name: str) -> pd.DataFrame:
    """Forward-fill `lagged_rate` (already lag-shifted, still on its own native
    index) onto `candles`' calendar-day index via merge_asof(direction="backward")
    -- a strict forward-fill, exactly matching
    nero_core.data_sources.macro_data.align_macro_to_daily_candles's own
    convention (reused here rather than re-derived, since the alignment rule
    doesn't depend on which macro series is being aligned)."""
    frame = candles.copy().sort_values("close_time").reset_index(drop=True)
    # Explicit datetime64[ns] cast on BOTH sides -- merge_asof requires identical
    # datetime resolutions, and `date` columns arriving from different upstream
    # sources (ms vs us precision) otherwise raise a MergeError, matching the same
    # fix nero_core.data_sources.macro_data._tz_naive_normalized_dates already
    # applies for its own candle/macro-series alignment.
    frame["_date_only"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    rate_frame = lagged_rate.rename(column_name).rename_axis("_rate_date").reset_index()
    rate_frame["_rate_date"] = pd.to_datetime(rate_frame["_rate_date"]).dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")
    rate_frame = rate_frame.sort_values("_rate_date")
    merged = pd.merge_asof(
        frame.sort_values("_date_only"), rate_frame, left_on="_date_only", right_on="_rate_date", direction="backward",
    )
    return merged.drop(columns=["_rate_date", "_date_only"]).sort_values("close_time").reset_index(drop=True)
