"""CLI: RMR Variant Research Cycle — Stage 1, backtest 4 variants against FRESH
v1.0.0 baselines (same asset/timeframe/data-window, same run — never a stale stored
comparison).

  (a) RMR_LONG_ONLY_EURUSD_4H       — range-mean-reversion-v1.1.0-long-only, EUR/USD/4h
  (b) RMR_ADX_FALLING_ETH_4H        — range-mean-reversion-v1.2.0-adx-falling, ETH/4h
  (c) RMR_LONG_ONLY_BTC_1D          — range-mean-reversion-v1.1.0-long-only, BTC/1d
  (d) RMR_CONFIRMATION_BTC_1D       — range-mean-reversion-v1.3.0-confirmation, BTC/1d

(c) and (d) share the same asset/timeframe (BTC/1d), so that data is fetched once and
the v1.0.0 baseline computed once, reused for both comparisons.

Fees: forex flat 0.05%/side (matching every prior forex task's convention); crypto
uses the unscaled crypto-baseline default (no scaling needed for BTC/ETH).

Every config: chronological 70/30 split, bootstrap 95% CI, and the same bespoke
regime-restricted random-entry baseline built for RANGE_MEAN_REVERSION Task 2
(tools.backtest_range_mean_reversion_sweep.range_random_baseline) — reused as-is,
not reimplemented, since the eligible-pool semantics (ADX < entry threshold) don't
change across variants. compute_metrics is reused directly from tools.backtest_compare
since RANGE_MEAN_REVERSION's ExitEvent already carries the same net_pnl/r_multiple/
equity_after fields that function expects.

No synthetic/fabricated price data — a failed fetch is reported as SKIPPED with the
reason, never a substituted result.

Usage:
    python -m tools.rmr_variant_research_stage1
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.range_mean_reversion import (
    DEFAULT_PARAMETERS,
    INDICATOR_COLUMNS_TO_CHECK,
    add_indicators,
    range_eligible_mask,
)
from nero_core.strategies.range_mean_reversion import run_backtest as v1_run_backtest
from nero_core.strategies.range_mean_reversion_adx_falling import ADX_FALLING_PARAMETERS
from nero_core.strategies.range_mean_reversion_confirmation import CONFIRMATION_PARAMETERS
from nero_core.strategies.range_mean_reversion_confirmation import run_backtest as confirmation_run_backtest
from nero_core.strategies.range_mean_reversion_long_only import LONG_ONLY_PARAMETERS
from tools.backtest_compare import compute_metrics
from tools.backtest_range_mean_reversion_sweep import range_random_baseline
from tools.backtest_statistics import MIN_SAMPLE_SIZE, bootstrap_mean_r_ci, classify_verdict
from tools.backtest_train_test_split import split_chronological
from tools.timeframe_data import fetch_timeframe_candles

FOREX_FEE_BPS = 5.0
FOREX_SLIPPAGE_BPS = 2.0


def calibrated_params_for(asset: str, base_params):
    if asset == "EUR/USD":
        return replace(base_params, fee_bps=FOREX_FEE_BPS, slippage_bps=FOREX_SLIPPAGE_BPS)
    return base_params  # crypto: standard/unscaled, per the task spec


def _half_stats(half_candles: pd.DataFrame, params, run_backtest_fn=v1_run_backtest) -> dict[str, object]:
    enriched = add_indicators(half_candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, state = run_backtest_fn(evaluable, params)
    metrics = compute_metrics("", "", state, trades)
    r_values = [t.r_multiple for t in trades]
    ci = bootstrap_mean_r_ci(r_values)
    eligible_mask = range_eligible_mask(evaluable, params)
    baseline = range_random_baseline(evaluable, eligible_mask, params, metrics.expectancy_r, len(trades))
    return {
        "trades": metrics.sample_size, "expectancy_r": metrics.expectancy_r,
        "win_rate": metrics.win_rate, "profit_factor": metrics.profit_factor, "max_drawdown": metrics.max_drawdown,
        "below_min_sample": len(trades) < MIN_SAMPLE_SIZE, "ci": ci, "baseline": baseline,
    }


def _config_result(label: str, params, run_backtest_fn, candles: pd.DataFrame) -> dict[str, object]:
    start = time.monotonic()
    train, test = split_chronological(candles)
    train_stats = _half_stats(train, params, run_backtest_fn)
    test_stats = _half_stats(test, params, run_backtest_fn)
    elapsed = time.monotonic() - start
    print(f"{label}: done ({elapsed:.1f}s)")
    return {
        "label": label, "candle_count": len(candles), "train": train_stats, "test": test_stats,
        "verdict": classify_verdict(train_stats, test_stats),
    }


def run_stage1() -> dict[str, list[dict[str, object]]]:
    client = MarketDataClient()
    results: dict[str, list[dict[str, object]]] = {}

    # (a) EUR/USD / 4h: baseline vs long-only
    try:
        eurusd = fetch_forex_ohlcv("EUR/USD", "4h").prices
        results["EUR/USD_4h"] = [
            _config_result("EUR/USD/4h v1.0.0 (baseline)", calibrated_params_for("EUR/USD", DEFAULT_PARAMETERS), v1_run_backtest, eurusd),
            _config_result("EUR/USD/4h v1.1.0-long-only (RMR_LONG_ONLY_EURUSD_4H)", calibrated_params_for("EUR/USD", LONG_ONLY_PARAMETERS), v1_run_backtest, eurusd),
        ]
    except ForexDataUnavailableError as exc:
        print(f"EUR/USD / 4h: SKIPPED — {exc}")
        results["EUR/USD_4h"] = [{"label": "EUR/USD/4h", "error": str(exc)}]

    # (b) ETH / 4h: baseline vs adx-falling
    try:
        eth, _method = fetch_timeframe_candles(client, "ETH", "4h")
        results["ETH_4h"] = [
            _config_result("ETH/4h v1.0.0 (baseline)", DEFAULT_PARAMETERS, v1_run_backtest, eth),
            _config_result("ETH/4h v1.2.0-adx-falling (RMR_ADX_FALLING_ETH_4H)", ADX_FALLING_PARAMETERS, v1_run_backtest, eth),
        ]
    except MarketDataUnavailableError as exc:
        print(f"ETH / 4h: SKIPPED — {exc}")
        results["ETH_4h"] = [{"label": "ETH/4h", "error": str(exc)}]

    # (c)+(d) BTC / 1d: baseline vs long-only vs confirmation (fetched once, reused)
    try:
        btc, _method = fetch_timeframe_candles(client, "BTC", "24h")
        results["BTC_1d"] = [
            _config_result("BTC/1d v1.0.0 (baseline)", DEFAULT_PARAMETERS, v1_run_backtest, btc),
            _config_result("BTC/1d v1.1.0-long-only (RMR_LONG_ONLY_BTC_1D)", LONG_ONLY_PARAMETERS, v1_run_backtest, btc),
            _config_result("BTC/1d v1.3.0-confirmation (RMR_CONFIRMATION_BTC_1D)", CONFIRMATION_PARAMETERS, confirmation_run_backtest, btc),
        ]
    except MarketDataUnavailableError as exc:
        print(f"BTC / 1d: SKIPPED — {exc}")
        results["BTC_1d"] = [{"label": "BTC/1d", "error": str(exc)}]

    return results


def _fmt_half(stats: dict[str, object]) -> str:
    flag = "*" if stats["below_min_sample"] else ""
    baseline = stats["baseline"]
    edge = f", edge_over_random={baseline.edge_over_random:.3f}" if baseline is not None else ""
    ci = stats["ci"]
    ci_txt = f", CI=[{ci.lower_2_5:.3f},{ci.upper_97_5:.3f}]" if ci is not None else ""
    return (
        f"N={stats['trades']}{flag} ExpR={stats['expectancy_r']:.3f} win%={stats['win_rate']*100:.1f} "
        f"PF={stats['profit_factor']:.2f} MaxDD={stats['max_drawdown']*100:.2f}%{edge}{ci_txt}"
    )


def format_report(results: dict[str, list[dict[str, object]]]) -> str:
    lines = ["=== RMR Variant Research Cycle — Stage 1 ===", ""]
    for group, configs in results.items():
        lines.append(f"--- {group} ---")
        for c in configs:
            if "error" in c:
                lines.append(f"  {c['label']}: SKIPPED — {c['error']}")
                continue
            lines.append(f"  {c['label']}: {c['verdict']} ({c['candle_count']} candles)")
            lines.append(f"    TRAIN: {_fmt_half(c['train'])}")
            lines.append(f"    TEST:  {_fmt_half(c['test'])}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_stage1()
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
