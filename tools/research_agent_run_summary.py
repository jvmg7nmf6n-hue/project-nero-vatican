"""Read-only human-readable report for one Research Agent pipeline run.

Reads the three files nero_core.research_agent.pipeline/performance already
write (docs/site_data/agent_hypotheses.json, agent_test_results.json,
agent_performance.json) and joins them by hypothesis_name -- it never calls
run_pipeline itself and never writes those three files. Meant to run as a
step AFTER `python -m nero_core.research_agent.pipeline` in the same job.

CALIBRATION CHECK: the whole point of comparing expected_frequency_claim
(the LLM's own guess, hypothesis_gen.py's own docstring: "for reference
only -- never trusted for gating") against measured_trades_per_year (frequency_
gate.py's independently measured value) is to answer "does the LLM know its
own hypotheses' real trade frequency" -- a question this project's own
Task 3 commit explicitly flagged as open. This module only reports the
comparison; it never feeds it back into gating or the prompt.

PERSISTENCE (added after the CC-1 review's own item 2 -- root cause: this
script's own summary printed to stdout and nowhere else, and the workflow
that runs it, .github/workflows/research_agent_manual.yml, deliberately has
NO commit step for the three files above ("this run's output must not
become part of the record until a human has inspected it," since agent_
hypotheses.json is append-only and a bad entry can't be cleanly undone
later) -- so a real run's calibration numbers (claimed vs measured trades/
year, which hypotheses were rejected TOO_SLOW, the average overestimate
ratio) existed nowhere durable at all once that job's log/artifact expired.
The 2026-08-03 real run's numbers (claimed 24-32 trades/year, measured
2.5-15/year, ~4.79x average overestimate, all 9 rejected TOO_SLOW) were
lost to exactly this gap -- they survived only because they happened to be
pasted into a chat transcript.

The fix here is deliberately narrower than committing the three raw files:
compute_summary_data below produces an AGGREGATE, DERIVED summary (counts,
ratios, which names were TOO_SLOW) -- never the raw hypothesis text itself,
which is exactly the part the existing no-commit rule protects (an
un-reviewed bad hypothesis proposal, not an aggregate statistic about
already-reviewed-elsewhere data). append_run_summary persists this to
docs/site_data/agent_run_summaries.json (append-only, like every other Eve/
Adam data file in this project), called unconditionally from main() so this
now happens automatically on every real invocation -- never dependent on a
human remembering to commit it, and never dependent on a transcript again.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_hypotheses.json"
TEST_RESULTS_PATH = REPO_ROOT / "docs" / "site_data" / "agent_test_results.json"
PERFORMANCE_PATH = REPO_ROOT / "docs" / "site_data" / "agent_performance.json"
RUN_SUMMARIES_PATH = REPO_ROOT / "docs" / "site_data" / "agent_run_summaries.json"

OVERESTIMATE_THRESHOLD = 1.5
UNDERESTIMATE_THRESHOLD = 1.0 / 1.5

CALIBRATION_DIRECTION_OVERESTIMATE = "overestimate"
CALIBRATION_DIRECTION_UNDERESTIMATE = "underestimate"
CALIBRATION_DIRECTION_ROUGHLY_CALIBRATED = "roughly_calibrated"


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


def compute_summary_data(hypotheses: list[dict], test_results: list[dict], run_entry: dict | None) -> dict:
    """THE ONE PLACE this run's calibration facts are derived -- pure, no
    I/O, so directly testable. build_summary (human-readable text) and
    append_run_summary (committed JSON) both format THIS function's output
    rather than each re-deriving the same ratios/counts independently,
    so the printed log and the persisted record can never silently
    disagree with each other."""
    claim_by_name = {h.get("hypothesis_name"): h.get("expected_frequency_claim") for h in hypotheses}
    channel_by_name = {h.get("hypothesis_name"): h.get("discovery_channel") for h in hypotheses}
    tested_names = {r.get("hypothesis_name") for r in test_results}

    run_aggregate = None
    if run_entry is not None:
        web_hyp = run_entry.get("web_hypotheses_generated", 0)
        web_calls = run_entry.get("web_llm_calls_made", 0)
        web_cost = run_entry.get("web_total_llm_cost_usd", 0.0)
        web_cost_limit = run_entry.get("web_cost_limit_hit", False)
        scanner_hyp = run_entry.get("hypotheses_generated", 0) - web_hyp
        scanner_calls = run_entry.get("llm_calls_made", 0) - web_calls
        scanner_cost = run_entry.get("total_llm_cost_usd", 0.0) - web_cost
        run_aggregate = {
            "hypotheses_generated": run_entry.get("hypotheses_generated"),
            "duplicates_skipped": run_entry.get("duplicates_skipped"),
            "llm_calls_made": run_entry.get("llm_calls_made"),
            "total_llm_cost_usd": run_entry.get("total_llm_cost_usd", 0.0),
            "cost_limit_hit": run_entry.get("cost_limit_hit"),
            "by_channel": {
                "scanner": {"hypotheses": scanner_hyp, "calls": scanner_calls, "cost_usd": scanner_cost},
                "web_search": {"hypotheses": web_hyp, "calls": web_calls, "cost_usd": web_cost, "cost_limit_hit": web_cost_limit},
            },
            "web_search_zero_hypotheses_note": web_calls > 0 and web_hyp == 0,
            "too_slow_rejected": run_entry.get("too_slow_rejected"),
            "unmeasurable_rejected": run_entry.get("unmeasurable_rejected"),
            "survived": run_entry.get("survived"),
            "promising_watchlist": run_entry.get("promising_watchlist"),
            "died": run_entry.get("died"),
            "untestable": run_entry.get("untestable"),
            "no_candles_available": run_entry.get("no_candles_available"),
        }

    per_hypothesis = [
        {
            "hypothesis_name": r.get("hypothesis_name"),
            "asset": r.get("asset"),
            "timeframe": r.get("timeframe"),
            "discovery_channel": channel_by_name.get(r.get("hypothesis_name")),
            "llm_claimed_trades_per_year": claim_by_name.get(r.get("hypothesis_name")),
            "measured_trades_per_year": r.get("measured_trades_per_year"),
            "expected_time_to_30_trades_months": r.get("expected_time_to_30_trades_months"),
            "frequency_classification": r.get("frequency_classification"),
            "verdict": r.get("verdict"),
        }
        for r in test_results
    ]

    untested_no_candles = [
        {"hypothesis_name": h.get("hypothesis_name"), "asset": h.get("asset"), "timeframe": h.get("timeframe")}
        for h in hypotheses
        if h.get("hypothesis_name") not in tested_names
    ]

    too_slow = [
        {
            "hypothesis_name": r.get("hypothesis_name"),
            "measured_trades_per_year": r.get("measured_trades_per_year"),
            "llm_claimed_trades_per_year": claim_by_name.get(r.get("hypothesis_name")),
        }
        for r in test_results
        if r.get("frequency_classification") == "TOO_SLOW"
    ]

    unmeasurable = [
        {"hypothesis_name": r.get("hypothesis_name"), "reason": r.get("reason")}
        for r in test_results
        if r.get("frequency_classification") == "UNMEASURABLE"
    ]

    ratios: list[float] = []
    ratio_by_name: dict[str, float] = {}
    infinite_overestimate_names: list[str] = []
    for r in test_results:
        name = r.get("hypothesis_name")
        measured = r.get("measured_trades_per_year")
        claim = claim_by_name.get(name)
        if measured is None or claim is None:
            continue
        if measured <= 0:
            infinite_overestimate_names.append(name)
            continue
        ratio = claim / measured
        ratios.append(ratio)
        ratio_by_name[name] = ratio

    calibration = None
    if ratios:
        avg_ratio = statistics.mean(ratios)
        median_ratio = statistics.median(ratios)
        if avg_ratio >= OVERESTIMATE_THRESHOLD:
            direction = CALIBRATION_DIRECTION_OVERESTIMATE
        elif avg_ratio <= UNDERESTIMATE_THRESHOLD:
            direction = CALIBRATION_DIRECTION_UNDERESTIMATE
        else:
            direction = CALIBRATION_DIRECTION_ROUGHLY_CALIBRATED
        calibration = {
            "average_ratio": avg_ratio,
            "median_ratio": median_ratio,
            "n": len(ratios),
            "direction": direction,
            "ratio_by_hypothesis_name": ratio_by_name,
            "infinite_overestimate_hypothesis_names": infinite_overestimate_names,
        }

    return {
        "run_aggregate": run_aggregate,
        "n_test_results": len(test_results),
        "per_hypothesis": per_hypothesis,
        "untested_no_candles": untested_no_candles,
        "too_slow": too_slow,
        "unmeasurable": unmeasurable,
        "calibration": calibration,
    }


def build_summary(hypotheses: list[dict], test_results: list[dict], run_entry: dict | None) -> str:
    """Human-readable formatting of compute_summary_data's own output."""
    data = compute_summary_data(hypotheses, test_results, run_entry)
    lines: list[str] = []
    lines.append("=== Research Agent Run Summary ===")

    agg = data["run_aggregate"]
    if agg is None:
        lines.append("(no matching entry in agent_performance.json -- aggregate counts unavailable)")
    else:
        lines.append(f"hypotheses_generated={agg['hypotheses_generated']} duplicates_skipped={agg['duplicates_skipped']}")
        lines.append(
            f"llm_calls_made={agg['llm_calls_made']} "
            f"total_llm_cost_usd=${agg['total_llm_cost_usd']:.6f} "
            f"cost_limit_hit={agg['cost_limit_hit']}"
        )
        scanner, web = agg["by_channel"]["scanner"], agg["by_channel"]["web_search"]
        lines.append(
            f"  by channel: scanner hypotheses={scanner['hypotheses']} calls={scanner['calls']} cost=${scanner['cost_usd']:.6f} | "
            f"web_search hypotheses={web['hypotheses']} calls={web['calls']} cost=${web['cost_usd']:.6f} cost_limit_hit={web['cost_limit_hit']}"
        )
        if agg["web_search_zero_hypotheses_note"]:
            lines.append(
                f"  NOTE: web_search made {web['calls']} call(s) this run but produced zero hypotheses -- "
                f"generate_web_hypotheses always spends its call budget with no early exit on success, "
                f"so this can be a normal completion (nothing usable found), not necessarily a failure."
            )
        lines.append(f"too_slow_rejected={agg['too_slow_rejected']} unmeasurable_rejected={agg['unmeasurable_rejected']}")
        lines.append(
            f"survived={agg['survived']} promising_watchlist={agg['promising_watchlist']} died={agg['died']} "
            f"untestable={agg['untestable']} no_candles_available={agg['no_candles_available']}"
        )

    lines.append("")
    lines.append("--- Per-hypothesis detail ---")
    if not data["per_hypothesis"]:
        lines.append("(no hypotheses reached the tester -- see no_candles_available above)")
    for h in data["per_hypothesis"]:
        lines.append(
            f"[{h['hypothesis_name']}] asset={h['asset']} timeframe={h['timeframe']} channel={h['discovery_channel']} | "
            f"LLM claim={h['llm_claimed_trades_per_year']} trades/yr | measured={h['measured_trades_per_year']} trades/yr | "
            f"time-to-30-trades={h['expected_time_to_30_trades_months']} months | "
            f"classification={h['frequency_classification']} | verdict={h['verdict']}"
        )

    if data["untested_no_candles"]:
        lines.append("")
        lines.append("--- Generated but never reached the tester (no_candles_available) ---")
        for h in data["untested_no_candles"]:
            lines.append(f"[{h['hypothesis_name']}] asset={h['asset']} timeframe={h['timeframe']}")

    lines.append("")
    lines.append(f"--- TOO_SLOW rejections ({len(data['too_slow'])}) -- measured trades/year ---")
    for r in data["too_slow"]:
        lines.append(f"[{r['hypothesis_name']}] measured={r['measured_trades_per_year']} trades/yr (LLM claimed {r['llm_claimed_trades_per_year']} trades/yr)")

    lines.append("")
    lines.append(f"--- UNMEASURABLE ({len(data['unmeasurable'])}) ---")
    for r in data["unmeasurable"]:
        lines.append(f"[{r['hypothesis_name']}] reason={r['reason']}")

    lines.append("")
    lines.append("--- LLM frequency-claim calibration check ---")
    calibration = data["calibration"]
    ratio_by_name = calibration["ratio_by_hypothesis_name"] if calibration else {}
    for r in test_results:
        name = r.get("hypothesis_name")
        measured = r.get("measured_trades_per_year")
        claim = claim_by_name_for_display(hypotheses, name)
        if measured is not None and measured <= 0 and claim is not None:
            lines.append(f"[{name}] measured=0 trades/yr, LLM claimed {claim} -- infinite overestimate, excluded from the average ratio below")
        elif name in ratio_by_name:
            lines.append(f"[{name}] claim/measured ratio = {ratio_by_name[name]:.2f}x")

    if calibration:
        lines.append(f"Average claim/measured ratio: {calibration['average_ratio']:.2f}x (median {calibration['median_ratio']:.2f}x, n={calibration['n']})")
        if calibration["direction"] == CALIBRATION_DIRECTION_OVERESTIMATE:
            lines.append(
                f"FLAG: the LLM systematically OVERESTIMATES its own hypotheses' trade frequency "
                f"by ~{calibration['average_ratio']:.1f}x on average. This matters more than any individual hypothesis "
                f"result -- expected_frequency_claim should not be trusted as a planning number."
            )
        elif calibration["direction"] == CALIBRATION_DIRECTION_UNDERESTIMATE:
            lines.append(
                f"FLAG: the LLM systematically UNDERESTIMATES its own hypotheses' trade frequency "
                f"by ~{1 / calibration['average_ratio']:.1f}x on average."
            )
        else:
            lines.append(f"Roughly calibrated on this run (~{calibration['average_ratio']:.2f}x average ratio).")
    else:
        lines.append("(no hypothesis had both a measurable frequency and an LLM claim to compare)")

    return "\n".join(lines)


def claim_by_name_for_display(hypotheses: list[dict], name: str | None) -> float | None:
    """Tiny helper so build_summary's calibration-section loop (which needs
    the raw claim value for the "infinite overestimate" line) doesn't have
    to rebuild claim_by_name a second time -- reads the same hypotheses list
    compute_summary_data already read."""
    for h in hypotheses:
        if h.get("hypothesis_name") == name:
            return h.get("expected_frequency_claim")
    return None


def append_run_summary(summary_data: dict, run_at: str, source: str, path: Path = RUN_SUMMARIES_PATH) -> None:
    """Persists ONE run's compute_summary_data output to docs/site_data/
    agent_run_summaries.json, append-only (read-modify-write the whole
    list, same convention as every other Eve/Adam JSON data file in this
    project -- see nero_core.eve.storage.append_json_list, not imported
    here since this is a tools/ script, not nero_core/, so it reimplements
    the same append-only pattern directly rather than reaching across that
    boundary). `source` distinguishes a real script/workflow run
    ("research_agent_run_summary.py") from a manually backfilled entry
    reconstructed after the fact from other committed files (see the CC-1
    review's own item 2c) -- NEVER ambiguous about its own provenance."""
    existing = _read_json_list(path)
    entry = {"run_at": run_at, "source": source, **summary_data}
    existing.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def main() -> None:
    hypotheses = _read_json_list(HYPOTHESES_PATH)
    test_results = _read_json_list(TEST_RESULTS_PATH)
    performance = _read_json_dict(PERFORMANCE_PATH)
    runs = performance.get("runs", [])
    run_entry = runs[-1] if runs else None

    print(build_summary(hypotheses, test_results, run_entry))

    summary_data = compute_summary_data(hypotheses, test_results, run_entry)
    now = datetime.now(timezone.utc).isoformat()
    append_run_summary(summary_data, run_at=now, source="research_agent_run_summary.py")
    print(f"\n(run summary persisted to {RUN_SUMMARIES_PATH})")


if __name__ == "__main__":
    main()
