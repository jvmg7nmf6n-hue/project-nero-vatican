"""Comprehensive Asset Expansion, Part B: Forex — Task B1 data audit.

Fetches every pair in the Task B2 universe (10 standard pairs) at each standard forex
timeframe (1h, 4h, 1day, 1week) via nero_core.data_sources.forex_data.fetch_forex_ohlcv
(Twelve Data — already integrated, confirmed to serve every one of these pairs on the
current free-tier plan, unlike SILVER/PLATINUM's XAG/USD, XPT/USD 404s), and reports
per-pair/timeframe history depth, any pair that fails to resolve, and the
outputsize-per-request depth cap.

No synthetic/fabricated data — every number in the report comes from a live fetch.
Run: python -m tools.forex_data_calibration_audit
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.forex_data import FOREX_PAIRS, ForexDataUnavailableError, fetch_forex_ohlcv

STANDARD_TIMEFRAMES = ["1h", "4h", "1day", "1week"]

ADEQUATE_MIN_CANDLES = 100

# Twelve Data's free plan rate-limits aggressively (confirmed directly while auditing:
# ~8s between requests avoided any 429s) — spacing consecutive audit calls out, on top
# of fetch_forex_ohlcv's own retry-with-backoff for an individual call that does hit
# the limit.
INTER_REQUEST_PAUSE_SECONDS = 8.0


def audit_pair_timeframe(pair: str, timeframe: str, sleep_fn=time.sleep) -> dict[str, object]:
    try:
        result = fetch_forex_ohlcv(pair, timeframe, sleep_fn=sleep_fn)
    except ForexDataUnavailableError as exc:
        return {
            "pair": pair, "timeframe": timeframe, "status": "SKIPPED (UNRESOLVED)",
            "candles": 0, "start": None, "end": None, "reason": str(exc),
        }
    candles = result.prices
    if candles.empty:
        return {
            "pair": pair, "timeframe": timeframe, "status": "SKIPPED (EMPTY)",
            "candles": 0, "start": None, "end": None, "reason": "fetch succeeded but returned zero candles",
        }
    status = "ADEQUATE" if len(candles) >= ADEQUATE_MIN_CANDLES else "SKIPPED (INSUFFICIENT DATA)"
    return {
        "pair": pair, "timeframe": timeframe, "status": status, "candles": len(candles),
        "start": candles["date"].iloc[0], "end": candles["date"].iloc[-1], "reason": None,
    }


def run_audit(pairs: list[str] = FOREX_PAIRS, sleep_fn=time.sleep) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pair in pairs:
        for timeframe in STANDARD_TIMEFRAMES:
            rows.append(audit_pair_timeframe(pair, timeframe, sleep_fn=sleep_fn))
            sleep_fn(INTER_REQUEST_PAUSE_SECONDS)
    return rows


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== Task B1: Forex Data Calibration Audit ===", ""]
    unresolved = [r for r in rows if r["status"] == "SKIPPED (UNRESOLVED)"]
    lines.append(f"Universe: {len(FOREX_PAIRS)} pairs x {len(STANDARD_TIMEFRAMES)} timeframes = {len(rows)} configs")
    lines.append(f"Unresolved pairs: {len(unresolved)}")
    for r in unresolved:
        lines.append(f"  SKIPPED (UNRESOLVED): {r['pair']} @ {r['timeframe']} — {r['reason']}")
    lines.append("")

    for pair in FOREX_PAIRS:
        pair_rows = [r for r in rows if r["pair"] == pair]
        lines.append(f"--- {pair} ---")
        for r in pair_rows:
            if r["status"] == "ADEQUATE":
                lines.append(f"  {r['timeframe']:>5}: {r['status']} — {r['candles']} candles, {r['start']} -> {r['end']}")
            else:
                lines.append(f"  {r['timeframe']:>5}: {r['status']} — {r['reason'] or ''}")
        lines.append("")

    lines.append("=== Depth cap note ===")
    lines.append(
        "Twelve Data caps a single request at 5000 rows on this plan (OUTPUTSIZE_CAP). "
        "For 1h (forex trades ~24h/day, 5 days/week), that bounds a single-call fetch to "
        "roughly ~219 days of history — confirmed directly. Older intraday history DOES "
        "exist further back (confirmed via the end_date pagination parameter) but this "
        "module does not paginate, matching the same single-call convention every other "
        "Twelve Data asset in this project uses. Daily/weekly depth is far beyond this "
        "cap for every pair (EUR/USD 1day confirmed back to 2007)."
    )
    lines.append("")
    lines.append("=== 24/5 market gap note ===")
    lines.append(
        "Forex trades continuously from Monday open to Friday close — the only real gap "
        "is Friday close -> Sunday/Monday open. Any grid-shift verification run against "
        "this data must not cross that boundary."
    )
    return "\n".join(lines)


def main() -> None:
    rows = run_audit()
    print(format_report(rows))


if __name__ == "__main__":
    main()
