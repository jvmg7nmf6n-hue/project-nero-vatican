"""Forex (FX) OHLCV fetcher via Twelve Data — Comprehensive Asset Expansion, Part B:
Forex, Tasks B1/B2. See docs/forex_data_calibration_audit.md for the full empirical
audit this module is based on.

Confirmed directly (unlike SILVER/PLATINUM's XAG/USD, XPT/USD 404s): all 10 standard
forex pairs resolve on the current Twelve Data plan, with NATIVE 1h/4h/1day/1week
intervals for every pair — no resampling needed anywhere in this module, unlike
stocks (session-aware 4h) or metals (yfinance-futures resampling).

DEPTH CAVEAT: a single request is capped at OUTPUTSIZE_CAP=5000 rows by this plan —
for 1h (forex trades ~24h/5 days a week), that's ~219 days per single call (confirmed
directly). Older intraday history DOES exist further back (confirmed via the
`end_date` pagination parameter), but this module does not paginate — a single-call
fetch, matching the same convention every other Twelve Data asset in this codebase
uses (GOLD included). Daily/weekly history is far deeper (EUR/USD 1day back to 2007,
confirmed directly) and is not capped by outputsize at the depths this project uses.

24/5 MARKET GAP: forex trades continuously Monday open to Friday close — the only
real gap is Friday close -> Sunday/Monday open. This module does not need to handle
that specially (Twelve Data simply never emits candles during the closed window,
identical in spirit to how yfinance never emits stock candles outside RTH) — but any
grid-shift verification run against this data must not cross that boundary (documented
in docs/forex_data_calibration_audit.md, not enforced in code here).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

from nero_core.config import load_dotenv

load_dotenv()  # populates os.environ from a repo-root .env if present; never overrides a real env var

CANDLE_COLUMNS = ["date", "open_time", "close_time", "open", "high", "low", "close", "volume"]

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "AUD/USD", "NZD/USD", "USD/CAD",
]

TWELVE_DATA_NATIVE_INTERVAL = {"1h": "1h", "4h": "4h", "1day": "1day", "1week": "1week"}
TWELVE_DATA_INTERVAL_MILLISECONDS = {
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1day": 86_400_000,
    "1week": 604_800_000,
}

OUTPUTSIZE_CAP = 5000  # Twelve Data's own per-request row cap on this plan

# Twelve Data's free plan rate-limits aggressively under back-to-back requests (observed
# directly while auditing — a request roughly every 8s avoided any 429s). Retried with
# backoff rather than treated as a permanent failure on the first hit.
RATE_LIMIT_RETRY_DELAYS_SECONDS = (10.0, 20.0, 30.0)


class ForexDataUnavailableError(Exception):
    """Raised when Twelve Data returns no usable data for a pair/timeframe after
    retries — never silently substituted with a different pair or fabricated data."""


@dataclass(frozen=True)
class ForexDataResult:
    prices: pd.DataFrame
    source: str
    pair: str
    timeframe: str


def fetch_forex_ohlcv(
    pair: str,
    timeframe: str,
    api_key: str | None = None,
    outputsize: int = OUTPUTSIZE_CAP,
    sleep_fn=time.sleep,
    timeout_seconds: float = 15.0,
) -> ForexDataResult:
    """Returns a ForexDataResult for one of the standard forex timeframes: 1h, 4h,
    1day, 1week — all native on Twelve Data, no resampling. Raises
    ForexDataUnavailableError if every retry is exhausted (rate-limited, pair doesn't
    resolve, or a transient network failure) rather than ever fabricating data."""
    interval = TWELVE_DATA_NATIVE_INTERVAL.get(timeframe)
    if interval is None:
        raise ValueError(f"unsupported forex timeframe: {timeframe!r}")

    key = (api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
    if not key:
        raise ForexDataUnavailableError("Twelve Data: missing API key")

    last_error: str | None = None
    for attempt, delay in enumerate((0.0,) + RATE_LIMIT_RETRY_DELAYS_SECONDS):
        if delay:
            sleep_fn(delay)
        try:
            response = requests.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": pair,
                    "interval": interval,
                    "outputsize": max(30, min(outputsize, OUTPUTSIZE_CAP)),
                    "apikey": key,
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            continue

        if payload.get("status") == "error":
            message = str(payload.get("message", "Twelve Data error"))
            last_error = message
            if "run out of API credits" in message.lower() or "429" in message:
                continue  # rate-limited — retry with backoff
            raise ForexDataUnavailableError(f"Twelve Data: {message}")

        values = payload.get("values")
        if not values:
            last_error = "empty Twelve Data response"
            continue

        frame = _normalize_frame(values, interval)
        return ForexDataResult(prices=frame, source=f"NATIVE: Twelve Data {pair} {interval}", pair=pair, timeframe=timeframe)

    raise ForexDataUnavailableError(
        f"{pair!r} at {timeframe!r}: exhausted all retries — last error: {last_error}"
    )


def _normalize_frame(values: list[dict], interval: str) -> pd.DataFrame:
    frame = pd.DataFrame(values)
    frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].astype(float)
    frame["volume"] = pd.to_numeric(frame.get("volume"), errors="coerce").fillna(0.0) if "volume" in frame.columns else 0.0
    frame["date"] = pd.to_datetime(frame["datetime"], utc=True)
    frame = frame.sort_values("date").reset_index(drop=True)
    interval_ms = TWELVE_DATA_INTERVAL_MILLISECONDS[interval]
    # Same .dt.as_unit("ms") pattern as market_data._load_twelve_data — see that
    # function's comment for the exact pandas-resolution bug this avoids.
    frame["close_time"] = frame["date"].dt.as_unit("ms").astype("int64")
    frame["open_time"] = frame["close_time"] - interval_ms
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    frame = frame[frame["close_time"] < now_ms].copy()
    return frame[CANDLE_COLUMNS].reset_index(drop=True)
