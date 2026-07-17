"""CLI: H4 hypothesis — head-to-head BREAKOUT_MOMENTUM v1.0.0 vs. its volume-confirmed
variant (breakout-momentum-v1.4.0-volume-confirmed: identical rules plus entry-candle
volume > 1.5x the average volume of the prior 20 candles, excluding the entry candle)
on IDENTICAL data. Crypto assets only (7 — GOLD volume from Twelve Data is unreliable),
all 5 standard timeframes. Question: does the volume filter improve per-trade
expectancy, or does it just cut trades without a quality gain? Reports BOTH trade
counts explicitly, plus expectancy/win-rate/profit-factor, full period + chronological
train(70%)/test(30%), with LOW SAMPLE flags.

No synthetic/fabricated price data is ever used — if a fetch fails, that combination is
reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_volume_confirmed_sweep.py
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, BacktestMetrics, compute_metrics, run_backtest
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import STANDARD_TIMEFRAMES, fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR"]
VARIANT_KEYS = ["breakout_momentum", "breakout_momentum_volume_confirmed"]


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
        "trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0,
        "below_min_sample": True, "skip_reason": reason,
    }


def _skip_row(asset: str, timeframe: str, strategy_label: str, reason: str) -> dict[str, object]:
    return {
        "asset": asset, "timeframe": timeframe, "strategy": strategy_label,
        "full": _empty_cell(reason), "train": _empty_cell(reason), "test": _empty_cell(reason),
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
                for key in VARIANT_KEYS:
                    rows.append(_skip_row(asset, timeframe, VARIANT_SPECS[key].label, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                for key in VARIANT_KEYS:
                    rows.append(_skip_row(asset, timeframe, VARIANT_SPECS[key].label, f"{exc.__class__.__name__}: {exc}"))
                continue

            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe}: {method} — {len(candles)} candles ({elapsed:.1f}s)")
            train, test = split_chronological(candles)

            for key in VARIANT_KEYS:
                base_spec = VARIANT_SPECS[key]
                spec = replace(base_spec, params=build_calibrated_params(base_spec.params, timeframe, asset))

                full_trades, full_state = run_backtest(candles, spec)
                train_trades, train_state = run_backtest(train, spec)
                test_trades, test_state = run_backtest(test, spec)

                rows.append(
                    {
                        "asset": asset,
                        "timeframe": timeframe,
                        "strategy": base_spec.label,
                        "full": _metrics_cell(compute_metrics(asset, base_spec.label, full_state, full_trades)),
                        "train": _metrics_cell(compute_metrics(asset, base_spec.label, train_state, train_trades)),
                        "test": _metrics_cell(compute_metrics(asset, base_spec.label, test_state, test_trades)),
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
    group_header = f"{'':<8}{'':<8}{'':<52}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Asset':<8}{'TF':<8}{'Strategy':<52}"
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
            lines.append(f"{row['asset']:<8}{row['timeframe']:<8}{row['strategy']:<52} SKIPPED — {skip_reason}")
            continue
        lines.append(
            f"{row['asset']:<8}{row['timeframe']:<8}{row['strategy']:<52}"
            f"{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def format_trade_count_comparison(rows: list[dict[str, object]]) -> str:
    """Explicitly answers 'does the filter just cut trades' — plain vs. volume-confirmed
    full-period trade counts, side by side, per asset/timeframe."""
    by_combo: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        if "skip_reason" in row["full"]:
            continue
        key = (row["asset"], row["timeframe"])
        by_combo.setdefault(key, {})[row["strategy"]] = row["full"]["trades"]

    plain_label = VARIANT_SPECS["breakout_momentum"].label
    confirmed_label = VARIANT_SPECS["breakout_momentum_volume_confirmed"].label

    lines: list[str] = ["", "Trade count: plain vs. volume-confirmed (full period):"]
    total_plain = 0
    total_confirmed = 0
    for (asset, timeframe), counts in by_combo.items():
        plain_n = counts.get(plain_label, 0)
        confirmed_n = counts.get(confirmed_label, 0)
        total_plain += plain_n
        total_confirmed += confirmed_n
        pct_kept = (confirmed_n / plain_n * 100.0) if plain_n else 0.0
        lines.append(f"  {asset:<6} {timeframe:<7} plain={plain_n:>5}  volume-confirmed={confirmed_n:>5}  ({pct_kept:.1f}% kept)")
    overall_pct = (total_confirmed / total_plain * 100.0) if total_plain else 0.0
    lines.append(f"  TOTAL: plain={total_plain}  volume-confirmed={total_confirmed}  ({overall_pct:.1f}% kept)")
    return "\n".join(lines)


def format_positive_both_halves_summary(qualifying: list[dict[str, object]]) -> str:
    lines: list[str] = ["", f"Configurations positive in BOTH train and test with >= {MIN_SAMPLE_SIZE} trades in each half:"]
    if not qualifying:
        lines.append("  None. No (asset, timeframe, strategy) combination in this sweep met that bar.")
        return "\n".join(lines)
    for row in qualifying:
        train, test = row["train"], row["test"]
        lines.append(
            f"  {row['asset']:<8} {row['timeframe']:<7} {row['strategy']:<52} "
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
    print(format_trade_count_comparison(rows))
    print(format_positive_both_halves_summary(find_positive_both_halves(rows)))


if __name__ == "__main__":
    main()
