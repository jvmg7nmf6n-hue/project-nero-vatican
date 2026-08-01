"""CLI: feature/watchlist-candidates-recheck — genuine out-of-sample recheck of
the RMR Variant Research Cycle's 3 real PROMISING-WATCHLIST candidates (all
BTC/1d): RMR_LONG_ONLY_BTC_1D (range-mean-reversion-v1.1.0-long-only, Stage 1),
RMR_CONFIRMATION_BTC_1D (v1.3.0-confirmation, Stage 1), and
RMR_LONG_ONLY_CONFIRMATION_BTC_1D (v1.4.0-long-only-confirmation, Stage 3
Refinement 1). See docs/watchlist_candidates_recheck_task1_scope.md for how
these 3 (not the task brief's originally-named 5, which don't exist anywhere
in this repo) were identified as the real candidates to recheck.

REUSE, NOT REIMPLEMENTATION: `_half_stats` is imported directly from
tools.rmr_variant_research_stage1 (the exact function the original Stage 1/
Stage 3 runs used for indicator enrichment, backtest, bootstrap CI, and
random-entry baseline) — not reimplemented here. `classify_verdict`/
`MIN_SAMPLE_SIZE`/`split_chronological` are the same functions/constants the
original runs used, imported unchanged. See test_classification_path_matches_
the_original_harness in tests/test_watchlist_candidates_recheck.py for a
direct proof this module calls the SAME function objects, not lookalikes.

OUT-OF-SAMPLE WINDOW: the original Stage 1 (commit dd24839, 2026-07-20
04:26:29 +0500 = 2026-07-19 23:26:29 UTC) and Stage 3 (commit 373a8fb,
2026-07-20 04:39:16 +0500 = 2026-07-19 23:39:16 UTC) runs both fetched BTC/1d
data before 2026-07-19 23:59:59 UTC (when that day's daily candle closes) —
so the last CLOSED candle either run could have seen was 2026-07-18's. Every
candle with close_time >= 2026-07-19 00:00:00 UTC is therefore genuinely
untouched by either original run. OUT_OF_SAMPLE_CUTOFF below encodes exactly
that boundary — see select_out_of_sample_candles's own docstring for why NO
pre-cutoff data is used at all, not even for indicator warmup (the task's own
literal wording: "using ONLY data that was NOT part of the window already
tested").

GRID-SHIFT: not run here, deliberately — see
docs/watchlist_candidates_recheck_task1_scope.md's own section on why (BTC/1d
is native daily data in this pipeline, an already-settled structural fact
from the original research, not an unrun gap for these 3 candidates).

CRITICAL SAFETY: writes only to the report path this module's own main()
resolves — never to any shared production ledger. Imports nothing from
nero_core.execution.live_scheduler or nero_core.strategies.registry.

Usage:
    python -m tools.watchlist_candidates_recheck
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.strategies.range_mean_reversion import run_backtest as v1_run_backtest
from nero_core.strategies.range_mean_reversion_confirmation import run_backtest as confirmation_run_backtest
from nero_core.strategies.range_mean_reversion_confirmation import CONFIRMATION_PARAMETERS
from nero_core.strategies.range_mean_reversion_long_only import LONG_ONLY_PARAMETERS
from nero_core.strategies.range_mean_reversion_long_only_confirmation import LONG_ONLY_CONFIRMATION_PARAMETERS
from tools.backtest_statistics import MIN_SAMPLE_SIZE, VERDICT_DIED, VERDICT_PROMISING_WATCHLIST, VERDICT_SURVIVED, classify_verdict
from tools.backtest_train_test_split import split_chronological
from tools.rmr_variant_research_stage1 import _half_stats
from tools.timeframe_data import fetch_timeframe_candles

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "watchlist_candidates_recheck_results.json"

# See module docstring's OUT-OF-SAMPLE WINDOW section for the exact derivation.
OUT_OF_SAMPLE_CUTOFF = datetime(2026, 7, 19, 0, 0, 0, tzinfo=timezone.utc)

VERDICT_UNTESTABLE = "UNTESTABLE"

# (name, params, run_backtest_fn) -- exactly the 3 real candidates identified in
# docs/watchlist_candidates_recheck_task1_scope.md, all BTC/1d.
CANDIDATES = [
    ("RMR_LONG_ONLY_BTC_1D", LONG_ONLY_PARAMETERS, v1_run_backtest),
    ("RMR_CONFIRMATION_BTC_1D", CONFIRMATION_PARAMETERS, confirmation_run_backtest),
    ("RMR_LONG_ONLY_CONFIRMATION_BTC_1D", LONG_ONLY_CONFIRMATION_PARAMETERS, confirmation_run_backtest),
]


def select_out_of_sample_candles(candles: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    """Every row with close_time >= cutoff, and NOTHING before it -- not even
    for indicator warmup. This is deliberate, not an oversight: the task's own
    wording is "using ONLY data that was NOT part of the window already
    tested," with no carve-out for warmup-only use of pre-cutoff data. A
    consequence (not a bug) is that a genuinely short out-of-sample window can
    produce zero indicator-warmed rows at all -- see recheck_candidate's own
    UNTESTABLE handling for exactly that case."""
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    return candles[candles["close_time"] >= cutoff_ms].sort_values("close_time").reset_index(drop=True)


def recheck_candidate(
    name: str, params, run_backtest_fn, full_candles: pd.DataFrame, cutoff: datetime = OUT_OF_SAMPLE_CUTOFF
) -> dict[str, object]:
    """Re-runs the EXACT original harness (_half_stats -> classify_verdict)
    against ONLY the out-of-sample slice. Returns VERDICT_UNTESTABLE (never a
    manual override of SURVIVED/PROMISING-WATCHLIST/DIED -- those three come
    straight from classify_verdict, unmodified) when there is nothing for the
    harness to meaningfully classify: zero out-of-sample candles, or zero
    trades in EITHER half (which, left to classify_verdict alone, would
    silently read as "DIED" -- expectancy_r=0.0 is not > 0 -- when the honest
    reading is "no fresh evidence existed to test," a different claim
    entirely)."""
    oos_candles = select_out_of_sample_candles(full_candles, cutoff)
    if oos_candles.empty:
        return {
            "name": name, "verdict": VERDICT_UNTESTABLE,
            "reason": f"0 candles at/after {cutoff.isoformat()} -- no out-of-sample data exists yet.",
            "oos_candle_count": 0,
        }

    train_raw, test_raw = split_chronological(oos_candles)
    train_stats = _half_stats(train_raw, params, run_backtest_fn)
    test_stats = _half_stats(test_raw, params, run_backtest_fn)

    if train_stats["trades"] == 0 and test_stats["trades"] == 0:
        return {
            "name": name, "verdict": VERDICT_UNTESTABLE,
            "reason": (
                f"{len(oos_candles)} out-of-sample candles ({cutoff.date()} onward; "
                f"train={len(train_raw)}, test={len(test_raw)} raw candles) produced 0 trades in "
                f"either half -- almost certainly below this strategy family's indicator warmup "
                f"floor (sma20/bb needs 20 candles, adx14's double-smoothing needs ~28), since no "
                f"pre-cutoff data was used for warmup (see select_out_of_sample_candles's own "
                f"docstring). Reported as UNTESTABLE rather than letting classify_verdict silently "
                f"read 0 trades as a negative (DIED) result."
            ),
            "oos_candle_count": len(oos_candles),
            "train": train_stats, "test": test_stats,
        }

    verdict = classify_verdict(
        {"expectancy_r": train_stats["expectancy_r"], "trades": train_stats["trades"], "ci": train_stats["ci"]},
        {"expectancy_r": test_stats["expectancy_r"], "trades": test_stats["trades"], "ci": test_stats["ci"]},
        min_sample_size=MIN_SAMPLE_SIZE,
    )
    return {
        "name": name, "verdict": verdict, "oos_candle_count": len(oos_candles),
        "train": train_stats, "test": test_stats,
    }


def _stats_to_jsonable(stats: dict | None) -> dict | None:
    if stats is None:
        return None
    out = dict(stats)
    if out.get("ci") is not None:
        out["ci"] = asdict(out["ci"])
    if out.get("baseline") is not None:
        out["baseline"] = asdict(out["baseline"])
    return out


def run_all() -> dict[str, dict]:
    client = MarketDataClient()
    try:
        btc, method = fetch_timeframe_candles(client, "BTC", "24h")
    except MarketDataUnavailableError as exc:
        return {name: {"name": name, "verdict": VERDICT_UNTESTABLE, "reason": f"BTC/1d fetch failed: {exc}"} for name, _, _ in CANDIDATES}

    print(f"BTC/1d: {len(btc)} candles fetched via {method}")
    results: dict[str, dict] = {}
    for name, params, run_backtest_fn in CANDIDATES:
        result = recheck_candidate(name, params, run_backtest_fn, btc)
        results[name] = result
        print(f"{name}: verdict={result['verdict']} oos_candles={result.get('oos_candle_count')}")
        if "reason" in result:
            print(f"  {result['reason']}")
    return results


def persist_report(results: dict[str, dict], path: Path = DEFAULT_REPORT_PATH) -> None:
    payload = {
        "out_of_sample_cutoff": OUT_OF_SAMPLE_CUTOFF.isoformat(),
        "candidates": {
            name: {
                "name": r["name"], "verdict": r["verdict"], "oos_candle_count": r.get("oos_candle_count"),
                "reason": r.get("reason"),
                "train": _stats_to_jsonable(r.get("train")), "test": _stats_to_jsonable(r.get("test")),
            }
            for name, r in results.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    results = run_all()
    persist_report(results)
    print(f"\nreport written to {DEFAULT_REPORT_PATH}")
