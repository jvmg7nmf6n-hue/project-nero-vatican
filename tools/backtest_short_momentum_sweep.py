"""CLI: run SHORT_MOMENTUM (short-momentum-v1.0.0) across the standard timeframe set
(2h, 4h, 12h, 24h, 1week), crypto assets only (7 — BTC, ETH, SOL, BNB, XRP, DOGE, NEAR;
GOLD excluded, this hypothesis is scoped to crypto), reporting full-period, train
(first 70%), and test (last 30%) metrics side by side with LOW SAMPLE flags.

SHORT_MOMENTUM has its own dedicated backtest loop (nero_core.strategies.
short_momentum.run_short_backtest) rather than going through the shared VariantSpec/
run_backtest pipeline — see that module's docstring for why (the shared run_backtest
hardcodes a long-only exit function). Timeframe-aware holding cap is applied per
timeframe via nero_core.strategies.timeframe_calibration.build_calibrated_params (no
GOLD fee branch ever fires here since GOLD is excluded).

No synthetic/fabricated price data is ever used — if a fetch fails, that combination is
reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_short_momentum_sweep.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.short_momentum import DEFAULT_PARAMETERS, STRATEGY_VERSION, run_short_backtest
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import BacktestMetrics, compute_metrics
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import STANDARD_TIMEFRAMES, fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR"]
STRATEGY_LABEL = f"SHORT_MOMENTUM ({STRATEGY_VERSION})"


def _metrics_cell(metrics: BacktestMetrics) -> dict[str, object]:
    return {
        "trades": metrics.sample_size,
        "win_rate": metrics.win_rate,
        "expectancy_r": metrics.expectancy_r,
        "profit_factor": metrics.profit_factor,
        "below_min_sample": metrics.sample_size < MIN_SAMPLE_SIZE,
    }


def _empty_cell(reason: str) -> dict[str, object]:
    return {
        "trades": 0,
        "win_rate": 0.0,
        "expectancy_r": 0.0,
        "profit_factor": 0.0,
        "below_min_sample": True,
        "skip_reason": reason,
    }


def _skip_row(asset: str, timeframe: str, reason: str) -> dict[str, object]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "strategy": STRATEGY_LABEL,
        "full": _empty_cell(reason),
        "train": _empty_cell(reason),
        "test": _empty_cell(reason),
    }


def run_sweep(assets: list[str], timeframes: list[str], client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for asset in assets:
        for timeframe in timeframes:
            start = time.monotonic()
            try:
                candles, method = fetch_timeframe_candles(client, asset, timeframe)
            except MarketDataUnavailableError as exc:
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
                rows.append(_skip_row(asset, timeframe, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                rows.append(_skip_row(asset, timeframe, f"{exc.__class__.__name__}: {exc}"))
                continue

            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe}: {method} — {len(candles)} candles ({elapsed:.1f}s)")
            train, test = split_chronological(candles)
            params = build_calibrated_params(DEFAULT_PARAMETERS, timeframe, asset)

            full_trades, full_state = run_short_backtest(candles, params)
            train_trades, train_state = run_short_backtest(train, params)
            test_trades, test_state = run_short_backtest(test, params)

            rows.append(
                {
                    "asset": asset,
                    "timeframe": timeframe,
                    "strategy": STRATEGY_LABEL,
                    "full": _metrics_cell(compute_metrics(asset, STRATEGY_LABEL, full_state, full_trades)),
                    "train": _metrics_cell(compute_metrics(asset, STRATEGY_LABEL, train_state, train_trades)),
                    "test": _metrics_cell(compute_metrics(asset, STRATEGY_LABEL, test_state, test_trades)),
                }
            )

    return rows


def find_positive_both_halves(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    qualifying: list[dict[str, object]] = []
    for row in rows:
        train, test = row["train"], row["test"]
        if "skip_reason" in train or "skip_reason" in test:
            continue
        if train["trades"] >= MIN_SAMPLE_SIZE and test["trades"] >= MIN_SAMPLE_SIZE and train["expectancy_r"] > 0 and test["expectancy_r"] > 0:
            qualifying.append(row)
    return qualifying


def _fmt_cell(cell: dict[str, object]) -> str:
    if "skip_reason" in cell:
        return f"{'SKIP':>4} {'':>6} {'':>7} {'':>6}"
    pf = cell["profit_factor"]
    pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
    flag = "*" if cell["below_min_sample"] else " "
    return f"{cell['trades']:>4} {cell['win_rate'] * 100:>5.1f}% {cell['expectancy_r']:>7.3f} {pf_display:>6}{flag}"


def format_consolidated_table(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    group_header = f"{'':<8}{'':<8}{'':<34}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Asset':<8}{'TF':<8}{'Strategy':<34}"
        f"{'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6}"
    )
    lines.append(group_header)
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        skip_reason = row["full"].get("skip_reason")
        if skip_reason is not None:
            lines.append(f"{row['asset']:<8}{row['timeframe']:<8}{row['strategy']:<34} SKIPPED — {skip_reason}")
            continue
        lines.append(
            f"{row['asset']:<8}{row['timeframe']:<8}{row['strategy']:<34}"
            f"{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def format_positive_both_halves_summary(qualifying: list[dict[str, object]]) -> str:
    lines: list[str] = ["", f"Configurations positive in BOTH train and test with >= {MIN_SAMPLE_SIZE} trades in each half:"]
    if not qualifying:
        lines.append("  None. No (asset, timeframe) combination in this sweep met that bar.")
        return "\n".join(lines)
    for row in qualifying:
        train, test = row["train"], row["test"]
        lines.append(
            f"  {row['asset']:<8} {row['timeframe']:<7} "
            f"train: N={train['trades']} ExpR={train['expectancy_r']:.3f} | "
            f"test: N={test['trades']} ExpR={test['expectancy_r']:.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=CRYPTO_ASSETS)
    parser.add_argument("--timeframes", nargs="+", default=STANDARD_TIMEFRAMES, choices=STANDARD_TIMEFRAMES)
    args = parser.parse_args()

    client = MarketDataClient()
    rows = run_sweep(args.assets, args.timeframes, client)

    print()
    print(format_consolidated_table(rows))
    print(format_positive_both_halves_summary(find_positive_both_halves(rows)))


if __name__ == "__main__":
    main()
