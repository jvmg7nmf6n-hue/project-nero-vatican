"""Stock (US equities) OHLCV fetcher via yfinance — Comprehensive Asset Expansion,
Part A: Stocks, Tasks A1/A2. See docs/stock_data_calibration_audit.md for the full
empirical audit this module's design is based on.

SURVIVORSHIP-BIAS CAVEAT (permanent, cannot be fixed by an audit): yfinance only ever
returns data for a symbol's CURRENT ticker. Anything delisted, merged away, or
acquired simply has no path back into this fetcher — the "currently-listed liquid
stock universe" this module can reach is itself a survivor-selected sample, blind to
every company that failed. Every single-stock backtest result produced from this
module must be read with that caveat attached. SPY/QQQ/IWM (index ETFs, which by
construction always hold whatever is CURRENTLY in the index — constituent turnover
happens invisibly inside the fund, not as a visible "delisting" the ETF itself
suffers) are the bias-free reference set to compare single-stock results against.

TICKER RESOLUTION: a symbol that no longer resolves (delisted, or renamed away from —
e.g. Block Inc changed SQ to XYZ in January 2025; SQ now returns a genuinely empty
yfinance response, confirmed directly, not the old data under a stale symbol) raises
StockDataUnavailableError and must be logged + SKIPPED by the caller — never silently
redirected to a guessed successor ticker.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

CANDLE_COLUMNS = ["date", "open_time", "close_time", "open", "high", "low", "close", "volume"]

# Same rate-limit precedent as nero_core.data_sources.market_data._load_yfinance —
# yfinance/Yahoo throttles aggressively under repeated back-to-back requests.
YFINANCE_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)

# yfinance's native intervals for our standard stock timeframe set. "4h" has no native
# yfinance interval for equities — resampled here from 1h, market-hours aware (see
# resample_1h_to_4h_market_hours_aware).
YFINANCE_NATIVE_INTERVAL = {"1h": "1h", "1day": "1d", "1week": "1wk"}
YFINANCE_INTERVAL_MILLISECONDS = {"1h": 3_600_000, "1day": 86_400_000, "1week": 604_800_000}

RTH_SESSION_TIMEZONE = "America/New_York"


class StockDataUnavailableError(Exception):
    """Raised when yfinance returns no usable data for a symbol/timeframe — a ticker
    that fails to resolve (delisted, renamed, or never valid) raises this rather than
    ever being silently substituted with a different symbol."""


@dataclass(frozen=True)
class StockDataResult:
    prices: pd.DataFrame
    source: str
    symbol: str
    timeframe: str


def _drop_unclosed(frame: pd.DataFrame) -> pd.DataFrame:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return frame[frame["close_time"] < now_ms].copy()


def _fetch_yfinance_history(
    symbol: str, yf_interval: str, period: str | None = None, start=None, end=None, sleep_fn=time.sleep
) -> pd.DataFrame:
    history = None
    last_error: Exception | None = None
    for attempt, delay in enumerate((0.0,) + YFINANCE_RETRY_DELAYS_SECONDS):
        if delay:
            sleep_fn(delay)
        try:
            ticker = yf.Ticker(symbol)
            if period is not None:
                history = ticker.history(period=period, interval=yf_interval)
            else:
                history = ticker.history(start=start, end=end, interval=yf_interval)
        except Exception as exc:  # noqa: BLE001 - yfinance raises varied types; retry regardless
            last_error = exc
            history = None
        if history is not None and not history.empty:
            break

    if history is None or history.empty:
        reason = f": {last_error.__class__.__name__}: {last_error}" if last_error is not None else ""
        raise StockDataUnavailableError(
            f"{symbol!r} returned no data at interval={yf_interval!r} "
            f"(delisted, renamed, or never a valid ticker){reason}"
        )
    return history


def _normalize_frame(history: pd.DataFrame, interval_ms: int) -> pd.DataFrame:
    frame = history.reset_index()
    time_col = "Datetime" if "Datetime" in frame.columns else "Date"
    # Same .dt.as_unit("ms") pattern established for GOLD/SILVER/PLATINUM after the
    # pandas-resolution timestamp bug (see nero_core.data_sources.market_data) — a bare
    # .astype("int64") // 1_000_000 assumes nanosecond resolution, which is NOT
    # guaranteed across pandas versions.
    frame["open_time"] = pd.to_datetime(frame[time_col], utc=True).dt.as_unit("ms").astype("int64")
    frame["close_time"] = frame["open_time"] + interval_ms
    frame = frame.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    frame[["open", "high", "low", "close", "volume"]] = frame[["open", "high", "low", "close", "volume"]].astype(float)
    frame = _drop_unclosed(frame)
    frame = frame.sort_values("close_time").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    return frame[CANDLE_COLUMNS].reset_index(drop=True)


def resample_1h_to_4h_market_hours_aware(hourly: pd.DataFrame) -> pd.DataFrame:
    """Groups each trading day's OWN 1h candles into consecutive chunks of 4,
    RESET at every session boundary (a group never spans two different trading
    days). Confirmed empirically (docs/stock_data_calibration_audit.md): a ~6.5h RTH
    session yields exactly 7 hourly candles, so each day produces exactly one
    complete 4h bar plus a dropped ~2.5h/3-candle remainder — the same
    never-fabricate-an-incomplete-group convention as
    tools.timeframe_data.aggregate_n_consecutive_candles, just reset per session
    instead of globally (which would incorrectly straddle overnight/weekend gaps).
    Volume is summed across the 4 combined candles."""
    if hourly.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    frame = hourly.sort_values("close_time").reset_index(drop=True).copy()
    frame["_session_date"] = frame["date"].dt.tz_convert(RTH_SESSION_TIMEZONE).dt.date

    grouped_rows: list[dict[str, object]] = []
    for _session_date, day_frame in frame.groupby("_session_date", sort=True):
        day_frame = day_frame.reset_index(drop=True)
        complete_groups = len(day_frame) // 4
        for g in range(complete_groups):
            chunk = day_frame.iloc[g * 4 : (g + 1) * 4]
            grouped_rows.append(
                {
                    "open_time": int(chunk["open_time"].iloc[0]),
                    "close_time": int(chunk["close_time"].iloc[-1]),
                    "open": float(chunk["open"].iloc[0]),
                    "high": float(chunk["high"].max()),
                    "low": float(chunk["low"].min()),
                    "close": float(chunk["close"].iloc[-1]),
                    "volume": float(chunk["volume"].sum()),
                }
            )

    result = pd.DataFrame(grouped_rows)
    if result.empty:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    result["date"] = pd.to_datetime(result["close_time"], unit="ms", utc=True)
    return result[CANDLE_COLUMNS].reset_index(drop=True)


def fetch_stock_ohlcv(symbol: str, timeframe: str, start=None, end=None, sleep_fn=time.sleep) -> StockDataResult:
    """Returns a StockDataResult for one of the standard stock timeframes: 1h, 4h,
    1day, 1week. Raises StockDataUnavailableError if the symbol fails to resolve at
    all (see module docstring's TICKER RESOLUTION note) — never silently substitutes
    a different symbol. `start`/`end` (if given) are passed straight to yfinance;
    otherwise the full available history (period="max") is requested — yfinance
    itself enforces the real per-interval depth cap (e.g. ~730 days for 1h, confirmed
    directly — see the audit doc), so this module doesn't hardcode an assumed cap."""
    if timeframe == "4h":
        hourly = fetch_stock_ohlcv(symbol, "1h", start=start, end=end, sleep_fn=sleep_fn)
        resampled = resample_1h_to_4h_market_hours_aware(hourly.prices)
        return StockDataResult(
            prices=resampled,
            source=f"RESAMPLED: 4 consecutive 1h candles per session from {hourly.source}",
            symbol=symbol,
            timeframe=timeframe,
        )

    yf_interval = YFINANCE_NATIVE_INTERVAL.get(timeframe)
    if yf_interval is None:
        raise ValueError(f"unsupported stock timeframe: {timeframe!r}")

    if start is not None or end is not None:
        history = _fetch_yfinance_history(symbol, yf_interval, start=start, end=end, sleep_fn=sleep_fn)
    else:
        history = _fetch_yfinance_history(symbol, yf_interval, period="max", sleep_fn=sleep_fn)

    frame = _normalize_frame(history, YFINANCE_INTERVAL_MILLISECONDS[timeframe])
    return StockDataResult(prices=frame, source=f"NATIVE: yfinance {symbol} {yf_interval}", symbol=symbol, timeframe=timeframe)
