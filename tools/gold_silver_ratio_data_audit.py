"""CLI: GOLD_SILVER_RATIO_MR — data audit (Three New Hypothesis Batch, Hypothesis 1).

Fetches GOLD and SILVER daily (="24h") and weekly (="1week") candles via the
established tools.timeframe_data.fetch_timeframe_candles pipeline, aligns them on
close_time, computes ratio = GOLD_close / SILVER_close, and reports mean/std,
10th/90th percentile bands over the FULL history, plus a rolling-252-session 10th/
90th percentile band (the actual entry trigger the strategy will use) so any
structural extreme (2020 COVID spike, etc.) is visible BEFORE the strategy is built,
not discovered after.

No synthetic/fabricated price data — a failed fetch blocks the whole hypothesis and
is reported as such, never silently substituted.

Usage:
    python -m tools.gold_silver_ratio_data_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.gold_silver_ratio_mr import align_gold_silver_candles
from tools.timeframe_data import fetch_timeframe_candles

TIMEFRAMES = {"1d": "24h", "1week": "1week"}
ROLLING_WINDOW = 252
MIN_YEARS = 5


def align_and_ratio(gold: pd.DataFrame, silver: pd.DataFrame) -> pd.DataFrame:
    """Reuses the strategy module's own align_gold_silver_candles (calendar-date
    join -- see that function's docstring for why an exact close_time join
    produces zero matches), then attaches the ratio column this audit reports on."""
    merged = align_gold_silver_candles(gold, silver)
    merged["ratio"] = merged["gold_close"] / merged["silver_close"]
    return merged


def audit_timeframe(display_tf: str, client: MarketDataClient) -> dict[str, object]:
    try:
        gold, gold_method = fetch_timeframe_candles(client, "GOLD", TIMEFRAMES[display_tf])
        silver, silver_method = fetch_timeframe_candles(client, "SILVER", TIMEFRAMES[display_tf])
    except MarketDataUnavailableError as exc:
        return {"timeframe": display_tf, "blocked": True, "reason": str(exc)}

    merged = align_and_ratio(gold, silver)
    if merged.empty:
        return {"timeframe": display_tf, "blocked": True, "reason": "no aligned GOLD/SILVER candles"}

    span_days = (merged["date"].iloc[-1] - merged["date"].iloc[0]).days
    span_years = span_days / 365.25
    adequate_history = span_years >= MIN_YEARS

    ratio = merged["ratio"]
    rolling_p10 = ratio.rolling(ROLLING_WINDOW).quantile(0.10)
    rolling_p90 = ratio.rolling(ROLLING_WINDOW).quantile(0.90)
    rolling_median = ratio.rolling(ROLLING_WINDOW).median()

    return {
        "timeframe": display_tf,
        "blocked": not adequate_history,
        "reason": None if adequate_history else f"only {span_years:.1f} years of aligned history (< {MIN_YEARS})",
        "gold_method": gold_method, "silver_method": silver_method,
        "candle_count": len(merged), "span_years": span_years,
        "ratio_mean": float(ratio.mean()), "ratio_std": float(ratio.std()),
        "ratio_min": float(ratio.min()), "ratio_max": float(ratio.max()),
        "ratio_p10_full_history": float(ratio.quantile(0.10)),
        "ratio_p90_full_history": float(ratio.quantile(0.90)),
        "rolling_p10_last": float(rolling_p10.dropna().iloc[-1]) if rolling_p10.dropna().size else None,
        "rolling_p90_last": float(rolling_p90.dropna().iloc[-1]) if rolling_p90.dropna().size else None,
        "rolling_median_last": float(rolling_median.dropna().iloc[-1]) if rolling_median.dropna().size else None,
        "max_ratio_date": str(merged.loc[ratio.idxmax(), "date"]),
        "min_ratio_date": str(merged.loc[ratio.idxmin(), "date"]),
        "warmup_valid_rows": int(rolling_p10.dropna().shape[0]),
    }


def format_report(results: list[dict[str, object]]) -> str:
    lines = ["=== GOLD_SILVER_RATIO_MR: Data Audit ===", ""]
    for r in results:
        lines.append(f"--- {r['timeframe']} ---")
        if r["blocked"]:
            lines.append(f"  BLOCKED: {r['reason']}")
            lines.append("")
            continue
        lines.append(f"  GOLD: {r['gold_method']} | SILVER: {r['silver_method']}")
        lines.append(f"  Aligned candles: {r['candle_count']} ({r['span_years']:.1f} years)")
        lines.append(f"  Ratio full-history: mean={r['ratio_mean']:.3f} std={r['ratio_std']:.3f} "
                     f"min={r['ratio_min']:.3f} ({r['min_ratio_date']}) max={r['ratio_max']:.3f} ({r['max_ratio_date']})")
        lines.append(f"  Ratio full-history 10th/90th percentile: {r['ratio_p10_full_history']:.3f} / {r['ratio_p90_full_history']:.3f}")
        lines.append(f"  Rolling-{ROLLING_WINDOW}-session 10th/median/90th (most recent): "
                     f"{r['rolling_p10_last']:.3f} / {r['rolling_median_last']:.3f} / {r['rolling_p90_last']:.3f}"
                     if r["rolling_p90_last"] is not None else "  Rolling percentile: insufficient warmup")
        lines.append(f"  Warmup-valid rows (usable for rolling-band entry): {r['warmup_valid_rows']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    client = MarketDataClient()
    results = [audit_timeframe(tf, client) for tf in TIMEFRAMES]
    print(format_report(results))


if __name__ == "__main__":
    main()
