"""CLI: LEADLAG_FOLLOW (leadlag-follow-v1.0.0) for the 7 (alt, timeframe, lag) pairs
that passed H5's Bonferroni-corrected Granger causality test
(tools/granger_leadlag_test.py) — this strategy exists ONLY because that test found
significant results; it is not run on any pair that didn't pass. Reports full-period,
chronological train(70%)/test(30%) metrics with LOW SAMPLE flags, plus the standard
positive-in-both-halves-with-adequate-sample filter.

No synthetic/fabricated price data is ever used — if a fetch fails, that pair is
reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_leadlag_follow_sweep.py
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.leadlag_follow import (
    DEFAULT_PARAMETERS,
    STRATEGY_VERSION,
    align_leadlag_candles,
    run_leadlag_backtest,
)
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import BacktestMetrics, compute_metrics
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
STRATEGY_LABEL = f"LEADLAG_FOLLOW ({STRATEGY_VERSION})"

# The 7 pairs H5 found significant under the Bonferroni-corrected threshold — see
# docs (or the H5 commit message) for the raw p-values this list is derived from.
SIGNIFICANT_PAIRS = [
    {"alt": "SOL", "timeframe": "12h", "lag": 5},
    {"alt": "BNB", "timeframe": "12h", "lag": 4},
    {"alt": "XRP", "timeframe": "12h", "lag": 3},
    {"alt": "DOGE", "timeframe": "12h", "lag": 3},
    {"alt": "NEAR", "timeframe": "12h", "lag": 5},
    {"alt": "BNB", "timeframe": "24h", "lag": 1},
    {"alt": "DOGE", "timeframe": "24h", "lag": 3},
]


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


def run_sweep(pairs: list[dict[str, object]], client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for pair in pairs:
        alt, timeframe, lag = pair["alt"], pair["timeframe"], pair["lag"]
        start = time.monotonic()
        try:
            btc_candles, btc_method = fetch_timeframe_candles(client, "BTC", timeframe)
            alt_candles, alt_method = fetch_timeframe_candles(client, alt, timeframe)
        except MarketDataUnavailableError as exc:
            print(f"BTC-{alt} / {timeframe} (lag={lag}): SKIPPED — {exc}")
            rows.append({"alt": alt, "timeframe": timeframe, "lag": lag, "full": _empty_cell(str(exc)), "train": _empty_cell(str(exc)), "test": _empty_cell(str(exc))})
            continue
        except Exception as exc:  # noqa: BLE001
            reason = f"{exc.__class__.__name__}: {exc}"
            print(f"BTC-{alt} / {timeframe} (lag={lag}): FAILED — {reason}")
            rows.append({"alt": alt, "timeframe": timeframe, "lag": lag, "full": _empty_cell(reason), "train": _empty_cell(reason), "test": _empty_cell(reason)})
            continue

        aligned = align_leadlag_candles(btc_candles, alt_candles, "BTC", alt)
        if aligned.empty:
            reason = f"no overlapping candles between BTC and {alt}"
            rows.append({"alt": alt, "timeframe": timeframe, "lag": lag, "full": _empty_cell(reason), "train": _empty_cell(reason), "test": _empty_cell(reason)})
            continue

        elapsed = time.monotonic() - start
        print(f"BTC-{alt} / {timeframe} (lag={lag}): {btc_method} + {alt_method} — {len(aligned)} aligned candles ({elapsed:.1f}s)")

        params = build_calibrated_params(replace(DEFAULT_PARAMETERS, lag=lag), timeframe, alt)
        train_raw, test_raw = split_chronological(aligned)

        full_trades, full_state = run_leadlag_backtest(aligned, params, "BTC", alt)
        train_trades, train_state = run_leadlag_backtest(train_raw, params, "BTC", alt)
        test_trades, test_state = run_leadlag_backtest(test_raw, params, "BTC", alt)

        label = f"BTC-{alt}"
        rows.append(
            {
                "alt": alt,
                "timeframe": timeframe,
                "lag": lag,
                "full": _metrics_cell(compute_metrics(label, STRATEGY_LABEL, full_state, full_trades)),
                "train": _metrics_cell(compute_metrics(label, STRATEGY_LABEL, train_state, train_trades)),
                "test": _metrics_cell(compute_metrics(label, STRATEGY_LABEL, test_state, test_trades)),
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
    group_header = f"{'':<8}{'':<8}{'':<6}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Pair':<8}{'TF':<8}{'Lag':<6}"
        f"{'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6}"
    )
    lines.append(group_header)
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        pair_label = f"BTC-{row['alt']}"
        skip_reason = row["full"].get("skip_reason")
        if skip_reason is not None:
            lines.append(f"{pair_label:<8}{row['timeframe']:<8}{row['lag']:<6} SKIPPED — {skip_reason}")
            continue
        lines.append(
            f"{pair_label:<8}{row['timeframe']:<8}{row['lag']:<6}"
            f"{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def format_positive_both_halves_summary(qualifying: list[dict[str, object]]) -> str:
    lines: list[str] = ["", f"Configurations positive in BOTH train and test with >= {MIN_SAMPLE_SIZE} trades in each half:"]
    if not qualifying:
        lines.append("  None. No pair in this sweep met that bar.")
        return "\n".join(lines)
    for row in qualifying:
        train, test = row["train"], row["test"]
        lines.append(
            f"  BTC-{row['alt']:<6} {row['timeframe']:<7} lag={row['lag']} "
            f"train: N={train['trades']} ExpR={train['expectancy_r']:.3f} | "
            f"test: N={test['trades']} ExpR={test['expectancy_r']:.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    client = MarketDataClient()
    rows = run_sweep(SIGNIFICANT_PAIRS, client)

    print()
    print(format_consolidated_table(rows))
    print(format_positive_both_halves_summary(find_positive_both_halves(rows)))


if __name__ == "__main__":
    main()
