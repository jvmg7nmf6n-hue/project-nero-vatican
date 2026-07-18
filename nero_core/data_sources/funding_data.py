"""Historical Binance USDT-perp funding rate data — no API key needed (public
endpoint: fapi/v1/fundingRate).

Binance settles perpetual futures funding every 8 hours, exactly at 00:00, 08:00, and
16:00 UTC. This endpoint returns only ALREADY-SETTLED funding events — each stamped
with its own `fundingTime`, the exact UTC settlement timestamp this module stores
verbatim (as `settlement_time`, epoch ms) rather than deriving or rounding it. There is
no "predicted/pending funding" leakage path here: the live predicted rate for the
current, not-yet-settled period lives on a completely different endpoint
(premiumIndex), which this module deliberately never calls.

Caching follows the same convention as nero_core.data_sources.macro_data: a CSV cache
per asset under data/funding_cache/, checked first when use_cache=True, written after
every successful live fetch. No synthetic/fabricated funding data is ever used — if a
live fetch fails and no cache exists, FundingDataUnavailableError is raised.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from nero_core.data_sources.market_data import BINANCE_SYMBOLS

FUNDING_ASSETS = ["BTC", "ETH", "SOL", "BNB"]
FUNDING_SETTLEMENT_HOURS_UTC = (0, 8, 16)

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_FUNDING_MAX_LIMIT = 1000
# 200 * 1000 = 200,000 settlements at the 8h cadence = ~182 years — comfortably past any
# of these perpetuals' listing history, so "full available history" is bounded by the
# exchange running out of data (the early-stop below), not by this page cap.
BINANCE_FUNDING_MAX_PAGES = 200

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "funding_cache"

FUNDING_COLUMNS = ["settlement_time", "settlement_date", "funding_rate"]


class FundingDataUnavailableError(Exception):
    """Raised when no configured source (live or cached) could return usable funding
    data. Never falls back to synthetic/fabricated values."""


@dataclass(frozen=True)
class FundingHistoryResult:
    asset: str
    settlements: pd.DataFrame  # FUNDING_COLUMNS, sorted ascending by settlement_time
    source: str
    from_cache: bool


def _cache_path(asset: str, cache_dir: Path) -> Path:
    return cache_dir / f"{asset}_funding.csv"


def _read_cache(asset: str, cache_dir: Path) -> pd.DataFrame | None:
    path = _cache_path(asset, cache_dir)
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    if frame.empty:
        return None
    # format="ISO8601" (not a single inferred strptime format): the round-tripped CSV
    # column has variable fractional-second precision row to row (pandas trims trailing
    # zero microseconds when writing), which a single fixed-format parse rejects outright.
    frame["settlement_date"] = pd.to_datetime(frame["settlement_date"], utc=True, format="ISO8601")
    return frame[FUNDING_COLUMNS].sort_values("settlement_time").reset_index(drop=True)


def _write_cache(asset: str, frame: pd.DataFrame, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frame[FUNDING_COLUMNS].to_csv(_cache_path(asset, cache_dir), index=False)


def _fetch_funding_page(symbol: str, start_time_ms: int, limit: int, timeout_seconds: int) -> list[dict]:
    # `startTime` is ALWAYS sent explicitly — verified empirically that omitting it (or
    # sending 0) makes this endpoint return only its most-recent ~500-record window
    # instead of full history, while a genuine early timestamp (even one predating a
    # symbol's actual listing) correctly returns from that symbol's real earliest
    # record forward. There is no "leave it unset for full history" path here.
    params: dict[str, object] = {"symbol": symbol, "limit": limit, "startTime": start_time_ms}
    response = requests.get(BINANCE_FUNDING_URL, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise FundingDataUnavailableError(f"Unexpected funding rate response for {symbol}: {payload!r}")
    return payload


# A safely-early explicit startTime — predates every USDT-M perpetual this module
# supports (all listed well after this date) — used as the pagination floor so the
# first page genuinely returns each symbol's earliest available settlement, not
# Binance's most-recent-window default (see _fetch_funding_page's comment).
FUNDING_HISTORY_GENESIS_MS = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _fetch_full_funding_history(symbol: str, timeout_seconds: int = 8) -> pd.DataFrame:
    """Forward-paginate from FUNDING_HISTORY_GENESIS_MS (effectively "the earliest
    available settlement" for any symbol this module supports) to the most recent,
    stopping as soon as a page returns fewer than the request limit (the exchange has
    no more history) — every page is a genuine live response, nothing is interpolated
    between pages."""
    pages: list[list[dict]] = []
    start_time_ms: int = FUNDING_HISTORY_GENESIS_MS
    for page_index in range(BINANCE_FUNDING_MAX_PAGES):
        if page_index > 0:
            time.sleep(0.15)  # stay well under Binance's rate limit across a long paginated fetch
        try:
            page = _fetch_funding_page(symbol, start_time_ms, BINANCE_FUNDING_MAX_LIMIT, timeout_seconds)
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise FundingDataUnavailableError(
                f"Binance funding rate fetch failed for {symbol}: {exc.__class__.__name__}: {exc}"
            ) from exc
        if not page:
            break
        pages.append(page)
        start_time_ms = int(page[-1]["fundingTime"]) + 1
        if len(page) < BINANCE_FUNDING_MAX_LIMIT:
            break

    if not pages:
        raise FundingDataUnavailableError(f"empty funding rate response for {symbol}")

    rows = [item for page in pages for item in page]
    frame = pd.DataFrame(rows)
    frame["settlement_time"] = frame["fundingTime"].astype("int64")
    frame["funding_rate"] = frame["fundingRate"].astype(float)
    frame = frame.drop_duplicates(subset=["settlement_time"]).sort_values("settlement_time").reset_index(drop=True)

    # Defensive, belt-and-suspenders filter — the fundingRate endpoint only ever reports
    # already-settled events by its own semantics, but this mirrors market_data.py's
    # _drop_unclosed convention explicitly rather than relying solely on that assumption.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    frame = frame[frame["settlement_time"] < now_ms].reset_index(drop=True)

    frame["settlement_date"] = pd.to_datetime(frame["settlement_time"], unit="ms", utc=True)
    return frame[FUNDING_COLUMNS]


def load_funding_history(
    asset: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    timeout_seconds: int = 8,
) -> FundingHistoryResult:
    """Load an asset's full available settled-funding history. Checks the on-disk cache
    first when use_cache=True; on a cache miss (or use_cache=False), fetches live from
    Binance and writes the cache for next time. Raises FundingDataUnavailableError if
    `asset` isn't one of FUNDING_ASSETS, or if a live fetch is needed and fails."""
    asset = asset.upper()
    if asset not in FUNDING_ASSETS:
        raise FundingDataUnavailableError(f"Unsupported asset for funding data: {asset!r}. Supported: {FUNDING_ASSETS}.")
    symbol = BINANCE_SYMBOLS[asset]
    source_label = f"Binance {symbol} funding rate (fapi/v1/fundingRate)"

    if use_cache:
        cached = _read_cache(asset, cache_dir)
        if cached is not None:
            return FundingHistoryResult(asset=asset, settlements=cached, source=f"CACHED: {source_label}", from_cache=True)

    frame = _fetch_full_funding_history(symbol, timeout_seconds)
    _write_cache(asset, frame, cache_dir)
    return FundingHistoryResult(asset=asset, settlements=frame, source=f"NATIVE: {source_label}", from_cache=False)


def history_depth_report(asset: str, settlements: pd.DataFrame) -> str:
    """One-line summary of how much settled funding history is available for `asset` —
    used by tools/funding_history_depth_report.py to report depth per asset factually,
    not just fetch it silently."""
    if settlements.empty:
        return f"{asset}: 0 settlements (no funding history available)"
    first = settlements["settlement_date"].iloc[0]
    last = settlements["settlement_date"].iloc[-1]
    span_days = (last - first).total_seconds() / 86400.0
    return f"{asset}: {len(settlements)} settlements, {first.date()} to {last.date()} (~{span_days:.0f} days)"
