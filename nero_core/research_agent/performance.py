"""Task 6 -- the Agent's own performance metric.

Six months from now the honest question is "is this Agent actually working?"
-- that answer must come from data recorded after every run, not from
impression. `record_run` is called once per pipeline.run_pipeline() call
(enabled or not) and writes docs/site_data/agent_performance.json: a
cumulative total across every run ever made, plus this run's own numbers
appended to a `runs` history, so both "how has this done overall" and
"what happened in run N" are answerable directly from the file.

A disabled (kill-switch-off) run is NEVER recorded here -- Task 5's own spec
is "nothing runs when disabled," and a telemetry write is still an action;
pipeline.run_pipeline returns before calling this module at all in that case.
`enabled` is still a field on every entry this module ever writes because
this function's own contract accepts any PipelineRunResult, but in practice
every entry that reaches this file has enabled=True.

survival_rate is computed ONLY from hypotheses that were actually TESTED
(SURVIVED + PROMISING-WATCHLIST + DIED + UNTESTABLE) -- SKIPPED (gate-rejected)
hypotheses are excluded from the denominator on purpose: they were never
given a chance to survive or die, so folding them in would understate the
rate the harness itself is achieving on what it actually evaluates. `null`
(never a fabricated 0.0) until at least one hypothesis has ever been tested.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PERFORMANCE_PATH = REPO_ROOT / "docs" / "site_data" / "agent_performance.json"

SCHEMA_VERSION = 1

_CUMULATIVE_INT_FIELDS = (
    "hypotheses_generated", "duplicates_skipped", "too_slow_rejected", "unmeasurable_rejected",
    "tested", "survived", "promising_watchlist", "died", "untestable", "no_candles_available",
    "llm_calls_made",
)


def _empty_cumulative() -> dict:
    cumulative = {field: 0 for field in _CUMULATIVE_INT_FIELDS}
    cumulative["total_llm_cost_usd"] = 0.0
    cumulative["survival_rate"] = None
    return cumulative


def _load(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "last_updated": None, "cumulative": _empty_cumulative(), "runs": []}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "last_updated": None, "cumulative": _empty_cumulative(), "runs": []}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "last_updated": None, "cumulative": _empty_cumulative(), "runs": []}
    data.setdefault("cumulative", _empty_cumulative())
    data.setdefault("runs", [])
    return data


def _run_entry(result, now: datetime) -> dict:
    tested = result.survived + result.promising_watchlist + result.died + result.untestable
    return {
        "run_at": now.isoformat(),
        "enabled": result.enabled,
        "reason": result.reason,
        # status + errors: a failed run must leave a durable record here, not
        # just console output that scrolls away once the Actions log closes.
        # See pipeline.PipelineRunResult's own STATUS_* constants.
        "status": result.status,
        "errors": result.errors,
        "hypotheses_generated": result.hypotheses_generated,
        "duplicates_skipped": result.duplicates_skipped,
        "too_slow_rejected": result.too_slow_rejected,
        "unmeasurable_rejected": result.unmeasurable_rejected,
        "tested": tested,
        "survived": result.survived,
        "promising_watchlist": result.promising_watchlist,
        "died": result.died,
        "untestable": result.untestable,
        "no_candles_available": result.no_candles_available,
        "llm_calls_made": result.llm_calls_made,
        "total_llm_cost_usd": result.total_llm_cost_usd,
        "cost_limit_hit": result.cost_limit_hit,
    }


def record_run(result, path: Path = DEFAULT_PERFORMANCE_PATH, now: datetime | None = None) -> dict:
    """`result` is a nero_core.research_agent.pipeline.PipelineRunResult.
    Returns the full updated state (also written to `path`)."""
    now = now or datetime.now(timezone.utc)
    state = _load(path)
    cumulative = state["cumulative"]

    run_entry = _run_entry(result, now)
    if result.enabled:
        for field in ("hypotheses_generated", "duplicates_skipped", "too_slow_rejected", "unmeasurable_rejected",
                       "survived", "promising_watchlist", "died", "untestable", "no_candles_available", "llm_calls_made"):
            cumulative[field] = cumulative.get(field, 0) + getattr(result, field)
        cumulative["tested"] = cumulative.get("tested", 0) + run_entry["tested"]
        cumulative["total_llm_cost_usd"] = cumulative.get("total_llm_cost_usd", 0.0) + result.total_llm_cost_usd

        if cumulative["tested"] > 0:
            cumulative["survival_rate"] = (cumulative["survived"] + cumulative["promising_watchlist"]) / cumulative["tested"]
        else:
            cumulative["survival_rate"] = None

    state["schema_version"] = SCHEMA_VERSION
    state["last_updated"] = now.isoformat()
    state["cumulative"] = cumulative
    state["runs"] = state["runs"] + [run_entry]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n")
    return state


def load_performance(path: Path = DEFAULT_PERFORMANCE_PATH) -> dict:
    return _load(path)
