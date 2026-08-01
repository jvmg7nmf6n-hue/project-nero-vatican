"""CLI: feature/philosophy-hypotheses-live-test -- first real frequency_gate/
auto_tester run for the 15 philosophy hypotheses expressed on main
(RMR_LONG_ONLY_EURUSD_4H, WISE_MAN_HOLD_V1-V10, ADX_RANGE_V1-V4). Every one of
these has only ever been PARSE-validated (test_research_agent_philosophy_
hypotheses_parsing.py / _variants.py) or unit-tested against synthetic candle
fixtures (test_research_agent_exitplan_dynamic_exit.py) -- none had been run
through the real gate+harness against real market data before this branch.

REUSABLE MANUAL-SUBMISSION MECHANISM -- FINDING: no such function existed
anywhere in this codebase before this file. tools.rmr_variant_research_
stage1.py looks adjacent (it also does a "fetch real data, backtest, report"
cycle for an RMR variant) but it drives a COMPLETELY different code path --
nero_core.strategies.range_mean_reversion's own run_backtest/add_indicators,
never nero_core.research_agent.frequency_gate.measure_entry_frequency or
nero_core.research_agent.auto_tester.test_hypothesis, which is what every
`structured_entry_rule`/`structured_exit_plan` hypothesis dict (the ONLY shape
RMR_LONG_ONLY_EURUSD_4H and all 14 philosophy variants are expressed in) needs.
The only prior callers of measure_entry_frequency/test_hypothesis with REAL
(non-fixture) data are nero_core.research_agent.pipeline.run_pipeline (via its
default_candles_provider, which reads the docs/site_data/candles/ export --
capped at 200 rows, ~33 days at 4h, per nero_core.execution.export_candle_
data.CANDLE_COUNT -- too short a span to trust an annualized frequency
measurement against) and this project's test suite (synthetic fixtures only).
So: `fetch_full_history` + `run_hypothesis_live` below ARE that reusable
mechanism, built once here and intended for reuse by any future manual
philosophy-hypothesis submission -- not a one-off inlined per hypothesis.

DATA SOURCE: fetches FULL native history directly (not the capped export),
the same convention tools.rmr_variant_research_stage1.py already established
for a fresh manual submission -- fetch_forex_ohlcv for a "X/Y" pair,
fetch_timeframe_candles (Binance-native where available) otherwise. BTC/4h:
~19,600 native candles back to 2017. EUR/USD/4h: ~5,000 native candles back to
2023 (Twelve Data's own plan-level history limit for this pair/interval, not
an artificial cap this script imposes).

GRID-SHIFT (H6 precedent, tools.grid_shift_robustness_audit.py): that tool's
own OFFSETS_BY_TIMEFRAME only covers 12h/2h, not 4h. This project's own
precedent for choosing offsets is "test every distinct UTC-clock alignment a
grid can have" (2h tested both of its 2 possible offsets; 12h tested 3 of its
12). A 4h grid has exactly 4 distinct possible alignments (0,1,2,3 -- offset
4 wraps back to 0), so GRID_OFFSETS_4H tests all 4, the direct analogue of the
2h precedent's "all of them" rather than a subset.

CRITICAL SAFETY: this module writes ONLY to the report path passed to
main() (default docs/philosophy_hypotheses_live_test_results.json) -- it
deliberately does NOT call auto_tester.persist_test_results (which would
append into docs/site_data/agent_test_results.json, the SHARED ledger the
real scanner/LLM-driven pipeline reads/writes). These are manually-authored,
hand-submitted hypotheses, not scanner output -- commingling them into the
production ledger would misrepresent their provenance to any future reader of
that file. It imports nothing from nero_core.execution.live_scheduler or
nero_core.strategies.registry -- see test_philosophy_hypotheses_live_test.py's
own no-auto-wire check.

Usage:
    python -m tools.philosophy_hypotheses_live_test
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nero_core.data_sources.candle_resampling import resample_hourly_to_grid
from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.research_agent import auto_tester, frequency_gate
from tools.timeframe_data import fetch_timeframe_candles

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "philosophy_hypotheses_live_test_results.json"

GRID_OFFSETS_4H = [0, 1, 2, 3]
HOURLY_FETCH_CANDLES = 100_000  # far past any of these assets' listing/plan history


def fetch_full_history(asset: str, timeframe: str, client: MarketDataClient) -> pd.DataFrame:
    """Full native history for `asset`/`timeframe` -- forex pairs ("EUR/USD") via
    fetch_forex_ohlcv, everything else via fetch_timeframe_candles. Raises
    ForexDataUnavailableError/MarketDataUnavailableError on failure -- never a
    fabricated substitute (matches every other tool in this project)."""
    if "/" in asset:
        return fetch_forex_ohlcv(asset, timeframe).prices
    candles, _method = fetch_timeframe_candles(client, asset, timeframe)
    return candles


def fetch_hourly_for_grid(asset: str, client: MarketDataClient) -> pd.DataFrame:
    if "/" in asset:
        return fetch_forex_ohlcv(asset, "1h").prices
    return client.load_intraday(asset, interval="1h", candles=HOURLY_FETCH_CANDLES).prices


def build_4h_grids(asset: str, client: MarketDataClient) -> dict[str, pd.DataFrame]:
    """Native 4h grid plus every offset+1h/2h/3h resampled grid, built from the
    same underlying 1h source -- see module docstring's GRID-SHIFT section."""
    hourly = fetch_hourly_for_grid(asset, client)
    grids: dict[str, pd.DataFrame] = {}
    for offset in GRID_OFFSETS_4H:
        label = "native (offset+0h)" if offset == 0 else f"offset+{offset}h"
        grids[label] = resample_hourly_to_grid(hourly, 4, offset)
    return grids


def run_hypothesis_live(
    hypothesis: dict,
    candles: pd.DataFrame,
    now: datetime,
    client: MarketDataClient | None = None,
    run_grid_shift: bool = True,
) -> dict:
    """The reusable per-hypothesis submission: frequency_gate + full harness in
    one call (auto_tester.test_hypothesis already runs the gate as its own
    first step -- see that module's docstring), then, ONLY for a hypothesis
    that cleared FAST/VIABLE, a grid-shift re-run across all 4 possible 4h
    alignments. Returns {"result": TestResult, "grid_shift": {label:
    TestResult} | None}."""
    result = auto_tester.test_hypothesis(hypothesis, candles, now)
    grid_shift: dict[str, auto_tester.TestResult] | None = None
    if run_grid_shift and result.frequency_classification in (frequency_gate.FAST, frequency_gate.VIABLE):
        client = client or MarketDataClient()
        grids = build_4h_grids(hypothesis["asset"], client)
        grid_shift = auto_tester.run_grid_shift_check(hypothesis, grids, now)
    return {"result": result, "grid_shift": grid_shift}


def _to_jsonable(run: dict) -> dict:
    result: auto_tester.TestResult = run["result"]
    grid_shift = run["grid_shift"]
    return {
        "result": result.to_dict(),
        "grid_shift": None if grid_shift is None else {label: r.to_dict() for label, r in grid_shift.items()},
    }


def persist_report(report: dict, path: Path = DEFAULT_REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str))


# ---------------------------------------------------------------------------
# THE PRE-REGISTERED SET -- 15 named philosophy hypotheses (1 RMR + 10
# WISE_MAN_HOLD + 4 ADX_RANGE), reduced to the distinct rule-configurations
# actually needing a fresh run once the two KNOWN duplicate clusters are
# collapsed (see each entry's "aliases"). No tuning/adding based on interim
# results -- this list is fixed before any of it runs, per the branch's own
# no-p-hacking instruction.
# ---------------------------------------------------------------------------

RANGE_ENTRY_RULE = {
    "conditions": [
        {"field": "close", "op": "lt", "compare_to_field": "bb_lower"},
        {"field": "adx14", "op": "lt", "value": 25.0},
    ],
}

# WISE_MAN_HOLD family: (canonical_name, aliases, target_pct_of_entry, stop_pct_of_entry).
# The V2/V9/WISE_MAN_ASYMMETRIC_HOLD triple is ONE numerically identical ExitPlan
# (target 1%, stop 3%) -- run once under the ORIGINAL name, aliases list the other two.
_WISE_MAN_HOLD_RUNS = [
    ("WISE_MAN_HOLD_V1", [], 0.008, 0.040),
    ("WISE_MAN_ASYMMETRIC_HOLD", ["WISE_MAN_HOLD_V2", "WISE_MAN_HOLD_V9"], 0.010, 0.030),
    ("WISE_MAN_HOLD_V3", [], 0.015, 0.030),
    ("WISE_MAN_HOLD_V4", [], 0.020, 0.020),
    ("WISE_MAN_HOLD_V5", [], 0.030, 0.015),
    ("WISE_MAN_HOLD_V6", [], 0.010, 0.010),
    ("WISE_MAN_HOLD_V7", [], 0.010, 0.015),
    ("WISE_MAN_HOLD_V8", [], 0.010, 0.020),
    ("WISE_MAN_HOLD_V10", [], 0.010, 0.040),
]

# ADX_RANGE family: (canonical_name, aliases, adx14 entry threshold).
# V2 (adx14 < 20) is rule-for-rule identical to the already-built
# ADX_GATED_RANGE_PERSISTENCE -- run once under ADX_RANGE_V2's own name, alias
# lists the original.
_ADX_RANGE_RUNS = [
    ("ADX_RANGE_V1", [], 15.0),
    ("ADX_RANGE_V2", ["ADX_GATED_RANGE_PERSISTENCE"], 20.0),
    ("ADX_RANGE_V3", [], 25.0),
    ("ADX_RANGE_V4", [], 30.0),
]

ADX_RANGE_PROXY_NOTE = (
    "PROXY_TEST result, NOT a real trading edge -- target_r_multiple=50.0 against "
    "stop_atr_multiple=2.0 is a practically unreachable placeholder target. Every "
    "resolved trade under this plan should exit via REGIME_BREAK/SL/TIME, never "
    "TARGET. Survival here means 'the regime-break/time-cap exits fire in a "
    "statistically distinguishable pattern vs. random', NOT 'this makes money'."
)


def build_hypothesis_set() -> list[dict]:
    """Returns the full pre-registered list of {name, aliases, asset, timeframe,
    is_proxy, structured_entry_rule, structured_exit_plan} records -- the SAME
    list every run of this script executes, in the SAME order, unconditionally
    of any prior result (no interim tuning)."""
    records: list[dict] = []

    records.append({
        "name": "RMR_LONG_ONLY_EURUSD_4H",
        "aliases": [],
        "asset": "EUR/USD",
        "timeframe": "4h",
        "is_proxy": False,
        "structured_entry_rule": RANGE_ENTRY_RULE,
        "structured_exit_plan": {
            "stop_atr_multiple": 2.0,
            "dynamic_target_condition": {"field": "close", "op": "gte", "compare_to_field": "ma20"},
            "regime_break_condition": {"field": "adx14", "op": "gte", "value": 28.0},
            "regime_break_consecutive_bars": 2,
        },
    })

    for name, aliases, target_pct, stop_pct in _WISE_MAN_HOLD_RUNS:
        records.append({
            "name": name,
            "aliases": aliases,
            "asset": "BTC",
            "timeframe": "4h",
            "is_proxy": False,
            "structured_entry_rule": RANGE_ENTRY_RULE,
            "structured_exit_plan": {"stop_pct_of_entry": stop_pct, "target_pct_of_entry": target_pct},
        })

    for name, aliases, threshold in _ADX_RANGE_RUNS:
        records.append({
            "name": name,
            "aliases": aliases,
            "asset": "BTC",
            "timeframe": "4h",
            "is_proxy": True,
            "proxy_note": ADX_RANGE_PROXY_NOTE,
            "structured_entry_rule": {"conditions": [{"field": "adx14", "op": "lt", "value": threshold}]},
            "structured_exit_plan": {
                "stop_atr_multiple": 2.0,
                "target_r_multiple": 50.0,
                "regime_break_condition": {"field": "adx14", "op": "gte", "value": 25.0},
                "regime_break_consecutive_bars": 1,
                "max_holding_hours": 480.0,
            },
        })

    return records


def main(report_path: Path = DEFAULT_REPORT_PATH) -> dict:
    client = MarketDataClient()
    now = datetime.now(timezone.utc)
    records = build_hypothesis_set()

    print(f"=== philosophy_hypotheses_live_test: {len(records)} distinct runs, generated_at/now={now.isoformat()} ===", flush=True)

    history_cache: dict[tuple[str, str], pd.DataFrame] = {}
    runs: dict[str, dict] = {}

    def _write_report() -> dict:
        report = {
            "generated_at": now.isoformat(),
            "candle_source": {f"{a}/{t}": ("live-fetched, see run log" if history_cache.get((a, t)) is not None else "unavailable") for a, t in history_cache},
            "candle_counts": {f"{a}/{t}": (0 if history_cache.get((a, t)) is None else len(history_cache[(a, t)])) for a, t in history_cache},
            "runs": runs,
        }
        persist_report(report, report_path)
        return report

    for idx, record in enumerate(records, start=1):
        key = (record["asset"], record["timeframe"])
        if key not in history_cache:
            print(f"[{idx}/{len(records)}] fetching full history for {key[0]}/{key[1]} ...", flush=True)
            try:
                history_cache[key] = fetch_full_history(record["asset"], record["timeframe"], client)
                print(f"  -> {len(history_cache[key])} candles", flush=True)
            except (ForexDataUnavailableError, MarketDataUnavailableError) as exc:
                print(f"  FETCH FAILED: {exc}", flush=True)
                history_cache[key] = None
        candles = history_cache[key]
        if candles is None:
            print(f"[{idx}/{len(records)}] {record['name']}: SKIPPED -- no candle data available", flush=True)
            continue

        hypothesis = {
            "hypothesis_name": record["name"],
            "asset": record["asset"],
            "timeframe": record["timeframe"],
            "generated_at": now.isoformat(),
            "structured_entry_rule": record["structured_entry_rule"],
            "structured_exit_plan": record["structured_exit_plan"],
        }
        print(f"[{idx}/{len(records)}] {record['name']}: running frequency_gate + harness ...", flush=True)
        t_start = datetime.now(timezone.utc)
        run = run_hypothesis_live(hypothesis, candles, now, client=client)
        elapsed = (datetime.now(timezone.utc) - t_start).total_seconds()
        result = run["result"]
        grid_note = f" grid_shift={len(run['grid_shift'])} offsets" if run["grid_shift"] else ""
        print(
            f"[{idx}/{len(records)}] {record['name']} (aliases={record['aliases']}) done in {elapsed:.1f}s: "
            f"freq={result.frequency_classification} verdict={result.verdict}{grid_note} -- {result.reason}",
            flush=True,
        )
        runs[record["name"]] = {
            "aliases": record["aliases"],
            "asset": record["asset"],
            "timeframe": record["timeframe"],
            "is_proxy": record["is_proxy"],
            "proxy_note": record.get("proxy_note"),
            **_to_jsonable(run),
        }
        _write_report()  # incremental persistence -- survives an interrupted run
        print(f"  -> report updated at {report_path} ({len(runs)}/{len(records)} runs so far)", flush=True)

    report = _write_report()
    print(f"=== DONE. report written to {report_path} ===", flush=True)
    return report


if __name__ == "__main__":
    main()
