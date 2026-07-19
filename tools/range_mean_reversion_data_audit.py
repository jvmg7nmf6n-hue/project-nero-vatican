"""RANGE_MEAN_REVERSION Task 2 — data audit (run BEFORE any backtest).

Three tiers, per the task spec:
  TIER 1 (range-prone): Forex EUR/USD, USD/JPY, GBP/USD, USD/CHF @ 1h/4h/1day;
                        Metals GOLD, SILVER @ 4h/1day(="24h")/1week
  TIER 2 (conditional):  BTC, ETH @ 4h/12h/1day(="24h")
  TIER 3 (stress-test):  SOL, NEAR @ 4h/12h

Known constraints to verify EMPIRICALLY, not assume from memory:
  - Metals intraday on Twelve Data's free tier has historically capped near ~210
    days for GOLD specifically (native Twelve Data XAU/USD) — SILVER routes through
    yfinance futures instead (Twelve Data 404s for XAG/USD, see
    docs/metals_data_calibration_audit.md), which showed much deeper 1h/4h history
    in that audit, so the ~210-day cap should NOT apply to SILVER the same way.
  - NEAR's history via the crypto exchange cascade previously hit Coinbase's
    ~300-candle cap on some intervals — must verify 4h/12h depth is adequate before
    testing, never force a stress-test on inadequate data (that would validate
    nothing).

"1day" in this task's own phrasing maps to this codebase's existing "24h" key for
crypto/metals (tools.timeframe_data's standard timeframe set), and to forex_data's own
native "1day" key for forex — both are fetched here under their respective pipeline's
real key and reported under a uniform "1day" label for readability.

No synthetic/fabricated data — a failed fetch is reported as SKIPPED with the reason.
Run: python -m tools.range_mean_reversion_data_audit
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from tools.timeframe_data import fetch_timeframe_candles

ADEQUATE_MIN_CANDLES = 100

FOREX_PAIRS = ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF"]
FOREX_TIMEFRAMES = ["1h", "4h", "1day"]

METALS = ["GOLD", "SILVER"]
METALS_TIMEFRAMES = {"4h": "4h", "1day": "24h", "1week": "1week"}  # display label -> pipeline key

TIER2_CRYPTO = ["BTC", "ETH"]
TIER2_TIMEFRAMES = {"4h": "4h", "12h": "12h", "1day": "24h"}

TIER3_CRYPTO = ["SOL", "NEAR"]
TIER3_TIMEFRAMES = {"4h": "4h", "12h": "12h"}


def audit_forex(pair: str, timeframe: str) -> dict[str, object]:
    try:
        result = fetch_forex_ohlcv(pair, timeframe)
    except ForexDataUnavailableError as exc:
        return {"tier": "TIER 1 (forex)", "asset": pair, "timeframe": timeframe, "status": "SKIPPED (UNRESOLVED)",
                "candles": 0, "start": None, "end": None, "reason": str(exc)}
    candles = result.prices
    if candles.empty:
        return {"tier": "TIER 1 (forex)", "asset": pair, "timeframe": timeframe, "status": "SKIPPED (EMPTY)",
                "candles": 0, "start": None, "end": None, "reason": "fetch succeeded but returned zero candles"}
    status = "ADEQUATE" if len(candles) >= ADEQUATE_MIN_CANDLES else "SKIPPED (INSUFFICIENT DATA)"
    return {"tier": "TIER 1 (forex)", "asset": pair, "timeframe": timeframe, "status": status,
            "candles": len(candles), "start": candles["date"].iloc[0], "end": candles["date"].iloc[-1], "reason": None}


def audit_crypto_or_metal(client: MarketDataClient, tier_label: str, asset: str, display_timeframe: str, pipeline_timeframe: str) -> dict[str, object]:
    try:
        candles, method = fetch_timeframe_candles(client, asset, pipeline_timeframe)
    except MarketDataUnavailableError as exc:
        return {"tier": tier_label, "asset": asset, "timeframe": display_timeframe, "status": "SKIPPED (UNRESOLVED)",
                "candles": 0, "start": None, "end": None, "reason": str(exc)}
    if candles.empty:
        return {"tier": tier_label, "asset": asset, "timeframe": display_timeframe, "status": "SKIPPED (EMPTY)",
                "candles": 0, "start": None, "end": None, "reason": f"fetch succeeded ({method}) but returned zero candles"}
    status = "ADEQUATE" if len(candles) >= ADEQUATE_MIN_CANDLES else "SKIPPED (INSUFFICIENT DATA)"
    return {"tier": tier_label, "asset": asset, "timeframe": display_timeframe, "status": status,
            "candles": len(candles), "start": candles["date"].iloc[0], "end": candles["date"].iloc[-1], "reason": None}


def run_audit(client: MarketDataClient | None = None, sleep_fn=time.sleep) -> list[dict[str, object]]:
    client = client or MarketDataClient()
    rows: list[dict[str, object]] = []

    for pair in FOREX_PAIRS:
        for timeframe in FOREX_TIMEFRAMES:
            rows.append(audit_forex(pair, timeframe))
            sleep_fn(8.0)  # Twelve Data rate-limit spacing, same convention as Task B1's audit

    for asset in METALS:
        for display_tf, pipeline_tf in METALS_TIMEFRAMES.items():
            rows.append(audit_crypto_or_metal(client, "TIER 1 (metals)", asset, display_tf, pipeline_tf))

    for asset in TIER2_CRYPTO:
        for display_tf, pipeline_tf in TIER2_TIMEFRAMES.items():
            rows.append(audit_crypto_or_metal(client, "TIER 2 (crypto)", asset, display_tf, pipeline_tf))

    for asset in TIER3_CRYPTO:
        for display_tf, pipeline_tf in TIER3_TIMEFRAMES.items():
            rows.append(audit_crypto_or_metal(client, "TIER 3 (stress-test)", asset, display_tf, pipeline_tf))

    return rows


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== RANGE_MEAN_REVERSION Task 2: Data Audit ===", ""]
    for r in rows:
        if r["status"] == "ADEQUATE":
            lines.append(f"[{r['tier']}] {r['asset']} / {r['timeframe']}: {r['status']} — {r['candles']} candles, {r['start']} -> {r['end']}")
        else:
            lines.append(f"[{r['tier']}] {r['asset']} / {r['timeframe']}: {r['status']} — {r['reason']}")
    adequate = sum(1 for r in rows if r["status"] == "ADEQUATE")
    lines.append("")
    lines.append(f"=== {adequate} of {len(rows)} configs ADEQUATE ===")
    return "\n".join(lines)


def main() -> None:
    rows = run_audit()
    print(format_report(rows))


if __name__ == "__main__":
    main()
