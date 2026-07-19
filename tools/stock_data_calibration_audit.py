"""Comprehensive Asset Expansion, Part A: Stocks — Task A1 data audit.

Fetches every ticker in the Task A2 universe (SPY, QQQ, IWM index ETFs + 27 liquid
single stocks) at each standard stock timeframe (1h, 4h, 1day, 1week) via
nero_core.data_sources.stock_data.fetch_stock_ohlcv, and reports: per-timeframe
history depth, any ticker that fails to resolve (logged + excluded, never guessed at),
and the permanent survivorship-bias caveat this whole asset class carries.

No synthetic/fabricated data — every number in the report comes from a live fetch.
Run: python -m tools.stock_data_calibration_audit
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.stock_data import StockDataUnavailableError, fetch_stock_ohlcv

INDEX_ETFS = ["SPY", "QQQ", "IWM"]  # bias-free reference set (see module docstring)

STOCK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "NVDA", "META", "NFLX", "AVGO", "ADBE",
    "CRM", "INTU", "SHOP", "PYPL", "XYZ", "ROKU", "TWLO", "ZM", "DDOG", "NET",
    "OKTA", "CRWD", "SNOW", "MSTR", "COIN", "DASH", "UPST",
]

FULL_UNIVERSE = INDEX_ETFS + STOCK_UNIVERSE

STANDARD_TIMEFRAMES = ["1h", "4h", "1day", "1week"]

ADEQUATE_MIN_CANDLES = 100  # below this, a config is unusable for a 70/30 split with a meaningful test half

# A short pause between consecutive live fetches — not part of the retry-with-backoff
# logic (that already exists inside fetch_stock_ohlcv for a single symbol's transient
# failures), just spacing out the audit's ~120 sequential calls so it doesn't itself
# trigger Yahoo's aggressive burst throttling.
INTER_REQUEST_PAUSE_SECONDS = 0.5


def audit_symbol_timeframe(symbol: str, timeframe: str, sleep_fn=time.sleep) -> dict[str, object]:
    """Returns a dict describing one (symbol, timeframe) fetch attempt — never raises;
    a resolution failure is captured as a SKIPPED record, not an exception escaping the
    audit loop (mirrors the metals audit's own per-config resilience)."""
    try:
        result = fetch_stock_ohlcv(symbol, timeframe, sleep_fn=sleep_fn)
    except StockDataUnavailableError as exc:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "SKIPPED (UNRESOLVED)",
            "candles": 0, "start": None, "end": None, "reason": str(exc),
        }
    candles = result.prices
    if candles.empty:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "SKIPPED (EMPTY)",
            "candles": 0, "start": None, "end": None, "reason": "fetch succeeded but returned zero candles",
        }
    status = "ADEQUATE" if len(candles) >= ADEQUATE_MIN_CANDLES else "SKIPPED (INSUFFICIENT DATA)"
    return {
        "symbol": symbol, "timeframe": timeframe, "status": status, "candles": len(candles),
        "start": candles["date"].iloc[0], "end": candles["date"].iloc[-1], "reason": None,
    }


def run_audit(universe: list[str] = FULL_UNIVERSE, sleep_fn=time.sleep) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol in universe:
        for timeframe in STANDARD_TIMEFRAMES:
            rows.append(audit_symbol_timeframe(symbol, timeframe, sleep_fn=sleep_fn))
            sleep_fn(INTER_REQUEST_PAUSE_SECONDS)
    return rows


def format_report(rows: list[dict[str, object]]) -> str:
    lines = ["=== Task A1: Stock Data Calibration Audit ===", ""]
    unresolved = [r for r in rows if r["status"] == "SKIPPED (UNRESOLVED)"]
    lines.append(f"Universe: {len(FULL_UNIVERSE)} symbols x {len(STANDARD_TIMEFRAMES)} timeframes = {len(rows)} configs")
    lines.append(f"Unresolved tickers: {len(unresolved)}")
    for r in unresolved:
        lines.append(f"  SKIPPED (UNRESOLVED): {r['symbol']} @ {r['timeframe']} — {r['reason']}")
    lines.append("")

    for symbol in FULL_UNIVERSE:
        symbol_rows = [r for r in rows if r["symbol"] == symbol]
        tag = "[INDEX ETF, bias-free]" if symbol in INDEX_ETFS else ""
        lines.append(f"--- {symbol} {tag} ---".strip())
        for r in symbol_rows:
            if r["status"] == "ADEQUATE":
                lines.append(f"  {r['timeframe']:>5}: {r['status']} — {r['candles']} candles, {r['start']} -> {r['end']}")
            else:
                lines.append(f"  {r['timeframe']:>5}: {r['status']} — {r['reason'] or ''}")
        lines.append("")

    lines.append("=== Survivorship-bias caveat (permanent, applies to every single-stock result) ===")
    lines.append(
        "yfinance only serves currently-listed tickers. This universe cannot see any "
        "company that was delisted, went bankrupt, or was acquired away — it is "
        "structurally survivor-selected. SPY/QQQ/IWM are the bias-free reference set: "
        "as index funds they always hold whatever is CURRENTLY in the index, so "
        "constituent turnover happens invisibly inside the fund rather than as a "
        "visible delisting. Every single-stock SURVIVED/PROMISING-WATCHLIST result in "
        "Task A2 must be read with this caveat attached — an edge measurable only on "
        "stocks that happened to survive is not the same claim as an edge on GOLD or "
        "BTC, which have no analogous selection filter."
    )
    return "\n".join(lines)


def main() -> None:
    rows = run_audit()
    print(format_report(rows))


if __name__ == "__main__":
    main()
