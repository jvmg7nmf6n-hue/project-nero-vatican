"""CLI: backtest MEAN_REVERSION v1 and BREAKOUT_MOMENTUM_V1 across the standard
timeframe set, over the same 8 assets, using the longest historical window each source
actually has.

Usage:
    python tools/backtest_timeframe_sweep.py

Standard timeframes: 2h, 4h, 12h, 24h (daily), 1week — fetched as native exchange
candles (Binance for crypto; Twelve Data for GOLD, except 12h which Twelve Data doesn't
offer natively, resampled from 1h instead). 24h is native daily data (MarketDataClient's
load_daily), not an intraday interval string.

No synthetic/fabricated price data is ever used — if a fetch fails for an asset/timeframe,
that combination is reported as SKIPPED with the reason, not silently substituted.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from tools.backtest_compare import VARIANT_SPECS, compute_metrics, run_backtest
from tools.timeframe_data import ASSETS, STANDARD_TIMEFRAMES, aggregate_n_consecutive_candles, fetch_timeframe_candles

STRATEGY_KEYS = ["mean_reversion_v1", "breakout_momentum"]

# Canonical timeframe order for the report.
TIMEFRAMES = STANDARD_TIMEFRAMES

MIN_SAMPLE_SIZE = 20


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=ASSETS)
    parser.add_argument("--timeframes", nargs="+", default=TIMEFRAMES, choices=TIMEFRAMES)
    parser.add_argument("--variants", nargs="+", default=STRATEGY_KEYS, choices=list(VARIANT_SPECS))
    args = parser.parse_args()

    client = MarketDataClient()
    rows: list[dict[str, object]] = []

    for asset in args.assets:
        for timeframe in args.timeframes:
            start = time.monotonic()
            try:
                candles, method = fetch_timeframe_candles(client, asset, timeframe)
            except MarketDataUnavailableError as exc:
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
                for strategy_key in args.variants:
                    rows.append(_skipped_row(asset, timeframe, strategy_key, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - one combo's failure must not lose the rest
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                for strategy_key in args.variants:
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

            for strategy_key in args.variants:
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
