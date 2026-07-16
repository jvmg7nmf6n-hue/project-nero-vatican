"""Shared timeframe-fetching logic for all backtest tools — the single source of truth
for "the standard timeframe set" used across strategy testing.

Standard set: 2h, 4h, 12h, 24h (daily), 1week. 30min and 15days/30days are retired from
the standard rotation (still fetchable ad hoc via MarketDataClient directly, but no
longer part of the default sweep/split tooling).

No synthetic/fabricated price data is ever used — if a fetch fails, callers get a
MarketDataUnavailableError with the accumulated reason, never a silent substitute.
"""
from __future__ import annotations

import pandas as pd

from nero_core.data_sources.market_data import CANDLE_COLUMNS, MarketDataClient, MarketDataUnavailableError

STANDARD_TIMEFRAMES = ["2h", "4h", "12h", "24h", "1week"]

# Timeframes fetched directly as native exchange candles. "24h" is deliberately absent
# here — it's native daily data, fetched via MarketDataClient.load_daily directly (see
# fetch_timeframe_candles), which already cascades Binance/Coinbase/Kraken/Twelve Data
# for daily candles without needing an interval string per source.
NATIVE_BINANCE_INTERVAL = {"2h": "2h", "4h": "4h", "12h": "12h", "1week": "1w"}
NATIVE_TWELVEDATA_INTERVAL = {"2h": "2h", "4h": "4h", "1week": "1week"}  # no native 12h on Twelve Data

# How many candles to request per native intraday timeframe — set well past any of these
# assets' actual listing history, so the real cap is "the exchange ran out of history,"
# not this request size.
NATIVE_INTERVAL_CANDLES = {"2h": 100_000, "4h": 50_000, "12h": 20_000, "1week": 2_000}
GOLD_HOURLY_FALLBACK_CANDLES = 50_000  # for GOLD's 12h, resampled from Twelve Data 1h
DAILY_LOOKBACK_DAYS = 8000  # ~21.9 years — comfortably exceeds any of these assets' history

ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR", "GOLD"]


def aggregate_n_consecutive_candles(source: pd.DataFrame, n: int) -> pd.DataFrame:
    """Build wider candles by grouping every N consecutive already-closed candles from
    `source` (sorted ascending) — index-based consecutive grouping, not calendar-boundary
    resampling. Only complete groups of exactly N candles are kept: a trailing partial
    group (fewer than N) would represent a still-forming wider candle and is dropped, so
    this never introduces lookahead."""
    if source.empty or len(source) < n:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    frame = source.sort_values("close_time").reset_index(drop=True)
    complete_groups = len(frame) // n
    frame = frame.iloc[: complete_groups * n].copy()
    frame["_group"] = frame.index // n
    grouped = frame.groupby("_group").agg(
        open_time=("open_time", "first"),
        close_time=("close_time", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    grouped["date"] = pd.to_datetime(grouped["close_time"], unit="ms", utc=True)
    return grouped[CANDLE_COLUMNS]


def fetch_timeframe_candles(client: MarketDataClient, asset: str, timeframe: str) -> tuple[pd.DataFrame, str]:
    """Returns (candles, method_description). Raises MarketDataUnavailableError if the
    underlying live fetch fails for every configured source."""
    if timeframe == "24h":
        result = client.load_daily(asset, days=DAILY_LOOKBACK_DAYS)
        return result.prices, f"NATIVE: {result.source}"

    if asset == "GOLD":
        td_interval = NATIVE_TWELVEDATA_INTERVAL.get(timeframe)
        if td_interval is not None:
            result = client.load_intraday(asset, interval=td_interval, candles=NATIVE_INTERVAL_CANDLES[timeframe])
            return result.prices, f"NATIVE: {result.source}"
        if timeframe == "12h":
            hourly = client.load_intraday(asset, interval="1h", candles=GOLD_HOURLY_FALLBACK_CANDLES)
            resampled = aggregate_n_consecutive_candles(hourly.prices, 12)
            return resampled, f"RESAMPLED: grouped 12 consecutive 1h candles from {hourly.source} (Twelve Data has no native 12h)"
        raise MarketDataUnavailableError(f"No fetch method configured for GOLD at timeframe {timeframe!r}.")

    result = client.load_intraday(asset, interval=NATIVE_BINANCE_INTERVAL[timeframe], candles=NATIVE_INTERVAL_CANDLES[timeframe])
    return result.prices, f"NATIVE: {result.source}"
