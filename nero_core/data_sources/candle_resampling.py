"""Rebuild wider candles from finer native OHLCV data at an arbitrary UTC clock-time
offset, so shifting the candle "grid" (e.g. 12h candles closing at 03:00/15:00 UTC
instead of 00:00/12:00 UTC) can be tested as an independent variable from the strategy
itself — built for the H6 grid-shift robustness follow-up.

Only complete bins survive: a bin must contain exactly `target_hours` underlying 1h
candles spanning exactly `target_hours - 1` hours (no gap, no duplicate), so a
still-forming trailing bin, a partial leading bin at the start of history, or a bin
straddling missing source data never leaks into the output — this never introduces
lookahead and never fabricates a candle over missing data, matching the existing
tools.timeframe_data.aggregate_n_consecutive_candles "drop incomplete groups" contract,
just anchored to calendar time + offset instead of raw row count.
"""
from __future__ import annotations

import pandas as pd

from nero_core.data_sources.market_data import CANDLE_COLUMNS


def resample_hourly_to_grid(hourly: pd.DataFrame, target_hours: int, offset_hours: int) -> pd.DataFrame:
    """Resample already-closed native 1h candles into `target_hours`-wide candles whose
    bin edges are shifted by `offset_hours` from the UTC day boundary. offset_hours=0
    reproduces the standard grid (bins at 00:00, 12:00, ... UTC for target_hours=12);
    offset_hours=3 shifts every bin edge forward by 3 hours (03:00, 15:00, ... UTC).

    OHLCV aggregation: open = first candle's open, high = max high, low = min low,
    close = last candle's close, volume = SUM of all underlying candles' volume — the
    standard wider-candle-from-narrower-candles rule.
    """
    if hourly.empty or target_hours <= 0:
        return pd.DataFrame(columns=CANDLE_COLUMNS)

    frame = hourly.sort_values("close_time").reset_index(drop=True).copy()
    frame["open_dt"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame = frame.set_index("open_dt")

    grouper = pd.Grouper(freq=f"{target_hours}h", offset=f"{offset_hours % target_hours}h", label="left", closed="left")

    rows: list[dict[str, float | int]] = []
    for _bin_start, group in frame.groupby(grouper):
        if len(group) != target_hours:
            continue  # partial leading/trailing bin — a still-forming or incomplete candle, drop it
        span_hours = (group.index.max() - group.index.min()) / pd.Timedelta(hours=1)
        if span_hours != target_hours - 1:
            continue  # gap or duplicate inside the bin's source candles — don't fabricate a candle over missing data
        rows.append(
            {
                "open_time": int(group["open_time"].iloc[0]),
                "close_time": int(group["close_time"].iloc[-1]),
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "volume": float(group["volume"].sum()),
            }
        )

    if not rows:
        return pd.DataFrame(columns=CANDLE_COLUMNS)
    result = pd.DataFrame(rows)
    result["date"] = pd.to_datetime(result["close_time"], unit="ms", utc=True)
    return result[CANDLE_COLUMNS].reset_index(drop=True)
