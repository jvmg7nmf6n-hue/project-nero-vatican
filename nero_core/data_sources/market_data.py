from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

# Scoped to the assets this session actually needs: BTC, Gold, SOL, ETH, BNB, XRP, DOGE, NEAR.
# Adding an asset later just means adding an entry to the relevant map(s) below.
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "NEAR": "NEARUSDT",
}

# Coinbase/Kraken fallbacks: only listed where that exchange genuinely trades the asset.
# BNB is Binance-native and isn't listed on Coinbase or Kraken, so it has no fallback path.
COINBASE_PRODUCTS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
    "NEAR": "NEAR-USD",
}

KRAKEN_PAIRS = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "XRP": "XRPUSD",
    "DOGE": "XDGUSD",
}

TWELVE_DATA_SYMBOLS = {
    "GOLD": "XAU/USD",
}

CANDLE_COLUMNS = ["date", "open_time", "close_time", "open", "high", "low", "close", "volume"]


class MarketDataUnavailableError(Exception):
    """Raised when no configured live data source could return usable candles.

    Carries every attempted source's failure reason. There is deliberately no fallback to
    generated/synthetic data — a failed fetch is always a clear error, never silent fake
    prices standing in for real ones.
    """


@dataclass(frozen=True)
class MarketDataResult:
    prices: pd.DataFrame
    source: str
    asset: str
    interval: str


class MarketDataClient:
    """Fetches real OHLCV candles from live exchange/data APIs, cascading across sources
    for redundancy (e.g. Binance -> Coinbase -> Kraken for crypto). Every returned candle
    is fully closed (close_time in the past) — no in-progress candle is ever included, so
    downstream strategy/backtest logic never sees a lookahead-biased partial bar.

    If every configured source for an asset fails, `MarketDataUnavailableError` is raised
    with the accumulated failure reasons. This client never substitutes fabricated data.
    """

    def __init__(self, timeout_seconds: int = 8) -> None:
        self.timeout_seconds = timeout_seconds

    def load_daily(
        self,
        asset: str,
        days: int = 365,
        twelve_data_api_key: str | None = None,
    ) -> MarketDataResult:
        asset = asset.upper()
        errors: list[str] = []

        if asset in BINANCE_SYMBOLS:
            try:
                prices = self._load_binance("1d", BINANCE_SYMBOLS[asset], interval="1d", limit=days)
                return MarketDataResult(prices, f"Binance {BINANCE_SYMBOLS[asset]} daily candles", asset, "1d")
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Binance: {exc.__class__.__name__}: {exc}")

        if asset in COINBASE_PRODUCTS:
            try:
                prices = self._load_coinbase(COINBASE_PRODUCTS[asset], granularity_seconds=86400, candles=days)
                return MarketDataResult(prices, f"Coinbase {COINBASE_PRODUCTS[asset]} daily candles", asset, "1d")
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Coinbase: {exc.__class__.__name__}: {exc}")

        if asset in KRAKEN_PAIRS:
            try:
                prices = self._load_kraken(KRAKEN_PAIRS[asset], interval_minutes=1440, candles=days)
                return MarketDataResult(prices, f"Kraken {KRAKEN_PAIRS[asset]} daily candles", asset, "1d")
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Kraken: {exc.__class__.__name__}: {exc}")

        if asset in TWELVE_DATA_SYMBOLS:
            api_key = (twelve_data_api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
            if not api_key:
                errors.append("Twelve Data: missing API key")
            else:
                try:
                    symbol = TWELVE_DATA_SYMBOLS[asset]
                    prices = self._load_twelve_data(symbol, interval="1day", outputsize=days, api_key=api_key)
                    return MarketDataResult(prices, f"Twelve Data {symbol} daily candles", asset, "1d")
                except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                    errors.append(f"Twelve Data: {exc.__class__.__name__}: {exc}")

        self._raise_unavailable(asset, errors)

    def load_intraday(
        self,
        asset: str,
        interval: str = "1h",
        candles: int = 240,
        twelve_data_api_key: str | None = None,
    ) -> MarketDataResult:
        asset = asset.upper()
        errors: list[str] = []

        if asset in BINANCE_SYMBOLS:
            try:
                prices = self._load_binance("intraday", BINANCE_SYMBOLS[asset], interval=interval, limit=candles)
                return MarketDataResult(prices, f"Binance {BINANCE_SYMBOLS[asset]} {interval} candles", asset, interval)
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Binance: {exc.__class__.__name__}: {exc}")

        if asset in COINBASE_PRODUCTS:
            try:
                prices = self._load_coinbase(
                    COINBASE_PRODUCTS[asset], granularity_seconds=_coinbase_granularity(interval), candles=candles
                )
                return MarketDataResult(prices, f"Coinbase {COINBASE_PRODUCTS[asset]} {interval} candles", asset, interval)
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Coinbase: {exc.__class__.__name__}: {exc}")

        if asset in KRAKEN_PAIRS:
            try:
                prices = self._load_kraken(
                    KRAKEN_PAIRS[asset], interval_minutes=_kraken_interval_minutes(interval), candles=candles
                )
                return MarketDataResult(prices, f"Kraken {KRAKEN_PAIRS[asset]} {interval} candles", asset, interval)
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                errors.append(f"Kraken: {exc.__class__.__name__}: {exc}")

        if asset in TWELVE_DATA_SYMBOLS:
            api_key = (twelve_data_api_key or os.getenv("TWELVE_DATA_API_KEY", "")).strip()
            if not api_key:
                errors.append("Twelve Data: missing API key")
            else:
                try:
                    symbol = TWELVE_DATA_SYMBOLS[asset]
                    prices = self._load_twelve_data(symbol, interval=interval, outputsize=candles, api_key=api_key)
                    return MarketDataResult(prices, f"Twelve Data {symbol} {interval} candles", asset, interval)
                except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                    errors.append(f"Twelve Data: {exc.__class__.__name__}: {exc}")

        self._raise_unavailable(asset, errors)

    def _raise_unavailable(self, asset: str, errors: list[str]):
        supported = sorted(set(BINANCE_SYMBOLS) | set(COINBASE_PRODUCTS) | set(KRAKEN_PAIRS) | set(TWELVE_DATA_SYMBOLS))
        if not errors:
            raise MarketDataUnavailableError(
                f"No data source configured for asset {asset!r}. Supported assets: {supported}."
            )
        raise MarketDataUnavailableError(f"All live data sources failed for {asset}: " + "; ".join(errors))

    # -- source fetchers ------------------------------------------------------------

    BINANCE_MAX_LIMIT = 1000
    BINANCE_MAX_PAGES = 30  # safety cap: 30 * 1000 = 30,000 candles, far beyond any request this client makes

    def _load_binance(self, _label: str, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        limit = max(30, limit)
        if limit <= self.BINANCE_MAX_LIMIT:
            frame = self._fetch_binance_page(symbol, interval, limit)
        else:
            frame = self._fetch_binance_paginated(symbol, interval, limit)
        if frame.empty:
            raise ValueError("empty Binance candle response")
        frame = _drop_unclosed(frame)
        frame = frame.sort_values("close_time").reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
        return frame[CANDLE_COLUMNS].reset_index(drop=True)

    def _fetch_binance_page(self, symbol: str, interval: str, limit: int, end_time_ms: int | None = None) -> pd.DataFrame:
        params = {"symbol": symbol, "interval": interval, "limit": min(limit, self.BINANCE_MAX_LIMIT)}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        response = requests.get("https://api.binance.com/api/v3/klines", params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume", "close_time"])
        frame = pd.DataFrame(
            payload,
            columns=[
                "open_time", "open", "high", "low", "close", "volume", "close_time",
                "quote_asset_volume", "number_of_trades", "taker_buy_base_volume",
                "taker_buy_quote_volume", "ignore",
            ],
        )
        frame[["open", "high", "low", "close", "volume"]] = frame[["open", "high", "low", "close", "volume"]].astype(float)
        frame["open_time"] = frame["open_time"].astype("int64")
        frame["close_time"] = frame["close_time"].astype("int64")
        return frame[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

    def _fetch_binance_paginated(self, symbol: str, interval: str, total_limit: int) -> pd.DataFrame:
        """Binance caps a single request at 1000 candles. To cover a longer window (e.g.
        6-12 months of 1h candles), page backward in time using `endTime`, stitching pages
        together — every page is still a genuine live response, nothing is interpolated or
        fabricated between pages."""
        frames: list[pd.DataFrame] = []
        remaining = total_limit
        end_time_ms: int | None = None
        for _ in range(self.BINANCE_MAX_PAGES):
            if remaining <= 0:
                break
            batch = min(remaining, self.BINANCE_MAX_LIMIT)
            page = self._fetch_binance_page(symbol, interval, batch, end_time_ms=end_time_ms)
            if page.empty:
                break
            frames.append(page)
            earliest_open = int(page["open_time"].min())
            end_time_ms = earliest_open - 1
            remaining -= len(page)
            if len(page) < batch:
                break  # exchange ran out of history for this symbol
        if not frames:
            return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume", "close_time"])
        combined = pd.concat(frames, ignore_index=True)
        return combined.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)

    def _load_coinbase(self, product_id: str, granularity_seconds: int, candles: int) -> pd.DataFrame:
        response = requests.get(
            f"https://api.exchange.coinbase.com/products/{product_id}/candles",
            params={"granularity": granularity_seconds},
            headers={"User-Agent": "Project-Vatican/1.0"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise ValueError("empty Coinbase candle response")
        frame = pd.DataFrame(payload, columns=["time", "low", "high", "open", "close", "volume"])
        frame[["open", "high", "low", "close", "volume"]] = frame[["open", "high", "low", "close", "volume"]].astype(float)
        frame["open_time"] = (frame["time"].astype("int64")) * 1000
        frame["close_time"] = frame["open_time"] + granularity_seconds * 1000
        frame = _drop_unclosed(frame)
        frame = frame.sort_values("close_time").tail(max(30, min(candles, 300))).reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
        return frame[CANDLE_COLUMNS].reset_index(drop=True)

    def _load_kraken(self, pair: str, interval_minutes: int, candles: int) -> pd.DataFrame:
        response = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": pair, "interval": interval_minutes},
            headers={"User-Agent": "Project-Vatican/1.0"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise ValueError(str(payload["error"]))
        result = payload["result"]
        series_key = next(key for key in result if key != "last")
        rows = result[series_key]
        if not rows:
            raise ValueError("empty Kraken candle response")
        frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
        frame[["open", "high", "low", "close", "volume"]] = frame[["open", "high", "low", "close", "volume"]].astype(float)
        frame["open_time"] = (frame["time"].astype("int64")) * 1000
        frame["close_time"] = frame["open_time"] + interval_minutes * 60 * 1000
        frame = _drop_unclosed(frame)
        frame = frame.sort_values("close_time").tail(max(30, min(candles, 720))).reset_index(drop=True)
        frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
        return frame[CANDLE_COLUMNS].reset_index(drop=True)

    def _load_twelve_data(self, symbol: str, interval: str, outputsize: int, api_key: str) -> pd.DataFrame:
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": symbol,
                "interval": interval,
                "outputsize": max(30, min(outputsize, 5000)),
                "apikey": api_key,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "error":
            raise ValueError(str(payload.get("message", "Twelve Data error")))
        values = payload.get("values")
        if not values:
            raise ValueError("empty Twelve Data response")
        frame = pd.DataFrame(values)
        frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].astype(float)
        if "volume" in frame.columns:
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
        else:
            # Some Twelve Data feeds (e.g. spot Gold XAU/USD) report no volume at all.
            frame["volume"] = 0.0
        frame["date"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.sort_values("date").reset_index(drop=True)
        interval_ms = _twelve_data_interval_milliseconds(interval)
        frame["close_time"] = (frame["date"].astype("int64") // 1_000_000)
        frame["open_time"] = frame["close_time"] - interval_ms
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        frame = frame[frame["close_time"] < now_ms].copy()
        return frame[CANDLE_COLUMNS].reset_index(drop=True)


def _drop_unclosed(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop any candle whose close_time has not yet passed — the exchange's most recent
    bar is often still forming. Keeping it would leak an in-progress price into strategy
    logic that assumes every input candle is fully closed."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return frame[frame["close_time"] < now_ms].copy()


def _coinbase_granularity(interval: str) -> int:
    return {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "6h": 21600, "1d": 86400}.get(interval, 3600)


def _kraken_interval_minutes(interval: str) -> int:
    return {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 60)


def _twelve_data_interval_milliseconds(interval: str) -> int:
    return {
        "1min": 60_000, "5min": 300_000, "15min": 900_000, "30min": 1_800_000,
        "1h": 3_600_000, "4h": 14_400_000, "1day": 86_400_000,
    }.get(interval, 86_400_000)
