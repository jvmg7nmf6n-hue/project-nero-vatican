"""CLI: H5 hypothesis — does BTC lead any of the 6 alts (ETH, SOL, BNB, XRP, DOGE,
NEAR) at 12h and 24h, per the existing Granger causality test
(nero_core.quant.quant_intelligence.granger_causality_pvalues), run on LOG RETURNS (not
raw prices — stationarity), max lag 5 candles? 12 pair-tests total (6 alts x 2
timeframes).

Bonferroni correction: with 12 simultaneous tests, the corrected significance threshold
is 0.05 / 12 ~= 0.004167. Every pair's raw p-value and best lag is reported regardless
of significance — a null result is a valid, reportable result, not something to hide.

If (and only if) any pair passes the corrected threshold, this script also builds
LEADLAG_FOLLOW v1.0.0 for those specific pairs (see nero_core.strategies.leadlag_follow,
created only when needed). If nothing passes, that is reported plainly and no strategy
is built — this file alone does not create one.

No synthetic/fabricated price data is ever used — if a fetch fails, that pair is
reported as SKIPPED with the reason, not silently substituted.

Usage:
    python tools/granger_leadlag_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.quant.quant_intelligence import granger_causality_pvalues, log_returns
from nero_core.strategies.cointegration_pairs import align_pair_candles
from tools.timeframe_data import fetch_timeframe_candles

ALTS = ["ETH", "SOL", "BNB", "XRP", "DOGE", "NEAR"]
TIMEFRAMES = ["12h", "24h"]
MAX_LAG = 5
NUM_TESTS = len(ALTS) * len(TIMEFRAMES)
BONFERRONI_THRESHOLD = 0.05 / NUM_TESTS


def run_pair_test(client: MarketDataClient, alt: str, timeframe: str) -> dict[str, object]:
    try:
        btc_candles, btc_method = fetch_timeframe_candles(client, "BTC", timeframe)
        alt_candles, alt_method = fetch_timeframe_candles(client, alt, timeframe)
    except MarketDataUnavailableError as exc:
        return {"alt": alt, "timeframe": timeframe, "status": "SKIPPED", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"alt": alt, "timeframe": timeframe, "status": "FAILED", "reason": f"{exc.__class__.__name__}: {exc}"}

    aligned = align_pair_candles(btc_candles, alt_candles, "BTC", alt)
    if aligned.empty:
        return {"alt": alt, "timeframe": timeframe, "status": "SKIPPED", "reason": "no overlapping candles between BTC and " + alt}

    btc_returns = log_returns(aligned["BTC_close"])
    alt_returns = log_returns(aligned[f"{alt}_close"])
    returns = pd.concat({"BTC": btc_returns, alt: alt_returns}, axis=1).dropna()

    result = granger_causality_pvalues(returns, cause="BTC", effect=alt, max_lag=MAX_LAG)
    if isinstance(result, str):
        return {"alt": alt, "timeframe": timeframe, "status": result, "candle_count": len(aligned)}

    best_lag = min(result, key=result.get)
    best_pvalue = result[best_lag]
    return {
        "alt": alt,
        "timeframe": timeframe,
        "status": "ok",
        "candle_count": len(aligned),
        "pvalues_by_lag": result,
        "best_lag": best_lag,
        "best_pvalue": best_pvalue,
        "significant": best_pvalue < BONFERRONI_THRESHOLD,
    }


def run_all_tests(client: MarketDataClient) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for timeframe in TIMEFRAMES:
        for alt in ALTS:
            print(f"BTC -> {alt} / {timeframe}: testing...")
            result = run_pair_test(client, alt, timeframe)
            results.append(result)
            if result["status"] == "ok":
                print(
                    f"  best_lag={result['best_lag']} best_pvalue={result['best_pvalue']:.5f} "
                    f"significant(Bonferroni)={result['significant']}"
                )
            else:
                print(f"  {result['status']} — {result.get('reason', '')}")
    return results


def format_report(results: list[dict[str, object]]) -> str:
    lines: list[str] = [
        f"Granger causality: BTC -> alt, log returns, max_lag={MAX_LAG}, {NUM_TESTS} pair-tests",
        f"Bonferroni-corrected significance threshold: 0.05 / {NUM_TESTS} = {BONFERRONI_THRESHOLD:.6f}",
        "",
        f"{'Alt':<6}{'TF':<6}{'Status':<10}{'N':>6}{'BestLag':>9}{'BestP':>12}{'Significant':>14}",
        "-" * 63,
    ]
    for r in results:
        if r["status"] != "ok":
            lines.append(f"{r['alt']:<6}{r['timeframe']:<6}{r['status']:<10}{'':>6}{'':>9}{'':>12}{'':>14}  ({r.get('reason', '')})")
            continue
        lines.append(
            f"{r['alt']:<6}{r['timeframe']:<6}{'ok':<10}{r['candle_count']:>6}{r['best_lag']:>9}"
            f"{r['best_pvalue']:>12.6f}{str(r['significant']):>14}"
        )
    lines.append("-" * 63)

    significant = [r for r in results if r.get("significant")]
    lines.append("")
    if significant:
        lines.append(f"{len(significant)} pair(s) passed the Bonferroni-corrected threshold:")
        for r in significant:
            lines.append(f"  BTC -> {r['alt']} @ {r['timeframe']}, lag={r['best_lag']}, p={r['best_pvalue']:.6f}")
        lines.append("LEADLAG_FOLLOW v1.0.0 will be built for these pair(s).")
    else:
        lines.append("No pair passed the Bonferroni-corrected threshold. This is a valid null result:")
        lines.append("no LEADLAG_FOLLOW strategy is built. H5 is not supported by this test.")
    return "\n".join(lines)


def main() -> None:
    client = MarketDataClient()
    results = run_all_tests(client)
    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
