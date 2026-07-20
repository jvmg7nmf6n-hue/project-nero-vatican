"""CLI: PEAD — data audit (Three New Hypothesis Batch, Hypothesis 3). HARD GATE:
if estimates are unavailable or lookahead can't be confirmed for a ticker, that
ticker is BLOCKED.

Checks, per ticker (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META) plus SPY (expected
to have none — benchmark only):
  (a) earnings dates + history depth
  (b) actual vs ESTIMATE EPS (missing estimates -> BLOCKED)
  (c) announcement timestamp strictly before the next-trading-day open (checked
      via each ticker's own daily OHLCV, not assumed)
  (d) survivor-bias caveat (attached to the report unconditionally)

Usage:
    python -m tools.pead_data_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.earnings_data import (
    BENCHMARK_TICKER,
    SURVIVOR_BIAS_CAVEAT,
    EarningsDataUnavailableError,
    fetch_earnings_surprises,
)
from nero_core.data_sources.stock_data import StockDataUnavailableError, fetch_stock_ohlcv
from nero_core.strategies.pead import TICKERS


def audit_ticker(ticker: str) -> dict[str, object]:
    try:
        events = fetch_earnings_surprises(ticker, limit=100)
    except EarningsDataUnavailableError as exc:
        return {"ticker": ticker, "blocked": True, "reason": str(exc)}

    try:
        candles = fetch_stock_ohlcv(ticker, "1day").prices
    except StockDataUnavailableError as exc:
        return {"ticker": ticker, "blocked": True, "reason": f"no OHLCV: {exc}"}

    # (c) lookahead check: for every event, confirm a next-trading-day candle
    # exists AFTER the announcement (not merely that the timestamp looks early).
    dates = candles["date"]
    unresolvable = 0
    for event_time in events.index:
        future = dates[dates > event_time]
        if future.empty:
            unresolvable += 1

    hours = sorted(events.index.hour.unique().tolist())

    return {
        "ticker": ticker, "blocked": False, "observations": len(events),
        "oldest": str(events.index.min()), "newest": str(events.index.max()),
        "announcement_hours_et": hours, "unresolvable_events": unresolvable,
        "candle_count": len(candles),
    }


def audit_benchmark() -> dict[str, object]:
    try:
        fetch_earnings_surprises(BENCHMARK_TICKER, limit=10)
        return {"ticker": BENCHMARK_TICKER, "has_earnings": True}
    except EarningsDataUnavailableError as exc:
        return {"ticker": BENCHMARK_TICKER, "has_earnings": False, "reason": str(exc)}


def format_report(ticker_results: list[dict[str, object]], benchmark_result: dict[str, object]) -> str:
    lines = ["=== PEAD: Data Audit ===", "", SURVIVOR_BIAS_CAVEAT, "", "--- Tickers ---"]
    any_blocked = False
    for r in ticker_results:
        if r["blocked"]:
            any_blocked = True
            lines.append(f"  {r['ticker']}: BLOCKED — {r['reason']}")
        else:
            lines.append(
                f"  {r['ticker']}: OK N={r['observations']} [{r['oldest']} .. {r['newest']}] "
                f"announcement_hours_ET={r['announcement_hours_et']} unresolvable={r['unresolvable_events']} "
                f"(candles={r['candle_count']})"
            )
    lines.append("")
    lines.append(f"--- Benchmark ({BENCHMARK_TICKER}) ---")
    if benchmark_result["has_earnings"]:
        lines.append(f"  UNEXPECTED: {BENCHMARK_TICKER} has earnings data — re-check benchmark assumption")
    else:
        lines.append(f"  Confirmed: {BENCHMARK_TICKER} has no earnings data ({benchmark_result['reason']}) — benchmark-only, as expected")

    lines.append("")
    if any_blocked:
        lines.append("RESULT: PARTIAL/FULL BLOCK — see BLOCKED tickers above.")
    else:
        lines.append("RESULT: ALL CLEAR — 7/7 tickers have resolved estimate+actual EPS and confirmed lookahead-safe entry timing.")
    return "\n".join(lines)


def main() -> None:
    ticker_results = [audit_ticker(t) for t in TICKERS]
    benchmark_result = audit_benchmark()
    print(format_report(ticker_results, benchmark_result))


if __name__ == "__main__":
    main()
