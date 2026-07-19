"""CLI: RMR Variant Research Cycle — Stage 2 diagnosis support.

Stage 1's report already gives ExpR/win%/PF/MaxDD/edge-over-random per half. This
tool answers the two Stage 2 questions that need NEW numbers, not just a re-read of
Stage 1's own output:

  (b) For the long-only variants: what did the short leg actually cost in the fresh
      v1.0.0 baseline? Computed here as (baseline total R) - (long-only total R) per
      half — an APPROXIMATION, not an exact attribution, since disabling the short
      side can also change which LONG trades get taken (a blocked SHORT frees up
      state to enter a later LONG the baseline's concurrent short position would
      have blocked) — noted explicitly in the report, not glossed over.
  (d) Trade clustering / ADX-exit frequency / whipsaw patterns — exit_reason
      (STOP / REGIME_BREAK / REVERSION_TARGET) distribution and mean/median holding
      hours per config, computed from the SAME full-history run (not re-split),
      since clustering/whipsaw characterization doesn't need a train/test split.

Uses the exact same data-fetch pattern as tools.rmr_variant_research_stage1 (fetched
fresh in this run, not reused from stored Stage 1 results).

Usage:
    python -m tools.rmr_variant_research_stage2_diagnosis
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient
from nero_core.strategies.range_mean_reversion import DEFAULT_PARAMETERS, INDICATOR_COLUMNS_TO_CHECK, add_indicators
from nero_core.strategies.range_mean_reversion import run_backtest as v1_run_backtest
from nero_core.strategies.range_mean_reversion_adx_falling import ADX_FALLING_PARAMETERS
from nero_core.strategies.range_mean_reversion_confirmation import CONFIRMATION_PARAMETERS
from nero_core.strategies.range_mean_reversion_confirmation import run_backtest as confirmation_run_backtest
from nero_core.strategies.range_mean_reversion_long_only import LONG_ONLY_PARAMETERS
from tools.rmr_variant_research_stage1 import calibrated_params_for
from tools.timeframe_data import fetch_timeframe_candles


def run_full_history(candles: pd.DataFrame, params, run_backtest_fn=v1_run_backtest) -> list:
    enriched = add_indicators(candles, params)
    evaluable = enriched.dropna(subset=INDICATOR_COLUMNS_TO_CHECK).reset_index(drop=True)
    trades, _state = run_backtest_fn(evaluable, params)
    return trades


def exit_reason_profile(trades: list) -> dict[str, object]:
    if not trades:
        return {"counts": {}, "mean_holding_hours": None, "median_holding_hours": None, "n": 0}
    counts = dict(Counter(t.exit_reason for t in trades))
    holding = [t.holding_hours for t in trades]
    return {"counts": counts, "mean_holding_hours": mean(holding), "median_holding_hours": median(holding), "n": len(trades)}


def implied_short_leg_cost(baseline_trades: list, long_only_trades: list) -> dict[str, float]:
    """(baseline total R) - (long-only total R), an APPROXIMATION of the short leg's
    contribution — see module docstring for why it's not an exact attribution."""
    baseline_total_r = sum(t.r_multiple for t in baseline_trades)
    long_only_total_r = sum(t.r_multiple for t in long_only_trades)
    return {
        "baseline_total_r": baseline_total_r, "baseline_n": len(baseline_trades),
        "long_only_total_r": long_only_total_r, "long_only_n": len(long_only_trades),
        "implied_short_leg_total_r": baseline_total_r - long_only_total_r,
        "implied_short_leg_n": len(baseline_trades) - len(long_only_trades),
    }


def run_diagnosis() -> dict[str, object]:
    client = MarketDataClient()
    result: dict[str, object] = {}

    eurusd = fetch_forex_ohlcv("EUR/USD", "4h").prices
    eurusd_baseline_params = calibrated_params_for("EUR/USD", DEFAULT_PARAMETERS)
    eurusd_long_only_params = calibrated_params_for("EUR/USD", LONG_ONLY_PARAMETERS)
    eurusd_baseline_trades = run_full_history(eurusd, eurusd_baseline_params)
    eurusd_long_only_trades = run_full_history(eurusd, eurusd_long_only_params)
    result["EUR/USD_4h_baseline"] = exit_reason_profile(eurusd_baseline_trades)
    result["EUR/USD_4h_long_only"] = exit_reason_profile(eurusd_long_only_trades)
    result["EUR/USD_4h_short_leg_cost"] = implied_short_leg_cost(eurusd_baseline_trades, eurusd_long_only_trades)

    eth, _method = fetch_timeframe_candles(client, "ETH", "4h")
    eth_baseline_trades = run_full_history(eth, DEFAULT_PARAMETERS)
    eth_adx_falling_trades = run_full_history(eth, ADX_FALLING_PARAMETERS)
    result["ETH_4h_baseline"] = exit_reason_profile(eth_baseline_trades)
    result["ETH_4h_adx_falling"] = exit_reason_profile(eth_adx_falling_trades)

    btc, _method = fetch_timeframe_candles(client, "BTC", "24h")
    btc_baseline_trades = run_full_history(btc, DEFAULT_PARAMETERS)
    btc_long_only_trades = run_full_history(btc, LONG_ONLY_PARAMETERS)
    btc_confirmation_trades = run_full_history(btc, CONFIRMATION_PARAMETERS, confirmation_run_backtest)
    result["BTC_1d_baseline"] = exit_reason_profile(btc_baseline_trades)
    result["BTC_1d_long_only"] = exit_reason_profile(btc_long_only_trades)
    result["BTC_1d_confirmation"] = exit_reason_profile(btc_confirmation_trades)
    result["BTC_1d_short_leg_cost"] = implied_short_leg_cost(btc_baseline_trades, btc_long_only_trades)

    return result


def _fmt_profile(label: str, profile: dict[str, object]) -> str:
    if profile["n"] == 0:
        return f"  {label}: 0 trades (full history)"
    counts_txt = ", ".join(f"{k}={v}" for k, v in profile["counts"].items())
    return (
        f"  {label}: N={profile['n']} (full history) exit_reasons=[{counts_txt}] "
        f"mean_holding_hours={profile['mean_holding_hours']:.1f} median={profile['median_holding_hours']:.1f}"
    )


def format_report(result: dict[str, object]) -> str:
    lines = ["=== RMR Variant Research Cycle — Stage 2 Diagnosis Support ===", ""]
    lines.append("--- Exit-reason distribution / holding-hours (full history, not split) ---")
    for key, val in result.items():
        if key.endswith("_short_leg_cost"):
            continue
        lines.append(_fmt_profile(key, val))
    lines.append("")
    lines.append("--- Implied short-leg cost (baseline total R - long-only total R) ---")
    for key in ("EUR/USD_4h_short_leg_cost", "BTC_1d_short_leg_cost"):
        cost = result[key]
        avg = cost["implied_short_leg_total_r"] / cost["implied_short_leg_n"] if cost["implied_short_leg_n"] else 0.0
        lines.append(
            f"  {key}: baseline N={cost['baseline_n']} totalR={cost['baseline_total_r']:.2f} | "
            f"long_only N={cost['long_only_n']} totalR={cost['long_only_total_r']:.2f} | "
            f"implied short-leg: N~={cost['implied_short_leg_n']} totalR={cost['implied_short_leg_total_r']:.2f} "
            f"(avg~={avg:.3f} R/trade)"
        )
    return "\n".join(lines)


def main() -> None:
    result = run_diagnosis()
    print()
    print(format_report(result))


if __name__ == "__main__":
    main()
