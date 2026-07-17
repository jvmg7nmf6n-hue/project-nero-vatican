"""CLI: H6 — robustness audit (diagnostic only, NOT a strategy; nothing here is
registered). For the 6 configurations that passed the "positive in both train and test,
>= 20 trades each half" filter in the prior remaining-strategies sweep, break down every
CLOSED trade (full history) three ways: (a) day of week, (b) candle-close hour (UTC),
(c) calendar year. Reports trade count and summed/mean R per bucket, plus how much of
the total summed R the single largest bucket in each dimension accounts for — the
concrete number this audit exists to produce (e.g. "one year contributed 80% of all
profit" would flag fragility).

The 6 configurations audited:
  BTC   12h  MEAN_REVERSION relaxed-pullback
  BNB   12h  TREND_PULLBACK
  BNB   12h  MEAN_REVERSION relaxed-pullback
  XRP   2h   MEAN_REVERSION deep-value
  NEAR  2h   MEAN_REVERSION deep-value
  BTC-ETH 12h  COINTEGRATION_PAIRS

No synthetic/fabricated price data is ever used — if a fetch fails, that configuration
is reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/robustness_audit.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.cointegration_pairs import DEFAULT_PARAMETERS as PAIRS_PARAMETERS
from nero_core.strategies.cointegration_pairs import add_indicators as pairs_add_indicators
from nero_core.strategies.cointegration_pairs import align_pair_candles, run_pairs_backtest
from nero_core.strategies.timeframe_calibration import build_calibrated_params
from tools.backtest_compare import VARIANT_SPECS, run_backtest
from tools.timeframe_data import fetch_timeframe_candles

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SINGLE_ASSET_CONFIGS = [
    {"label": "BTC / 12h / MEAN_REVERSION relaxed-pullback", "asset": "BTC", "timeframe": "12h", "variant_key": "mean_reversion_relaxed_pullback"},
    {"label": "BNB / 12h / TREND_PULLBACK", "asset": "BNB", "timeframe": "12h", "variant_key": "trend_pullback"},
    {"label": "BNB / 12h / MEAN_REVERSION relaxed-pullback", "asset": "BNB", "timeframe": "12h", "variant_key": "mean_reversion_relaxed_pullback"},
    {"label": "XRP / 2h / MEAN_REVERSION deep-value", "asset": "XRP", "timeframe": "2h", "variant_key": "mean_reversion_deep_value"},
    {"label": "NEAR / 2h / MEAN_REVERSION deep-value", "asset": "NEAR", "timeframe": "2h", "variant_key": "mean_reversion_deep_value"},
]

PAIRS_CONFIG = {"label": "BTC-ETH / 12h / COINTEGRATION_PAIRS", "timeframe": "12h"}


def _bucket_stats(trades: list, key_fn) -> dict[object, dict[str, float]]:
    buckets: dict[object, dict[str, float]] = {}
    for trade in trades:
        key = key_fn(trade)
        bucket = buckets.setdefault(key, {"n": 0, "sum_r": 0.0})
        bucket["n"] += 1
        bucket["sum_r"] += trade.r_multiple
    for bucket in buckets.values():
        bucket["mean_r"] = bucket["sum_r"] / bucket["n"] if bucket["n"] else 0.0
    return buckets


def _timestamp(trade) -> pd.Timestamp:
    return pd.Timestamp(trade.exit_close_time, unit="ms", tz="UTC")


def _largest_bucket_share(buckets: dict[object, dict[str, float]]) -> tuple[object, float]:
    """Returns (bucket_key, share) where share is that bucket's sum_r as a fraction of
    the sum of all POSITIVE bucket sum_r values (a concentration-of-profit measure) —
    0.0 if there is no positive total to divide by."""
    total_positive = sum(b["sum_r"] for b in buckets.values() if b["sum_r"] > 0)
    if total_positive <= 0:
        return None, 0.0
    best_key, best_share = None, 0.0
    for key, bucket in buckets.items():
        if bucket["sum_r"] <= 0:
            continue
        share = bucket["sum_r"] / total_positive
        if share > best_share:
            best_key, best_share = key, share
    return best_key, best_share


def audit_trades(label: str, trades: list) -> dict[str, object]:
    by_day = _bucket_stats(trades, lambda t: _timestamp(t).day_name())
    by_hour = _bucket_stats(trades, lambda t: _timestamp(t).hour)
    by_year = _bucket_stats(trades, lambda t: _timestamp(t).year)
    return {
        "label": label,
        "total_trades": len(trades),
        "by_day": by_day,
        "by_hour": by_hour,
        "by_year": by_year,
        "largest_day_share": _largest_bucket_share(by_day),
        "largest_hour_share": _largest_bucket_share(by_hour),
        "largest_year_share": _largest_bucket_share(by_year),
    }


def run_single_asset_audit(config: dict[str, object], client: MarketDataClient) -> dict[str, object]:
    asset, timeframe, variant_key = config["asset"], config["timeframe"], config["variant_key"]
    try:
        candles, method = fetch_timeframe_candles(client, asset, timeframe)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": str(exc)}

    base_spec = VARIANT_SPECS[variant_key]
    spec = replace(base_spec, params=build_calibrated_params(base_spec.params, timeframe, asset))
    trades, _ = run_backtest(candles, spec)
    print(f"{config['label']}: {method} — {len(candles)} candles, {len(trades)} closed trades")
    return audit_trades(config["label"], trades)


def run_pairs_audit(config: dict[str, object], client: MarketDataClient) -> dict[str, object]:
    timeframe = config["timeframe"]
    try:
        btc_candles, btc_method = fetch_timeframe_candles(client, "BTC", timeframe)
        eth_candles, eth_method = fetch_timeframe_candles(client, "ETH", timeframe)
    except MarketDataUnavailableError as exc:
        return {"label": config["label"], "error": str(exc)}

    aligned = align_pair_candles(btc_candles, eth_candles, "BTC", "ETH")
    enriched = pairs_add_indicators(aligned, PAIRS_PARAMETERS, "BTC", "ETH")
    trades, _ = run_pairs_backtest(enriched, PAIRS_PARAMETERS, "BTC", "ETH")
    print(f"{config['label']}: {btc_method} + {eth_method} — {len(aligned)} aligned candles, {len(trades)} closed trades")
    return audit_trades(config["label"], trades)


def run_all_audits() -> list[dict[str, object]]:
    client = MarketDataClient()
    results = [run_single_asset_audit(c, client) for c in SINGLE_ASSET_CONFIGS]
    results.append(run_pairs_audit(PAIRS_CONFIG, client))
    return results


def _format_bucket_table(buckets: dict[object, dict[str, float]], order: list[object] | None = None) -> str:
    keys = order if order is not None else sorted(buckets.keys())
    lines = []
    for key in keys:
        if key not in buckets:
            continue
        b = buckets[key]
        lines.append(f"    {str(key):<12} N={b['n']:>4}  sum_R={b['sum_r']:>8.2f}  mean_R={b['mean_r']:>7.3f}")
    return "\n".join(lines)


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for r in results:
        lines.append(f"=== {r['label']} ===")
        if "error" in r:
            lines.append(f"  SKIPPED — {r['error']}")
            lines.append("")
            continue
        lines.append(f"  Total closed trades (full history): {r['total_trades']}")
        lines.append("  By day of week:")
        lines.append(_format_bucket_table(r["by_day"], order=DAY_ORDER))
        lines.append("  By candle-close hour (UTC):")
        lines.append(_format_bucket_table(r["by_hour"], order=list(range(24))))
        lines.append("  By calendar year:")
        lines.append(_format_bucket_table(r["by_year"]))

        day_key, day_share = r["largest_day_share"]
        hour_key, hour_share = r["largest_hour_share"]
        year_key, year_share = r["largest_year_share"]
        lines.append("  Concentration (share of total POSITIVE summed R from the single largest bucket):")
        lines.append(f"    Largest day:  {day_key}  ({day_share * 100:.1f}%)" if day_key is not None else "    Largest day:  n/a (no positive R)")
        lines.append(f"    Largest hour: {hour_key}  ({hour_share * 100:.1f}%)" if hour_key is not None else "    Largest hour: n/a (no positive R)")
        lines.append(f"    Largest year: {year_key}  ({year_share * 100:.1f}%)" if year_key is not None else "    Largest year: n/a (no positive R)")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    results = run_all_audits()
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
