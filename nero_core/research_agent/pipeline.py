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

CLI ENTRYPOINT (added 2026-07-30 -- the gap flagged in docs/research_agent_
real_run_followup.md): `main()` is the FIRST place in this whole package that
reads ANTHROPIC_API_KEY from the environment. Every other function here takes
`api_key` as an explicit parameter and never touches os.environ itself (by
design -- keeps everything else here pure and trivially testable without an
env var). `main()` closes that gap the same way nero_core.execution.
live_scheduler.py already does for news_sentiment_llm: `os.getenv(
"ANTHROPIC_API_KEY", "")` read ONCE, then passed explicitly as `api_key=`.
The value is never printed, logged, or included in any print() argument --
see test_research_agent_secret_handling.py's ast-based check, which verifies
that precisely (not "no print() calls at all" -- a print of aggregate,
non-secret counts, as main() does below, is fine and matches this project's
own nero_core.execution.export_quant_metrics.main() convention).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from nero_core.asset_universe import APPROVED_EVALUATION_UNIVERSE, APPROVED_RESEARCH_UNIVERSE
from nero_core.execution.export_candle_data import candle_filename
from nero_core.research_agent import auto_tester, frequency_gate, hypothesis_gen, performance, scanner
from nero_core.research_agent.config import is_enabled
from nero_core.research_agent.scanner import ScanFinding, ScanResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDLES_DIR = REPO_ROOT / "docs" / "site_data" / "candles"
# Full-history research export -- see nero_core.eve.pipeline's own identical
# constant/docstring (this module's default_candles_provider now applies the
# SAME refuse-don't-degrade discipline Eve's already had since
# docs/investigations/eve_engine_v1_report.md's silent-fallback-trap fix).
# Adam's own scanner.py (candle-freshness/regime-baseline reads) is
# UNTOUCHED by this constant -- only default_candles_provider, the function
# auto_tester.test_hypothesis's real backtest calls actually use, changes.
DEFAULT_RESEARCH_CANDLES_DIR = REPO_ROOT / "docs" / "research_data" / "candles"
DEFAULT_FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"

CandlesProvider = Callable[[str, str], "pd.DataFrame | None"]


class DataSourceRefusedError(Exception):
    """Raised by default_candles_provider when asked for an (asset,
    timeframe) pair it refuses to silently degrade for -- mirrors
    nero_core.eve.scoring.DataSourceRefusedError exactly (same reasoning,
    independently defined here rather than imported, so Adam and Eve stay
    two fully independent systems with no cross-import between them). Before
    this existed, Adam's default_candles_provider read ONLY the 200-row site
    display export -- the exact data source docs/investigations/
    eve_engine_v1_report.md already showed leaves ma200 NaN everywhere but
    the last row and never reaches MIN_SAMPLE_SIZE out-of-sample trades.
    run_pipeline catches this specific exception per-hypothesis and records
    an explicit, grep-able refusal (data_source_refused) instead of either a
    silent substitution or a null result indistinguishable from "no candle
    data was available anywhere for this pair."."""


def _load_failure_patterns(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        # Loud, not silent: a corrupted failure_patterns.json previously meant
        # every prompt silently lost its "known dead mechanisms" list, risking
        # a regenerated-and-already-killed hypothesis with zero indication why.
        print(
            f"ERROR: {path} is corrupted (JSONDecodeError: {exc}) -- proceeding with an EMPTY "
            f"known-dead-mechanisms list this run. Every prompt this run will be missing that "
            f"context until the file is restored.",
            file=sys.stderr,
        )
        return []
    return data if isinstance(data, list) else []


def _read_candles_file(path: Path) -> "pd.DataFrame | None":
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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"ERROR: {path} EXISTS but is malformed ({exc.__class__.__name__}: {exc}) -- "
            f"treating as no candle data available. This is a different, worse problem than a "
            f"missing file (a broken export, not an unexported asset) and should be investigated.",
            file=sys.stderr,
        )
        return None


def default_candles_provider(
    asset: str,
    timeframe: str,
    candles_dir: Path = DEFAULT_CANDLES_DIR,
    research_candles_dir: Path = DEFAULT_RESEARCH_CANDLES_DIR,
) -> "pd.DataFrame | None":
    """REFUSES (raises DataSourceRefusedError) rather than degrades -- mirrors
    nero_core.eve.pipeline.default_candles_provider exactly. An (asset,
    timeframe) pair in APPROVED_EVALUATION_UNIVERSE (a pre-existing live
    strategy being backtested, never a hypothesis-search candidate -- see
    nero_core.asset_universe) or outside APPROVED_RESEARCH_UNIVERSE entirely,
    or one inside it whose research export file is missing on disk, never
    falls back to `candles_dir` (the website's 200-row display export) --
    that silent substitution was this function's ORIGINAL behavior, and is
    exactly the failure mode this branch's own random-baseline investigation
    found (see docs/investigations/eve_engine_v1_report.md). `candles_dir`
    is kept as a parameter (unused in the success path) only so existing
    callers/tests that pass it explicitly don't need a signature change.

    On success, the returned frame is tagged (`.attrs["data_source"]` /
    `.attrs["row_count"]`), matching Eve's own convention, so a caller can
    record what was actually used per hypothesis, not just infer it."""
    if (asset, timeframe) in APPROVED_EVALUATION_UNIVERSE:
        raise DataSourceRefusedError(
            f"{asset}/{timeframe} is in APPROVED_EVALUATION_UNIVERSE, not APPROVED_RESEARCH_UNIVERSE -- "
            f"evaluation-only pairs (pre-existing live strategies being backtested, never a hypothesis-"
            f"search candidate) are never available for Adam's hypothesis scoring, by design. "
            f"See nero_core.asset_universe."
        )
    if (asset, timeframe) not in APPROVED_RESEARCH_UNIVERSE:
        raise DataSourceRefusedError(
            f"{asset}/{timeframe} is not in Adam's APPROVED_RESEARCH_UNIVERSE "
            f"{sorted(APPROVED_RESEARCH_UNIVERSE)} -- refusing to silently fall back to the "
            f"{candles_dir.name if hasattr(candles_dir, 'name') else candles_dir} site display export "
            f"(200 rows, no random baseline ever computed for this pair)."
        )
    research_frame = _read_candles_file(research_candles_dir / candle_filename(asset, timeframe))
    if research_frame is None:
        raise DataSourceRefusedError(
            f"{asset}/{timeframe} is in APPROVED_RESEARCH_UNIVERSE but its research export file is "
            f"missing at {research_candles_dir / candle_filename(asset, timeframe)} -- refusing to "
            f"silently fall back to the site display export."
        )
    research_frame.attrs["data_source"] = "research_export"
    research_frame.attrs["row_count"] = len(research_frame)
    return research_frame


# status distinguishes "ran fine" from "something failed" -- the exact
# distinction the run summary previously couldn't make (a 401, a network
# failure, and a genuinely-uneventful run all printed identically). See
# run_pipeline's own computation below.
STATUS_DISABLED = "disabled"
STATUS_ERROR = "error"
STATUS_CLEAN = "clean"


@dataclass(frozen=True)
class PipelineRunResult:
    enabled: bool
    reason: str = ""
    status: str = STATUS_CLEAN
    errors: list = field(default_factory=list)
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
    # Distinct from no_candles_available (this asset/timeframe simply has no
    # export yet) -- a hypothesis whose candles_provider call REFUSED
    # (DataSourceRefusedError: outside APPROVED_RESEARCH_UNIVERSE, or an
    # APPROVED_EVALUATION_UNIVERSE pair) rather than silently degrading to a
    # smaller/different data source. See default_candles_provider.
    data_source_refused: int = 0
    test_results: list = field(default_factory=list)
    # Web-sourced discovery channel breakdown (added alongside the scanner
    # path, not replacing it -- hypotheses_generated/llm_calls_made/
    # total_llm_cost_usd/cost_limit_hit above are the COMBINED totals across
    # BOTH channels; these track the web channel's own contribution, so a
    # reader can see how much of the combined total came from web search
    # specifically. Every hypothesis dict itself also carries its own
    # discovery_channel field for per-hypothesis attribution.
    web_hypotheses_generated: int = 0
    web_llm_calls_made: int = 0
    web_total_llm_cost_usd: float = 0.0
    web_cost_limit_hit: bool = False


def run_pipeline(
    api_key: str = "",
    candles_provider: CandlesProvider = default_candles_provider,
    max_calls_per_run: int = hypothesis_gen.DEFAULT_MAX_CALLS_PER_RUN,
    web_max_calls_per_run: int = hypothesis_gen.DEFAULT_WEB_MAX_CALLS_PER_RUN,
    now: datetime | None = None,
) -> PipelineRunResult:
    # Kill switch: checked BEFORE `now` is even resolved, and returns with no
    # further action of any kind -- not even a performance-log write. Task 5's
    # own spec is "nothing runs when disabled," and a telemetry write is still
    # an action; performance.record_run is only ever called on the enabled
    # path below. See test_research_agent_kill_switch.py.
    if not is_enabled():
        return PipelineRunResult(
            enabled=False, status=STATUS_DISABLED,
            reason="research_agent.enabled is False (RESEARCH_AGENT_ENABLED not set) -- pipeline did nothing",
        )

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

    # Web-sourced discovery: an INDEPENDENT, parallel channel -- NOT gated on
    # the scanner finding nothing (see docs/research_agent_web_scaling_notes
    # -- Part 1's approved design: gating on scanner-emptiness would bias
    # web-sourced ideas toward the least-informative runs). `existing_hypotheses
    # + generation.hypotheses` (not just existing_hypotheses) so this run's own
    # scanner-sourced output is also visible as "already proposed" context to
    # the web-search prompt, same in-run-dedup spirit generate_hypotheses
    # already applies to itself via its own `known` list.
    tracked_pairs = hypothesis_gen.load_tracked_asset_timeframes()
    web_generation = hypothesis_gen.generate_web_hypotheses(
        existing_hypotheses + generation.hypotheses, failure_patterns, api_key, tracked_pairs, web_max_calls_per_run, now
    )
    hypothesis_gen.persist_hypotheses(web_generation.hypotheses)

    # Both ScanResult.scan_errors and GenerationRunResult.errors already exist
    # and already populate correctly at their own layer -- this run was
    # previously discarding both. Normalized into one shape (phase + context +
    # message) so main() can print one uniform, prominent error section
    # instead of two differently-shaped internal lists nothing ever read.
    errors: list[dict] = []
    for e in scan_result.scan_errors:
        errors.append({"phase": "scan", "context": e.get("source", ""), "message": e.get("message", "")})
    for e in generation.errors:
        errors.append({"phase": "hypothesis_gen", "context": e.get("scan_finding", ""), "message": e.get("message", "")})
    for e in web_generation.errors:
        errors.append({"phase": "hypothesis_gen", "context": e.get("scan_finding", ""), "message": e.get("message", "")})
    status = STATUS_ERROR if errors else STATUS_CLEAN

    # RULE 1 (no special trust): scanner-sourced and web-sourced hypotheses are
    # concatenated into ONE list and fed through this SAME loop below -- not a
    # separate branch, not a separate call to auto_tester/frequency_gate with
    # different arguments. This is the strongest available proof that a
    # web-sourced hypothesis gets zero special treatment: it is, literally,
    # the same code path as a scanner-sourced one from this point on. See
    # tests/test_research_agent_web_hypothesis_gen.py's NoSpecialTreatmentTest
    # for the direct gate/harness-level proof this loop's uniformity implies.
    all_hypotheses = generation.hypotheses + web_generation.hypotheses

    too_slow = unmeasurable = survived = watchlist = died = untestable = no_candles = data_source_refused = 0
    test_results: list[auto_tester.TestResult] = []
    for record in all_hypotheses:
        try:
            candles = candles_provider(record["asset"], record["timeframe"])
        except DataSourceRefusedError:
            # Distinct from no_candles_available: this pair was REFUSED
            # (outside the approved research universe, or an approved pair
            # whose export is missing) -- never silently degraded to the
            # 200-row site export. See default_candles_provider's own
            # docstring and DataSourceRefusedError's.
            data_source_refused += 1
            continue
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

    result = PipelineRunResult(
        enabled=True,
        status=status,
        errors=errors,
        scan_result=scan_result,
        hypotheses_generated=len(all_hypotheses),
        duplicates_skipped=len(generation.duplicates_skipped) + len(web_generation.duplicates_skipped),
        llm_calls_made=generation.llm_calls_made + web_generation.llm_calls_made,
        total_llm_cost_usd=generation.total_cost_usd + web_generation.total_cost_usd,
        cost_limit_hit=generation.cost_limit_hit or web_generation.cost_limit_hit,
        too_slow_rejected=too_slow,
        unmeasurable_rejected=unmeasurable,
        survived=survived,
        promising_watchlist=watchlist,
        died=died,
        untestable=untestable,
        no_candles_available=no_candles,
        data_source_refused=data_source_refused,
        test_results=test_results,
        web_hypotheses_generated=len(web_generation.hypotheses),
        web_llm_calls_made=web_generation.llm_calls_made,
        web_total_llm_cost_usd=web_generation.total_cost_usd,
        web_cost_limit_hit=web_generation.cost_limit_hit,
    )
    performance.record_run(result, now=now)
    return result


def main() -> None:
    """CLI entrypoint: `python -m nero_core.research_agent.pipeline`. Reads
    ANTHROPIC_API_KEY via os.getenv (never printed) and runs the pipeline
    once. If RESEARCH_AGENT_ENABLED isn't set, run_pipeline itself no-ops
    immediately (see its own docstring) -- this function does not duplicate
    that check. Prints only aggregate, non-secret counts."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    result = run_pipeline(api_key=api_key)
    # status is the headline: "disabled" (kill switch off), "error" (something
    # in scan/hypothesis_gen failed -- see the ERRORS section below), or
    # "clean" (ran fully with no failures; hypotheses_generated/duplicates_
    # skipped/etc. above already say whether anything INTERESTING happened --
    # a clean run that found nothing is not the same claim as a failed run).
    print(f"status={result.status} enabled={result.enabled} reason={result.reason!r}")
    print(f"hypotheses_generated={result.hypotheses_generated} duplicates_skipped={result.duplicates_skipped}")
    print(f"llm_calls_made={result.llm_calls_made} total_llm_cost_usd={result.total_llm_cost_usd:.6f} cost_limit_hit={result.cost_limit_hit}")
    print(f"  of which web_search: web_hypotheses_generated={result.web_hypotheses_generated} "
          f"web_llm_calls_made={result.web_llm_calls_made} web_total_llm_cost_usd={result.web_total_llm_cost_usd:.6f} "
          f"web_cost_limit_hit={result.web_cost_limit_hit}")
    print(f"too_slow_rejected={result.too_slow_rejected} unmeasurable_rejected={result.unmeasurable_rejected}")
    print(f"survived={result.survived} promising_watchlist={result.promising_watchlist} died={result.died} untestable={result.untestable}")
    print(f"no_candles_available={result.no_candles_available} data_source_refused={result.data_source_refused}")
    # Errors printed as prominently as every summary line above -- status code
    # or exception class name only, NEVER the api_key value (every message
    # here comes from ScanResult.scan_errors / GenerationRunResult.errors,
    # neither of which is ever built from api_key itself -- see
    # test_research_agent_secret_handling.py).
    if result.errors:
        print(f"=== ERRORS ({len(result.errors)}) ===")
        for err in result.errors:
            print(f"  [{err['phase']}] {err['context']}: {err['message']}")
    else:
        print("errors=none")


if __name__ == "__main__":
    main()
