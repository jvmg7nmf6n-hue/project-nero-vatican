"""CLI: ASSET EXPANSION — Phase A, Task 1. Data + calibration audit for Silver
(XAG/USD) and Platinum (XPT/USD), run BEFORE any strategy sweep is attempted against
them.

For each metal, at every timeframe in the standard set (2h, 4h, 12h, 24h, 1week —
the full set any of Phase A's 9 strategies might need), reports:
  (a) history depth — candle count and wall-clock date span actually returned by
      tools.timeframe_data.fetch_timeframe_candles (the identical fetch path GOLD
      already uses: native Twelve Data 2h/4h/1week, 12h resampled from Twelve Data 1h,
      24h via MarketDataClient.load_daily).
  (b) gaps — the largest gap between consecutive closed candles, compared against the
      timeframe's expected spacing (a large multiple flags a real data hole, not just
      an expected exchange/market-closure gap).
  (c) ATR/price ratio at 4h vs GOLD's own measured ratio (see
      nero_core.strategies.mean_reversion_gold_calibrated.GOLD_MEASURED_PRICE_ATR_RATIO),
      using the IDENTICAL methodology: price/ATR averaged over every 4h candle where
      MEAN_REVERSION v1 actually takes an entry (same trigger, same n-derivation).

ADEQUACY BAR: a timeframe needs at least ADEQUATE_MIN_CANDLES total candles to be
tested at all. Rationale: every train/test split tool in this codebase recomputes
indicators independently on each half (test gets its own warmup from scratch, per
tools.backtest_train_test_split's docstring), and the widest warmup any Phase A
strategy needs is MA200. With a 70/30 split, the 30% test half must alone carry >=200
candles for MA200 to ever produce a non-NaN value at all, so the FULL series needs
>= 200 / 0.30 ~= 667 candles just for a single strategy to have a chance at ONE
signal — round up to 700. Below that, a timeframe is marked SKIPPED (INSUFFICIENT
DATA) and excluded from Task 2's sweep; no strategy is forced onto data this thin. If
every timeframe for a metal falls below the bar, the whole metal is marked BLOCKED.

CALIBRATION DECISION per metal: if the measured 4h price/ATR ratio is within +/-30%
of GOLD's own measured ratio, GOLD_FEE_SCALE_FACTOR is reused (documented here); if
not adequate at 4h (blocked/skipped) the ratio is instead measured at whichever
adequate intraday timeframe existed (documented explicitly, since it departs from the
GOLD-precedent methodology); if the ratio falls outside the 30% band, a metal-specific
scale factor is derived the same way GOLD's was: BTC_MEASURED_PRICE_ATR_RATIO / this
metal's own measured ratio.

No synthetic/fabricated price data is ever used — if a fetch fails, that
(metal, timeframe) combination is reported as SKIPPED with the reason, never a
substituted result.

Usage:
    python tools/metals_data_calibration_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.mean_reversion import (
    DEFAULT_PARAMETERS as MR_PARAMETERS,
    MeanReversionState,
    add_indicators as mr_add_indicators,
    evaluate_entry as mr_evaluate_entry,
)
from nero_core.strategies.mean_reversion_gold_calibrated import (
    BTC_MEASURED_PRICE_ATR_RATIO,
    GOLD_FEE_SCALE_FACTOR,
    GOLD_MEASURED_PRICE_ATR_RATIO,
)
from tools.timeframe_data import STANDARD_TIMEFRAMES, fetch_timeframe_candles

METALS = ["SILVER", "PLATINUM"]

ADEQUATE_MIN_CANDLES = 700

# Expected spacing between consecutive candles, in hours, for gap detection.
EXPECTED_SPACING_HOURS = {"2h": 2, "4h": 4, "12h": 12, "24h": 24, "1week": 168}

# A gap this many multiples of the expected spacing counts as a real data hole worth
# flagging, rather than routine weekend/holiday market closure (spot metals trade
# nearly 24/5 but do close over the weekend, so a ~2-2.5x gap every week is normal).
GAP_FLAG_MULTIPLE = 4.0

# Reuse GOLD's own calibration if the measured ratio is within this fraction of GOLD's.
CALIBRATION_REUSE_TOLERANCE = 0.30


def _max_gap_hours(candles: pd.DataFrame) -> float:
    if len(candles) < 2:
        return 0.0
    close_times = candles.sort_values("close_time")["close_time"].to_numpy()
    gaps_ms = close_times[1:] - close_times[:-1]
    return float(gaps_ms.max()) / 3_600_000.0


def audit_timeframe(client: MarketDataClient, asset: str, timeframe: str) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, asset, timeframe)
    except MarketDataUnavailableError as exc:
        return {"timeframe": timeframe, "error": str(exc)}

    if candles.empty:
        return {"timeframe": timeframe, "error": "fetch succeeded but returned zero candles"}

    candle_count = len(candles)
    date_min = pd.to_datetime(candles["date"]).min()
    date_max = pd.to_datetime(candles["date"]).max()
    span_days = (date_max - date_min).total_seconds() / 86400.0
    max_gap_hours = _max_gap_hours(candles)
    expected_spacing = EXPECTED_SPACING_HOURS[timeframe]
    gap_flag = max_gap_hours >= expected_spacing * GAP_FLAG_MULTIPLE
    adequate = candle_count >= ADEQUATE_MIN_CANDLES

    return {
        "timeframe": timeframe,
        "method": method,
        "candle_count": candle_count,
        "date_min": date_min,
        "date_max": date_max,
        "span_days": span_days,
        "max_gap_hours": max_gap_hours,
        "expected_spacing_hours": expected_spacing,
        "gap_flag": gap_flag,
        "adequate": adequate,
    }


def measure_price_atr_ratio(candles: pd.DataFrame) -> dict[str, object]:
    """Reproduces GOLD_MEASURED_PRICE_ATR_RATIO's exact methodology: price/ATR(14)
    averaged over every candle where MEAN_REVERSION v1's entry rule set actually
    passes (RSI<35, close<lower BB, close>MA200, MA20 target above close)."""
    enriched = mr_add_indicators(candles, MR_PARAMETERS)
    evaluable = enriched.dropna(subset=["ma20", "bb_lower", "ma200", "rsi", "atr"]).reset_index(drop=True)

    state = MeanReversionState(equity=MR_PARAMETERS.initial_equity)
    ratios: list[float] = []
    for i in range(len(evaluable)):
        candle = evaluable.iloc[i]
        evaluation = mr_evaluate_entry(candle, state, MR_PARAMETERS)
        if evaluation.passed and evaluation.atr > 0:
            ratios.append(evaluation.close / evaluation.atr)

    if not ratios:
        return {"n": 0, "ratio": None}
    return {"n": len(ratios), "ratio": sum(ratios) / len(ratios)}


def decide_calibration(metal: str, ratio_info: dict[str, object], ratio_source_timeframe: str | None) -> dict[str, object]:
    if ratio_info["n"] == 0 or ratio_info["ratio"] is None:
        return {
            "decision": "REUSE_GOLD",
            "scale_factor": GOLD_FEE_SCALE_FACTOR,
            "justification": (
                f"No MEAN_REVERSION v1 entries were observed for {metal} on any adequate "
                "intraday timeframe to measure a price/ATR ratio directly. Falling back to "
                "GOLD's calibration as the only available reference point for a precious "
                "metal instrument, pending a larger sample once more live history accrues."
            ),
        }

    ratio = ratio_info["ratio"]
    deviation = abs(ratio - GOLD_MEASURED_PRICE_ATR_RATIO) / GOLD_MEASURED_PRICE_ATR_RATIO
    if deviation <= CALIBRATION_REUSE_TOLERANCE:
        return {
            "decision": "REUSE_GOLD",
            "scale_factor": GOLD_FEE_SCALE_FACTOR,
            "justification": (
                f"{metal}'s measured price/ATR ratio ({ratio:.4f}, n={ratio_info['n']} entries "
                f"at {ratio_source_timeframe}) is within {deviation * 100:.1f}% of GOLD's "
                f"({GOLD_MEASURED_PRICE_ATR_RATIO:.4f}) — inside the {CALIBRATION_REUSE_TOLERANCE * 100:.0f}% "
                "reuse tolerance. GOLD_FEE_SCALE_FACTOR is reused unchanged."
            ),
        }

    own_scale_factor = BTC_MEASURED_PRICE_ATR_RATIO / ratio
    return {
        "decision": "DERIVE_OWN",
        "scale_factor": own_scale_factor,
        "justification": (
            f"{metal}'s measured price/ATR ratio ({ratio:.4f}, n={ratio_info['n']} entries at "
            f"{ratio_source_timeframe}) deviates {deviation * 100:.1f}% from GOLD's "
            f"({GOLD_MEASURED_PRICE_ATR_RATIO:.4f}), outside the {CALIBRATION_REUSE_TOLERANCE * 100:.0f}% "
            f"reuse tolerance. Derived a {metal}-specific scale factor the same way GOLD's was "
            f"derived: BTC_MEASURED_PRICE_ATR_RATIO / {metal}_MEASURED_PRICE_ATR_RATIO = "
            f"{BTC_MEASURED_PRICE_ATR_RATIO:.4f} / {ratio:.4f} = {own_scale_factor:.4f}."
        ),
    }


def run_audit() -> dict[str, object]:
    client = MarketDataClient()
    results: dict[str, object] = {}

    for metal in METALS:
        timeframe_results: dict[str, dict[str, object]] = {}
        for timeframe in STANDARD_TIMEFRAMES:
            print(f"{metal} / {timeframe}: fetching...")
            result = audit_timeframe(client, metal, timeframe)
            timeframe_results[timeframe] = result
            if "error" in result:
                print(f"{metal} / {timeframe}: SKIPPED — {result['error']}")
            else:
                status = "ADEQUATE" if result["adequate"] else "INSUFFICIENT DATA"
                print(
                    f"{metal} / {timeframe}: {status} — {result['candle_count']} candles, "
                    f"{result['span_days']:.1f} days ({result['date_min'].date()} to {result['date_max'].date()}), "
                    f"max gap {result['max_gap_hours']:.1f}h"
                )

        adequate_timeframes = [tf for tf, r in timeframe_results.items() if "error" not in r and r["adequate"]]
        blocked = not adequate_timeframes

        ratio_info = {"n": 0, "ratio": None}
        ratio_source_timeframe = None
        if "4h" in adequate_timeframes:
            candles_4h, _method = fetch_timeframe_candles(client, metal, "4h")
            ratio_info = measure_price_atr_ratio(candles_4h)
            ratio_source_timeframe = "4h"
        elif adequate_timeframes:
            # Deviation from the GOLD-precedent methodology (measured at 4h) — documented
            # explicitly in the report rather than silently substituted.
            fallback_tf = adequate_timeframes[0]
            candles_fallback, _method = fetch_timeframe_candles(client, metal, fallback_tf)
            ratio_info = measure_price_atr_ratio(candles_fallback)
            ratio_source_timeframe = fallback_tf

        calibration = None if blocked else decide_calibration(metal, ratio_info, ratio_source_timeframe)

        results[metal] = {
            "timeframes": timeframe_results,
            "adequate_timeframes": adequate_timeframes,
            "blocked": blocked,
            "ratio_info": ratio_info,
            "ratio_source_timeframe": ratio_source_timeframe,
            "calibration": calibration,
        }

    return results


def format_report(results: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"GOLD reference: measured price/ATR ratio = {GOLD_MEASURED_PRICE_ATR_RATIO:.4f} (4h, MEAN_REVERSION v1 entries)")
    lines.append(f"BTC reference: measured price/ATR ratio = {BTC_MEASURED_PRICE_ATR_RATIO:.4f} (4h, MEAN_REVERSION v1 entries)")
    lines.append(f"GOLD_FEE_SCALE_FACTOR = {GOLD_FEE_SCALE_FACTOR:.4f}")
    lines.append("")

    for metal, data in results.items():
        lines.append(f"=== {metal} ===")
        for timeframe in STANDARD_TIMEFRAMES:
            r = data["timeframes"][timeframe]
            if "error" in r:
                lines.append(f"  {timeframe:<7} SKIPPED — {r['error']}")
                continue
            status = "ADEQUATE" if r["adequate"] else "INSUFFICIENT DATA"
            gap_note = " *** GAP FLAG ***" if r["gap_flag"] else ""
            lines.append(
                f"  {timeframe:<7} {status:<18} {r['candle_count']:>6} candles  "
                f"{r['span_days']:>7.1f}d span  ({r['date_min'].date()} to {r['date_max'].date()})  "
                f"max_gap={r['max_gap_hours']:.1f}h{gap_note}"
            )

        if data["blocked"]:
            lines.append(f"  VERDICT: {metal} is BLOCKED — no timeframe reached the {ADEQUATE_MIN_CANDLES}-candle adequacy bar.")
        else:
            lines.append(f"  Adequate timeframes: {', '.join(data['adequate_timeframes'])}")
            ratio_info = data["ratio_info"]
            if ratio_info["n"] > 0:
                lines.append(
                    f"  Measured price/ATR ratio ({data['ratio_source_timeframe']}): "
                    f"{ratio_info['ratio']:.4f} (n={ratio_info['n']} MEAN_REVERSION v1 entries)"
                )
            else:
                lines.append("  Measured price/ATR ratio: n/a (zero MEAN_REVERSION v1 entries observed)")
            calibration = data["calibration"]
            lines.append(f"  CALIBRATION: {calibration['decision']} (scale_factor={calibration['scale_factor']:.4f})")
            lines.append(f"    {calibration['justification']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    results = run_audit()
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
