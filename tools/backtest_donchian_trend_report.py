"""CLI: DONCHIAN_TREND (donchian-trend-v1.0.0) on GOLD 1week only — its sole scope, per
the pre-registered hypothesis — reporting full-period, chronological train (first 70%),
and test (last 30%) metrics, alongside the existing BREAKOUT_MOMENTUM gold-calibrated
1week numbers on the SAME fetched data for direct comparison. Purpose: if a completely
different trend method (no RSI, no MA, no ATR-multiple stop) is ALSO positive on GOLD
1week, the edge is more likely an asset property than an artifact of BREAKOUT_MOMENTUM's
specific rule set.

No synthetic/fabricated price data is ever used — if the fetch fails, this is reported
plainly, not silently substituted.

Usage:
    python tools/backtest_donchian_trend_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.donchian_trend import DEFAULT_PARAMETERS as DONCHIAN_PARAMETERS
from nero_core.strategies.donchian_trend import STRATEGY_VERSION as DONCHIAN_VERSION
from nero_core.strategies.donchian_trend import run_donchian_backtest
from tools.backtest_compare import VARIANT_SPECS, BacktestMetrics, compute_metrics, run_backtest
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20
ASSET = "GOLD"
TIMEFRAME = "1week"
COMPARISON_VARIANT_KEY = "breakout_momentum_gold_calibrated_1week"


def _metrics_cell(metrics: BacktestMetrics) -> dict[str, object]:
    return {
        "trades": metrics.sample_size,
        "win_rate": metrics.win_rate,
        "expectancy_r": metrics.expectancy_r,
        "profit_factor": metrics.profit_factor,
        "below_min_sample": metrics.sample_size < MIN_SAMPLE_SIZE,
    }


def run_report() -> dict[str, object]:
    client = MarketDataClient()
    candles, method = fetch_timeframe_candles(client, ASSET, TIMEFRAME)
    train, test = split_chronological(candles)

    donchian_full_trades, donchian_full_state = run_donchian_backtest(candles, DONCHIAN_PARAMETERS)
    donchian_train_trades, donchian_train_state = run_donchian_backtest(train, DONCHIAN_PARAMETERS)
    donchian_test_trades, donchian_test_state = run_donchian_backtest(test, DONCHIAN_PARAMETERS)

    donchian_label = f"DONCHIAN_TREND ({DONCHIAN_VERSION})"
    donchian_row = {
        "strategy": donchian_label,
        "full": _metrics_cell(compute_metrics(ASSET, donchian_label, donchian_full_state, donchian_full_trades)),
        "train": _metrics_cell(compute_metrics(ASSET, donchian_label, donchian_train_state, donchian_train_trades)),
        "test": _metrics_cell(compute_metrics(ASSET, donchian_label, donchian_test_state, donchian_test_trades)),
    }

    comparison_spec = VARIANT_SPECS[COMPARISON_VARIANT_KEY]
    comp_full_trades, comp_full_state = run_backtest(candles, comparison_spec)
    comp_train_trades, comp_train_state = run_backtest(train, comparison_spec)
    comp_test_trades, comp_test_state = run_backtest(test, comparison_spec)
    comparison_row = {
        "strategy": comparison_spec.label,
        "full": _metrics_cell(compute_metrics(ASSET, comparison_spec.label, comp_full_state, comp_full_trades)),
        "train": _metrics_cell(compute_metrics(ASSET, comparison_spec.label, comp_train_state, comp_train_trades)),
        "test": _metrics_cell(compute_metrics(ASSET, comparison_spec.label, comp_test_state, comp_test_trades)),
    }

    return {"method": method, "candle_count": len(candles), "rows": [donchian_row, comparison_row]}


def _fmt_cell(cell: dict[str, object]) -> str:
    pf = cell["profit_factor"]
    pf_display = f"{pf:.2f}" if pf == pf and abs(pf) != float("inf") else "n/a"
    flag = "*" if cell["below_min_sample"] else " "
    return f"{cell['trades']:>4} {cell['win_rate'] * 100:>5.1f}% {cell['expectancy_r']:>7.3f} {pf_display:>6}{flag}"


def format_report(report: dict[str, object]) -> str:
    lines: list[str] = [f"GOLD / 1week — {report['method']} — {report['candle_count']} candles", ""]
    group_header = f"{'':<52}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Strategy':<52}"
        f"{'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6} "
        f"  {'N':>4} {'Win%':>6} {'ExpR':>7} {'PF':>6}"
    )
    lines.append(group_header)
    lines.append(header)
    lines.append("-" * len(header))
    for row in report["rows"]:
        lines.append(f"{row['strategy']:<52}{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}")
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")

    donchian_row = report["rows"][0]
    qualifies = (
        donchian_row["train"]["trades"] >= MIN_SAMPLE_SIZE
        and donchian_row["test"]["trades"] >= MIN_SAMPLE_SIZE
        and donchian_row["train"]["expectancy_r"] > 0
        and donchian_row["test"]["expectancy_r"] > 0
    )
    lines.append("")
    lines.append(f"DONCHIAN_TREND positive in BOTH train and test with >= {MIN_SAMPLE_SIZE} trades each half: {qualifies}")
    return "\n".join(lines)


def main() -> None:
    try:
        report = run_report()
    except MarketDataUnavailableError as exc:
        print(f"GOLD / 1week: SKIPPED — {exc}")
        return
    print(format_report(report))


if __name__ == "__main__":
    main()
