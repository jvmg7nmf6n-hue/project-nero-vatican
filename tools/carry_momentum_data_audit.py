"""CLI: CARRY_MOMENTUM — data audit (Three New Hypothesis Batch, Hypothesis 2).

Fetches FRED policy-rate/short-yield series for all 8 currencies (see
nero_core/data_sources/fred_rates.py's module docstring for the exact series IDs
and why each was chosen), confirms the 7 Twelve Data forex pairs this strategy
needs are still accessible, and checks whether the 7 pairs' own daily candles
share an exact close_time grid (unlike GOLD/SILVER's own 4-hour offset mismatch)
or need date-based alignment too.

Usage:
    python -m tools.carry_momentum_data_audit
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.fred_rates import FRED_SERIES_BY_CURRENCY, MacroDataUnavailableError, fetch_policy_rate
from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv

PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD"]


def audit_fred_rates() -> list[dict[str, object]]:
    results = []
    for currency in FRED_SERIES_BY_CURRENCY:
        try:
            series, source, freq = fetch_policy_rate(currency, use_cache=False)
            results.append({
                "currency": currency, "ok": True, "source": source, "frequency": freq,
                "observations": len(series), "first_date": str(series.index.min().date()),
                "last_date": str(series.index.max().date()), "last_value": float(series.iloc[-1]),
            })
        except MacroDataUnavailableError as exc:
            results.append({"currency": currency, "ok": False, "error": str(exc)})
    return results


def audit_forex_pairs() -> list[dict[str, object]]:
    results = []
    for pair in PAIRS:
        try:
            result = fetch_forex_ohlcv(pair, "1day")
            results.append({
                "pair": pair, "ok": True, "source": result.source, "candles": len(result.prices),
                "first_date": str(result.prices["date"].min()), "last_date": str(result.prices["date"].max()),
            })
        except ForexDataUnavailableError as exc:
            results.append({"pair": pair, "ok": False, "error": str(exc)})
    return results


def check_calendar_alignment(pair_results: list[dict[str, object]]) -> str:
    """Fetches raw close_time sets for the first 2 successfully-fetched pairs and
    checks whether they share an EXACT close_time grid (all from the same Twelve
    Data vendor, unlike GOLD/SILVER's cross-vendor mismatch)."""
    ok_pairs = [r["pair"] for r in pair_results if r["ok"]]
    if len(ok_pairs) < 2:
        return "insufficient successful fetches to check alignment"
    a = fetch_forex_ohlcv(ok_pairs[0], "1day").prices
    b = fetch_forex_ohlcv(ok_pairs[1], "1day").prices
    exact_match = set(a["close_time"]) & set(b["close_time"])
    return (
        f"{ok_pairs[0]} vs {ok_pairs[1]}: {len(a)} vs {len(b)} candles, "
        f"{len(exact_match)} EXACT close_time matches "
        f"({'aligned, no date-based join needed' if len(exact_match) > min(len(a), len(b)) * 0.9 else 'MISALIGNED -- date-based join needed, like GOLD/SILVER'})"
    )


def format_report(fred_results: list[dict[str, object]], pair_results: list[dict[str, object]], alignment_note: str) -> str:
    lines = ["=== CARRY_MOMENTUM: Data Audit ===", "", "--- FRED policy rates (8 currencies) ---"]
    for r in fred_results:
        if r["ok"]:
            lines.append(
                f"  {r['currency']}: OK {r['source']} freq={r['frequency']} "
                f"N={r['observations']} [{r['first_date']} .. {r['last_date']}] last_value={r['last_value']:.3f}"
            )
        else:
            lines.append(f"  {r['currency']}: BLOCKED — {r['error']}")

    lines.append("")
    lines.append("--- Forex pairs (7 pairs) ---")
    for r in pair_results:
        if r["ok"]:
            lines.append(f"  {r['pair']}: OK {r['source']} N={r['candles']} [{r['first_date']} .. {r['last_date']}]")
        else:
            lines.append(f"  {r['pair']}: BLOCKED — {r['error']}")

    lines.append("")
    lines.append(f"--- Calendar alignment check --- \n  {alignment_note}")

    blocked_fred = [r["currency"] for r in fred_results if not r["ok"]]
    blocked_pairs = [r["pair"] for r in pair_results if not r["ok"]]
    lines.append("")
    if blocked_fred or blocked_pairs:
        lines.append(f"PARTIAL BLOCK: FRED blocked={blocked_fred}, pairs blocked={blocked_pairs}")
    else:
        lines.append("ALL CLEAR: 8/8 FRED currencies, 7/7 forex pairs.")
    return "\n".join(lines)


def main() -> None:
    fred_results = audit_fred_rates()
    pair_results = audit_forex_pairs()
    alignment_note = check_calendar_alignment(pair_results)
    print(format_report(fred_results, pair_results, alignment_note))


if __name__ == "__main__":
    main()
