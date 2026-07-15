"""CLI: backtest MEAN_REVERSION v1 and BREAKOUT_MOMENTUM_V1 across multiple timeframes,
over the same 8 assets, using the longest historical window each source actually has.

Usage:
    python tools/backtest_timeframe_sweep.py

Timeframes: 30min, 4h, 12h, 1week are fetched as native exchange candles (Binance for
crypto; Twelve Data for GOLD, except 12h which Twelve Data doesn't offer natively).
48h, 15days, and 30days are NOT standard exchange intervals — they are built by
resampling daily (1d) candles, grouping N consecutive already-closed daily candles into
one wider candle. A trailing partial group (fewer than N candles) is always dropped, so
no still-forming candle is ever included.

No synthetic/fabricated price data is ever used — if a fetch fails for an asset/timeframe,
that combination is reported as SKIPPED with the reason, not silently substituted.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import CANDLE_COLUMNS, MarketDataClient, MarketDataUnavailableError
from tools.backtest_compare import VARIANT_SPECS, compute_metrics, run_backtest

STRATEGY_KEYS = ["mean_reversion_v1", "breakout_momentum"]

# Canonical timeframe order for the report.
TIMEFRAMES = ["30min", "4h", "12h", "48h", "1week", "15days", "30days"]

# Timeframes fetched directly as native exchange candles.
NATIVE_BINANCE_INTERVAL = {"30min": "30m", "4h": "4h", "12h": "12h", "1week": "1w"}
NATIVE_TWELVEDATA_INTERVAL = {"30min": "30min", "4h": "4h", "1week": "1week"}  # no native 12h on Twelve Data

# How many candles to request per native timeframe — set well past any of these assets'
# actual listing history, so the real cap is "the exchange ran out of history", not this
# request size. (30m: ~14y at the pagination cap; 4h/12h/1week comfortably exceed any of
# these assets' full history.)
NATIVE_INTERVAL_CANDLES = {"30min": 200_000, "4h": 50_000, "12h": 20_000, "1week": 2_000}
GOLD_HOURLY_FALLBACK_CANDLES = 50_000  # for GOLD's 12h, resampled from Twelve Data 1h

# Timeframes NOT natively offered by any source here — built by resampling N consecutive
# daily candles into one wider candle.
DAILY_RESAMPLE_GROUPS = {"48h": 2, "15days": 15, "30days": 30}
DAILY_LOOKBACK_DAYS = 8000  # ~21.9 years — comfortably exceeds any of these assets' history

ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR", "GOLD"]

MIN_SAMPLE_SIZE = 20


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


def fetch_timeframe_candles(
    client: MarketDataClient,
    asset: str,
    timeframe: str,
    daily_cache: dict[str, tuple[pd.DataFrame, str]],
) -> tuple[pd.DataFrame, str]:
    """Returns (candles, method_description). Raises MarketDataUnavailableError if the
    underlying live fetch fails for every configured source."""
    if timeframe in DAILY_RESAMPLE_GROUPS:
        if asset not in daily_cache:
            daily_result = client.load_daily(asset, days=DAILY_LOOKBACK_DAYS)
            daily_cache[asset] = (daily_result.prices, daily_result.source)
        daily_prices, daily_source = daily_cache[asset]
        n = DAILY_RESAMPLE_GROUPS[timeframe]
        resampled = aggregate_n_consecutive_candles(daily_prices, n)
        return resampled, f"RESAMPLED: grouped {n} consecutive daily candles from {daily_source}"

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


def main() -> None:
    client = MarketDataClient()
    rows: list[dict[str, object]] = []
    daily_cache: dict[str, tuple[pd.DataFrame, str]] = {}

    for asset in ASSETS:
        for timeframe in TIMEFRAMES:
            start = time.monotonic()
            try:
                candles, method = fetch_timeframe_candles(client, asset, timeframe, daily_cache)
            except MarketDataUnavailableError as exc:
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
                for strategy_key in STRATEGY_KEYS:
                    rows.append(_skipped_row(asset, timeframe, strategy_key, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - one combo's failure must not lose the rest
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                for strategy_key in STRATEGY_KEYS:
                    rows.append(_skipped_row(asset, timeframe, strategy_key, f"{exc.__class__.__name__}: {exc}"))
                continue

            elapsed = time.monotonic() - start
            if candles.empty:
                window_desc = "0 candles"
                window_days = 0.0
            else:
                window_days = (candles["date"].max() - candles["date"].min()).total_seconds() / 86400.0
                window_desc = f"{len(candles)} candles / {window_days:.1f} days"
            print(f"{asset} / {timeframe}: {method} — {window_desc} ({elapsed:.1f}s)")

            for strategy_key in STRATEGY_KEYS:
                spec = VARIANT_SPECS[strategy_key]
                trades, state = run_backtest(candles, spec)
                metrics = compute_metrics(asset, spec.label, state, trades)
                rows.append(
                    {
                        "asset": asset,
                        "timeframe": timeframe,
                        "method": method,
                        "candle_count": len(candles),
                        "window_days": round(window_days, 1),
                        "strategy": spec.label,
                        "trades": metrics.sample_size,
                        "win_rate": metrics.win_rate,
                        "expectancy_r": metrics.expectancy_r,
                        "profit_factor": metrics.profit_factor,
                        "max_drawdown": metrics.max_drawdown,
                        "net_pnl": metrics.net_pnl,
                        "below_min_sample": metrics.sample_size < MIN_SAMPLE_SIZE,
                    }
                )

    print()
    print(format_sweep_table(rows))


def _skipped_row(asset: str, timeframe: str, strategy_key: str, reason: str) -> dict[str, object]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "method": f"SKIPPED: {reason}",
        "candle_count": 0,
        "window_days": 0.0,
        "strategy": VARIANT_SPECS[strategy_key].label,
        "trades": 0,
        "win_rate": 0.0,
        "expectancy_r": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "net_pnl": 0.0,
        "below_min_sample": True,
    }


def format_sweep_table(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    header = (
        f"{'Asset':<6} {'Timeframe':<9} {'Candles':>8} {'WindowDays':>11} {'Strategy':<45} "
        f"{'Trades':>7} {'Win%':>7} {'ExpR':>8} {'PF':>8} {'MaxDD':>8} {'NetPnL':>10}  {'<20 FLAG':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        pf = row["profit_factor"]
        pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
        flag = "*** LOW SAMPLE ***" if row["below_min_sample"] else ""
        lines.append(
            f"{row['asset']:<6} {row['timeframe']:<9} {row['candle_count']:>8} {row['window_days']:>11.1f} "
            f"{row['strategy']:<45} {row['trades']:>7} {row['win_rate'] * 100:>6.1f}% {row['expectancy_r']:>8.3f} "
            f"{pf_display:>8} {row['max_drawdown'] * 100:>7.1f}% {row['net_pnl']:>10.2f}  {flag:>9}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
