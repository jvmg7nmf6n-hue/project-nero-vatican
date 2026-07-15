"""CLI: verify a backtest result out-of-sample via a chronological train/test split.

Splits each asset's historical candles by DATE (first 70% = train, last 30% = test —
never shuffled/randomized), then runs each strategy on each half completely
independently: the test half gets its own indicator warmup from scratch, using none of
the train half's data. This is a strict split — no information crosses the boundary in
either direction.

Usage:
    python tools/backtest_train_test_split.py --assets BTC ETH BNB DOGE --timeframe 12h

No synthetic/fabricated price data is ever used — if a fetch fails, that asset is
reported as SKIPPED with the reason.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from tools.backtest_compare import MIN_SAMPLE_SIZE, VARIANT_SPECS, compute_metrics, run_backtest

DEFAULT_ASSETS = ["BTC", "ETH", "BNB", "DOGE"]
DEFAULT_STRATEGIES = ["mean_reversion_v1", "breakout_momentum"]
DEFAULT_TIMEFRAME_CANDLES = 20_000  # matches backtest_timeframe_sweep.py's 12h request size
TRAIN_FRACTION = 0.7


def split_chronological(candles: pd.DataFrame, train_fraction: float = TRAIN_FRACTION) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split candles by DATE order — first `train_fraction` of candles (earliest) go to
    train, the remaining most-recent candles go to test. Never shuffled."""
    if candles.empty:
        return candles, candles
    frame = candles.sort_values("close_time").reset_index(drop=True)
    split_index = int(len(frame) * train_fraction)
    train = frame.iloc[:split_index].reset_index(drop=True)
    test = frame.iloc[split_index:].reset_index(drop=True)
    return train, test


def run_split_backtest(asset: str, timeframe: str, client: MarketDataClient, strategy_keys: list[str] = DEFAULT_STRATEGIES) -> dict[str, object]:
    result = client.load_intraday(asset, interval=timeframe, candles=DEFAULT_TIMEFRAME_CANDLES)
    train, test = split_chronological(result.prices)

    rows: list[dict[str, object]] = []
    for half_name, half_candles in (("TRAIN", train), ("TEST", test)):
        date_range = (
            f"{half_candles['date'].min().date()} to {half_candles['date'].max().date()}"
            if not half_candles.empty
            else "n/a"
        )
        for strategy_key in strategy_keys:
            spec = VARIANT_SPECS[strategy_key]
            trades, state = run_backtest(half_candles, spec)
            metrics = compute_metrics(asset, spec.label, state, trades)
            rows.append(
                {
                    "asset": asset,
                    "split": half_name,
                    "date_range": date_range,
                    "candle_count": len(half_candles),
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
    return {"asset": asset, "source": result.source, "total_candles": len(result.prices), "rows": rows}


def format_train_test_table(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    header = (
        f"{'Asset':<6} {'Split':<6} {'DateRange':<24} {'Candles':>7} {'Strategy':<45} "
        f"{'Trades':>7} {'Win%':>7} {'ExpR':>8} {'PF':>8}  {'<20 FLAG':>9}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for result in results:
        for row in result["rows"]:
            pf = row["profit_factor"]
            pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
            flag = "*** LOW SAMPLE ***" if row["below_min_sample"] else ""
            lines.append(
                f"{row['asset']:<6} {row['split']:<6} {row['date_range']:<24} {row['candle_count']:>7} "
                f"{row['strategy']:<45} {row['trades']:>7} {row['win_rate'] * 100:>6.1f}% "
                f"{row['expectancy_r']:>8.3f} {pf_display:>8}  {flag:>9}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=DEFAULT_ASSETS)
    parser.add_argument("--timeframe", default="12h")
    parser.add_argument("--variants", nargs="+", default=DEFAULT_STRATEGIES, choices=list(VARIANT_SPECS))
    args = parser.parse_args()

    client = MarketDataClient()
    results: list[dict[str, object]] = []
    for asset in args.assets:
        try:
            result = run_split_backtest(asset, args.timeframe, client, args.variants)
            results.append(result)
            print(f"{asset}: OK — {result['source']} ({result['total_candles']} candles total)")
        except MarketDataUnavailableError as exc:
            print(f"{asset}: SKIPPED — {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"{asset}: FAILED — {exc.__class__.__name__}: {exc}")

    print()
    if results:
        print(format_train_test_table(results))
    else:
        print("No assets produced usable data — nothing to compare.")


if __name__ == "__main__":
    main()
