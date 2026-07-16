"""CLI: run every remaining price-data-based strategy (TREND_PULLBACK, the three ported
NERO mean-reversion variants, and COINTEGRATION_PAIRS) through the standard timeframe set
(2h, 4h, 12h, 24h, 1week), reporting FULL-period, chronological TRAIN (first 70%), and
TEST (last 30%) metrics side by side, plus a summary of configurations that were positive
in BOTH halves with an adequate sample.

TREND_PULLBACK and the three MR ports run across all 8 standard assets, exactly like
VOLATILITY_SQUEEZE's sweep (see backtest_volatility_squeeze_sweep.py) — timeframe-aware
holding caps and GOLD fee calibration are applied per (asset, timeframe) via
nero_core.strategies.timeframe_calibration.build_calibrated_params. The three MR ports are
NOT GOLD fee-calibrated beyond that shared holding-cap correction — see each module's own
docstring; they were ported as-is from the original NERO candidates and this sweep may
reproduce the same GOLD fee mismatch documented for the original MEAN_REVERSION v1.0.0.

COINTEGRATION_PAIRS only applies to the single BTC-ETH pair (its whole premise), so it
contributes one row per timeframe, not one per asset. It uses a fixed 200-candle window
regardless of timeframe (per its spec) — timeframes with too little shared history for a
200-candle rolling window to warm up (most visibly 1week) will show few or zero trades
honestly, not a fabricated result.

No synthetic/fabricated price data is ever used — if a fetch fails, that combination is
reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/backtest_remaining_strategies_sweep.py
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import PAIR as PAIRS_ASSET_PAIR
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles, run_pairs_backtest
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, BacktestMetrics, VariantSpec, compute_metrics, run_backtest
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import ASSETS, STANDARD_TIMEFRAMES, fetch_timeframe_candles

MIN_SAMPLE_SIZE = 20

SINGLE_ASSET_VARIANT_KEYS = [
    "trend_pullback",
    "mean_reversion_relaxed_pullback",
    "mean_reversion_deep_value",
    "mean_reversion_target_1r",
    "mean_reversion_regime_filter",
]

PAIRS_ASSET_LABEL = "-".join(PAIRS_ASSET_PAIR)  # "BTC-ETH"
PAIRS_STRATEGY_LABEL = "COINTEGRATION_PAIRS (cointegration-pairs-v1.0.0)"


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


def _skip_row(asset_label: str, timeframe: str, strategy_label: str, reason: str) -> dict[str, object]:
    return {
        "asset": asset_label,
        "timeframe": timeframe,
        "strategy": strategy_label,
        "full": _empty_cell(reason),
        "train": _empty_cell(reason),
        "test": _empty_cell(reason),
    }


def _calibrated_spec(base_spec: VariantSpec, timeframe: str, asset: str) -> VariantSpec:
    return replace(base_spec, params=build_calibrated_params(base_spec.params, timeframe, asset))


def run_single_asset_rows(
    assets: list[str],
    timeframes: list[str],
    client: MarketDataClient,
    variant_keys: list[str] = SINGLE_ASSET_VARIANT_KEYS,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for asset in assets:
        for timeframe in timeframes:
            start = time.monotonic()
            try:
                candles, method = fetch_timeframe_candles(client, asset, timeframe)
            except MarketDataUnavailableError as exc:
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
                for key in variant_keys:
                    rows.append(_skip_row(asset, timeframe, VARIANT_SPECS[key].label, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001 - one combo's failure must not lose the rest
                elapsed = time.monotonic() - start
                print(f"{asset} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
                for key in variant_keys:
                    rows.append(_skip_row(asset, timeframe, VARIANT_SPECS[key].label, f"{exc.__class__.__name__}: {exc}"))
                continue

            elapsed = time.monotonic() - start
            print(f"{asset} / {timeframe}: {method} — {len(candles)} candles ({elapsed:.1f}s)")
            train, test = split_chronological(candles)

            for key in variant_keys:
                base_spec = VARIANT_SPECS[key]
                spec = _calibrated_spec(base_spec, timeframe, asset)

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


def run_pairs_rows(timeframes: list[str], client: MarketDataClient) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    x_name, y_name = PAIRS_ASSET_PAIR

    for timeframe in timeframes:
        start = time.monotonic()
        try:
            x_candles, x_method = fetch_timeframe_candles(client, x_name, timeframe)
            y_candles, y_method = fetch_timeframe_candles(client, y_name, timeframe)
        except MarketDataUnavailableError as exc:
            elapsed = time.monotonic() - start
            print(f"{PAIRS_ASSET_LABEL} / {timeframe}: SKIPPED ({elapsed:.1f}s) — {exc}")
            rows.append(_skip_row(PAIRS_ASSET_LABEL, timeframe, PAIRS_STRATEGY_LABEL, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            print(f"{PAIRS_ASSET_LABEL} / {timeframe}: FAILED ({elapsed:.1f}s) — {exc.__class__.__name__}: {exc}")
            rows.append(_skip_row(PAIRS_ASSET_LABEL, timeframe, PAIRS_STRATEGY_LABEL, f"{exc.__class__.__name__}: {exc}"))
            continue

        aligned = align_pair_candles(x_candles, y_candles, x_name, y_name)
        if aligned.empty:
            print(f"{PAIRS_ASSET_LABEL} / {timeframe}: SKIPPED — no overlapping candle timestamps between {x_name} and {y_name}")
            rows.append(_skip_row(PAIRS_ASSET_LABEL, timeframe, PAIRS_STRATEGY_LABEL, f"no overlapping candles between {x_name} and {y_name}"))
            continue

        elapsed = time.monotonic() - start
        print(f"{PAIRS_ASSET_LABEL} / {timeframe}: {x_method} + {y_method} — {len(aligned)} aligned candles ({elapsed:.1f}s)")

        train_raw, test_raw = split_chronological(aligned)
        full_enriched = pairs_add_indicators(aligned, PAIRS_PARAMETERS, x_name, y_name)
        train_enriched = pairs_add_indicators(train_raw, PAIRS_PARAMETERS, x_name, y_name)
        test_enriched = pairs_add_indicators(test_raw, PAIRS_PARAMETERS, x_name, y_name)

        full_trades, full_state = run_pairs_backtest(full_enriched, PAIRS_PARAMETERS, x_name, y_name)
        train_trades, train_state = run_pairs_backtest(train_enriched, PAIRS_PARAMETERS, x_name, y_name)
        test_trades, test_state = run_pairs_backtest(test_enriched, PAIRS_PARAMETERS, x_name, y_name)

        rows.append(
            {
                "asset": PAIRS_ASSET_LABEL,
                "timeframe": timeframe,
                "strategy": PAIRS_STRATEGY_LABEL,
                "full": _metrics_cell(compute_metrics(PAIRS_ASSET_LABEL, PAIRS_STRATEGY_LABEL, full_state, full_trades)),
                "train": _metrics_cell(compute_metrics(PAIRS_ASSET_LABEL, PAIRS_STRATEGY_LABEL, train_state, train_trades)),
                "test": _metrics_cell(compute_metrics(PAIRS_ASSET_LABEL, PAIRS_STRATEGY_LABEL, test_state, test_trades)),
            }
        )

    return rows


def find_positive_both_halves(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Configurations where BOTH train and test have expectancy_r > 0 AND at least
    MIN_SAMPLE_SIZE trades in EACH half. No other filter, no ranking beyond this."""
    qualifying: list[dict[str, object]] = []
    for row in rows:
        train, test = row["train"], row["test"]
        if "skip_reason" in train or "skip_reason" in test:
            continue
        if (
            train["trades"] >= MIN_SAMPLE_SIZE
            and test["trades"] >= MIN_SAMPLE_SIZE
            and train["expectancy_r"] > 0
            and test["expectancy_r"] > 0
        ):
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
    group_header = f"{'':<10}{'':<8}{'':<52}{'--- FULL ---':^24}  {'--- TRAIN (70%) ---':^24}  {'--- TEST (30%) ---':^24}"
    header = (
        f"{'Asset':<10}{'TF':<8}{'Strategy':<52}"
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
            lines.append(f"{row['asset']:<10}{row['timeframe']:<8}{row['strategy']:<52} SKIPPED — {skip_reason}")
            continue
        lines.append(
            f"{row['asset']:<10}{row['timeframe']:<8}{row['strategy']:<52}"
            f"{_fmt_cell(row['full'])}  {_fmt_cell(row['train'])}  {_fmt_cell(row['test'])}"
        )
    lines.append("-" * len(header))
    lines.append("* = below the 20-trade minimum sample; treat that cell as exploratory, not conclusive.")
    return "\n".join(lines)


def format_positive_both_halves_summary(qualifying: list[dict[str, object]]) -> str:
    lines: list[str] = ["", f"Configurations positive in BOTH train and test with >= {MIN_SAMPLE_SIZE} trades in each half:"]
    if not qualifying:
        lines.append("  None. No (asset, timeframe, strategy) combination in this sweep met that bar.")
        return "\n".join(lines)
    for row in qualifying:
        train, test = row["train"], row["test"]
        lines.append(
            f"  {row['asset']:<10} {row['timeframe']:<7} {row['strategy']:<52} "
            f"train: N={train['trades']} ExpR={train['expectancy_r']:.3f} | "
            f"test: N={test['trades']} ExpR={test['expectancy_r']:.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", nargs="+", default=ASSETS)
    parser.add_argument("--timeframes", nargs="+", default=STANDARD_TIMEFRAMES, choices=STANDARD_TIMEFRAMES)
    parser.add_argument("--variants", nargs="+", default=SINGLE_ASSET_VARIANT_KEYS, choices=SINGLE_ASSET_VARIANT_KEYS)
    parser.add_argument("--skip-pairs", action="store_true", help="skip the COINTEGRATION_PAIRS BTC-ETH rows")
    args = parser.parse_args()

    client = MarketDataClient()
    rows = run_single_asset_rows(args.assets, args.timeframes, client, args.variants)
    if not args.skip_pairs:
        rows.extend(run_pairs_rows(args.timeframes, client))

    print()
    print(format_consolidated_table(rows))
    print(format_positive_both_halves_summary(find_positive_both_halves(rows)))


if __name__ == "__main__":
    main()
