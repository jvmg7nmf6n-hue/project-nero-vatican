"""Task 5 -- Kill Switch enforcement point, and the orchestrator that ties
Tasks 1-4 together into one run: scanner -> hypothesis_gen -> (frequency gate
+ auto_tester, per hypothesis). `run_pipeline` is the ONE entrypoint every
scheduled/manual invocation of the Research Agent should call.

KILL SWITCH: the very first line of run_pipeline checks
nero_core.research_agent.config.is_enabled(). When RESEARCH_AGENT_ENABLED
isn't set to a truthy value, run_pipeline returns immediately -- no scan, no
LLM call, no candle fetch, no file write, anywhere. Turning the whole pipeline
off/on again needs zero code changes, just the one environment variable. See
test_research_agent_kill_switch.py.

CRITICAL SAFETY: this module (and everything it calls -- scanner, hypothesis_
gen, auto_tester) writes ONLY to docs/site_data/agent_hypotheses.json and
docs/site_data/agent_test_results.json. It never imports
nero_core.execution.live_scheduler and never touches
nero_core.strategies.registry's default_registry -- see
test_research_agent_no_auto_wire.py's HARD TEST.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nero_core.execution.export_candle_data import candle_filename
from nero_core.research_agent import auto_tester, frequency_gate, hypothesis_gen, scanner
from nero_core.research_agent.config import is_enabled
from nero_core.research_agent.scanner import ScanFinding, ScanResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDLES_DIR = REPO_ROOT / "docs" / "site_data" / "candles"
DEFAULT_FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"

CandlesProvider = Callable[[str, str], "pd.DataFrame | None"]


def _load_failure_patterns(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def default_candles_provider(asset: str, timeframe: str, candles_dir: Path = DEFAULT_CANDLES_DIR) -> "pd.DataFrame | None":
    """Loads the already-exported docs/site_data/candles/ file for
    (asset, timeframe) -- the same export scanner.py already reads, using
    export_candle_data's own filename convention (never re-derived). Returns
    None (never fabricated data) if no file exists for this exact pair; the
    pipeline records that hypothesis as `no_candles_available` rather than
    guessing at a price history."""
    path = candles_dir / candle_filename(asset, timeframe)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        rows = data["candles"]
        return pd.DataFrame(
            {
                "close_time": [int(c["time"]) * 1000 for c in rows],
                "close": [float(c["close"]) for c in rows],
                "high": [float(c["high"]) for c in rows],
                "low": [float(c["low"]) for c in rows],
                "volume": [float(c.get("volume") or 0.0) for c in rows],
            }
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


@dataclass(frozen=True)
class PipelineRunResult:
    enabled: bool
    reason: str = ""
    scan_result: ScanResult | None = None
    hypotheses_generated: int = 0
    duplicates_skipped: int = 0
    llm_calls_made: int = 0
    total_llm_cost_usd: float = 0.0
    cost_limit_hit: bool = False
    too_slow_rejected: int = 0
    unmeasurable_rejected: int = 0
    survived: int = 0
    promising_watchlist: int = 0
    died: int = 0
    untestable: int = 0
    no_candles_available: int = 0
    test_results: list = field(default_factory=list)


def run_pipeline(
    api_key: str = "",
    candles_provider: CandlesProvider = default_candles_provider,
    max_calls_per_run: int = hypothesis_gen.DEFAULT_MAX_CALLS_PER_RUN,
    now: datetime | None = None,
) -> PipelineRunResult:
    if not is_enabled():
        return PipelineRunResult(enabled=False, reason="research_agent.enabled is False (RESEARCH_AGENT_ENABLED not set) -- pipeline did nothing")

    now = now or datetime.now(timezone.utc)

    scan_result = scanner.run_scan(now=now)
    all_findings: list[ScanFinding] = (
        scan_result.extreme_zscore
        + scan_result.regime_transitions
        + scan_result.correlation_breakdowns
        + scan_result.low_strategy_coverage
    )

    failure_patterns = _load_failure_patterns(DEFAULT_FAILURE_PATTERNS_PATH)
    existing_hypotheses = hypothesis_gen.load_existing_hypotheses()
    generation = hypothesis_gen.generate_hypotheses(
        all_findings, failure_patterns, api_key, existing_hypotheses, max_calls_per_run, now
    )
    hypothesis_gen.persist_hypotheses(generation.hypotheses)

    too_slow = unmeasurable = survived = watchlist = died = untestable = no_candles = 0
    test_results: list[auto_tester.TestResult] = []
    for record in generation.hypotheses:
        candles = candles_provider(record["asset"], record["timeframe"])
        if candles is None or candles.empty:
            no_candles += 1
            continue

        result = auto_tester.test_hypothesis(record, candles, now)
        test_results.append(result)

        if result.frequency_classification == frequency_gate.TOO_SLOW:
            too_slow += 1
        elif result.frequency_classification == frequency_gate.UNMEASURABLE:
            unmeasurable += 1

        if result.verdict == auto_tester.VERDICT_SURVIVED:
            survived += 1
        elif result.verdict == auto_tester.VERDICT_PROMISING_WATCHLIST:
            watchlist += 1
        elif result.verdict == auto_tester.VERDICT_DIED:
            died += 1
        elif result.verdict == auto_tester.VERDICT_UNTESTABLE:
            untestable += 1

    auto_tester.persist_test_results(test_results)

    return PipelineRunResult(
        enabled=True,
        scan_result=scan_result,
        hypotheses_generated=len(generation.hypotheses),
        duplicates_skipped=len(generation.duplicates_skipped),
        llm_calls_made=generation.llm_calls_made,
        total_llm_cost_usd=generation.total_cost_usd,
        cost_limit_hit=generation.cost_limit_hit,
        too_slow_rejected=too_slow,
        unmeasurable_rejected=unmeasurable,
        survived=survived,
        promising_watchlist=watchlist,
        died=died,
        untestable=untestable,
        no_candles_available=no_candles,
        test_results=test_results,
    )
