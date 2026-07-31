"""Read-only human-readable report for one Research Agent pipeline run.

Reads the three files nero_core.research_agent.pipeline/performance already
write (docs/site_data/agent_hypotheses.json, agent_test_results.json,
agent_performance.json) and joins them by hypothesis_name -- it never calls
run_pipeline itself and never writes anything. Meant to run as a step AFTER
`python -m nero_core.research_agent.pipeline` in the same job, so its output
lands in the same Actions step log the operator is already reading.

CALIBRATION CHECK: the whole point of comparing expected_frequency_claim
(the LLM's own guess, hypothesis_gen.py's own docstring: "for reference
only -- never trusted for gating") against measured_trades_per_year (frequency_
gate.py's independently measured value) is to answer "does the LLM know its
own hypotheses' real trade frequency" -- a question this project's own
Task 3 commit explicitly flagged as open. This module only reports the
comparison; it never feeds it back into gating or the prompt.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"
TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"
PERFORMANCE_PATH = REPO_ROOT / "docs" / "site_data" / "agent_performance.json"

OVERESTIMATE_THRESHOLD = 1.5
UNDERESTIMATE_THRESHOLD = 1.0 / 1.5


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _read_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def build_summary(hypotheses: list[dict], test_results: list[dict], run_entry: dict | None) -> str:
    """Pure formatting -- no I/O, so this is directly testable without touching
    the filesystem. `run_entry` is one entry from agent_performance.json's
    `runs` list (this run's own aggregate counts); None is handled (prints
    n/a) rather than crashing if performance.json wasn't written for some
    reason."""
    lines: list[str] = []
    lines.append("=== Research Agent Run Summary ===")

    if run_entry is None:
        lines.append("(no matching entry in agent_performance.json -- aggregate counts unavailable)")
    else:
        lines.append(
            f"hypotheses_generated={run_entry.get('hypotheses_generated')} "
            f"duplicates_skipped={run_entry.get('duplicates_skipped')}"
        )
        lines.append(
            f"llm_calls_made={run_entry.get('llm_calls_made')} "
            f"total_llm_cost_usd=${run_entry.get('total_llm_cost_usd', 0.0):.6f} "
            f"cost_limit_hit={run_entry.get('cost_limit_hit')}"
        )
        # By-channel split -- web_* keys are absent on run entries recorded
        # before the web-search channel existed, so .get(..., 0) defaults are
        # the honest value there (zero web activity), not a placeholder.
        # Scanner-only counts are derived (combined - web) rather than stored
        # separately, since combined == scanner + web by construction in
        # pipeline.run_pipeline.
        web_hyp = run_entry.get("web_hypotheses_generated", 0)
        web_calls = run_entry.get("web_llm_calls_made", 0)
        web_cost = run_entry.get("web_total_llm_cost_usd", 0.0)
        web_cost_limit = run_entry.get("web_cost_limit_hit", False)
        scanner_hyp = run_entry.get("hypotheses_generated", 0) - web_hyp
        scanner_calls = run_entry.get("llm_calls_made", 0) - web_calls
        scanner_cost = run_entry.get("total_llm_cost_usd", 0.0) - web_cost
        lines.append(
            f"  by channel: scanner hypotheses={scanner_hyp} calls={scanner_calls} cost=${scanner_cost:.6f} | "
            f"web_search hypotheses={web_hyp} calls={web_calls} cost=${web_cost:.6f} cost_limit_hit={web_cost_limit}"
        )
        if web_calls > 0 and web_hyp == 0:
            lines.append(
                f"  NOTE: web_search made {web_calls} call(s) this run but produced zero hypotheses -- "
                f"generate_web_hypotheses always spends its call budget with no early exit on success, "
                f"so this can be a normal completion (nothing usable found), not necessarily a failure."
            )
        lines.append(
            f"too_slow_rejected={run_entry.get('too_slow_rejected')} "
            f"unmeasurable_rejected={run_entry.get('unmeasurable_rejected')}"
        )
        lines.append(
            f"survived={run_entry.get('survived')} "
            f"promising_watchlist={run_entry.get('promising_watchlist')} "
            f"died={run_entry.get('died')} "
            f"untestable={run_entry.get('untestable')} "
            f"no_candles_available={run_entry.get('no_candles_available')}"
        )

    claim_by_name = {h.get("hypothesis_name"): h.get("expected_frequency_claim") for h in hypotheses}
    channel_by_name = {h.get("hypothesis_name"): h.get("discovery_channel") for h in hypotheses}
    tested_names = {r.get("hypothesis_name") for r in test_results}

    lines.append("")
    lines.append("--- Per-hypothesis detail ---")
    if not test_results:
        lines.append("(no hypotheses reached the tester -- see no_candles_available above)")
    for r in test_results:
        name = r.get("hypothesis_name")
        claim = claim_by_name.get(name)
        channel = channel_by_name.get(name)
        measured = r.get("measured_trades_per_year")
        months = r.get("expected_time_to_30_trades_months")
        lines.append(
            f"[{name}] asset={r.get('asset')} timeframe={r.get('timeframe')} channel={channel} | "
            f"LLM claim={claim} trades/yr | measured={measured} trades/yr | "
            f"time-to-30-trades={months} months | "
            f"classification={r.get('frequency_classification')} | verdict={r.get('verdict')}"
        )

    untested = [h for h in hypotheses if h.get("hypothesis_name") not in tested_names]
    if untested:
        lines.append("")
        lines.append("--- Generated but never reached the tester (no_candles_available) ---")
        for h in untested:
            lines.append(f"[{h.get('hypothesis_name')}] asset={h.get('asset')} timeframe={h.get('timeframe')}")

    too_slow = [r for r in test_results if r.get("frequency_classification") == "TOO_SLOW"]
    lines.append("")
    lines.append(f"--- TOO_SLOW rejections ({len(too_slow)}) -- measured trades/year ---")
    for r in too_slow:
        claim = claim_by_name.get(r.get("hypothesis_name"))
        lines.append(
            f"[{r.get('hypothesis_name')}] measured={r.get('measured_trades_per_year')} trades/yr "
            f"(LLM claimed {claim} trades/yr)"
        )

    unmeasurable = [r for r in test_results if r.get("frequency_classification") == "UNMEASURABLE"]
    lines.append("")
    lines.append(f"--- UNMEASURABLE ({len(unmeasurable)}) ---")
    for r in unmeasurable:
        lines.append(f"[{r.get('hypothesis_name')}] reason={r.get('reason')}")

    lines.append("")
    lines.append("--- LLM frequency-claim calibration check ---")
    ratios: list[float] = []
    for r in test_results:
        measured = r.get("measured_trades_per_year")
        claim = claim_by_name.get(r.get("hypothesis_name"))
        if measured is None or claim is None:
            continue
        if measured <= 0:
            lines.append(
                f"[{r.get('hypothesis_name')}] measured=0 trades/yr, LLM claimed {claim} -- "
                f"infinite overestimate, excluded from the average ratio below"
            )
            continue
        ratio = claim / measured
        ratios.append(ratio)
        lines.append(f"[{r.get('hypothesis_name')}] claim/measured ratio = {ratio:.2f}x")

    if ratios:
        avg_ratio = statistics.mean(ratios)
        median_ratio = statistics.median(ratios)
        lines.append(f"Average claim/measured ratio: {avg_ratio:.2f}x (median {median_ratio:.2f}x, n={len(ratios)})")
        if avg_ratio >= OVERESTIMATE_THRESHOLD:
            lines.append(
                f"FLAG: the LLM systematically OVERESTIMATES its own hypotheses' trade frequency "
                f"by ~{avg_ratio:.1f}x on average. This matters more than any individual hypothesis "
                f"result -- expected_frequency_claim should not be trusted as a planning number."
            )
        elif avg_ratio <= UNDERESTIMATE_THRESHOLD:
            lines.append(
                f"FLAG: the LLM systematically UNDERESTIMATES its own hypotheses' trade frequency "
                f"by ~{1 / avg_ratio:.1f}x on average."
            )
        else:
            lines.append(f"Roughly calibrated on this run (~{avg_ratio:.2f}x average ratio).")
    else:
        lines.append("(no hypothesis had both a measurable frequency and an LLM claim to compare)")

    return "\n".join(lines)


def main() -> None:
    hypotheses = _read_json_list(HYPOTHESES_PATH)
    test_results = _read_json_list(TEST_RESULTS_PATH)
    performance = _read_json_dict(PERFORMANCE_PATH)
    runs = performance.get("runs", [])
    run_entry = runs[-1] if runs else None
    print(build_summary(hypotheses, test_results, run_entry))


if __name__ == "__main__":
    main()
