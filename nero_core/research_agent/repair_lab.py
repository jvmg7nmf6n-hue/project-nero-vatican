"""Repair Lab v1 -- a closed loop for DIED hypotheses only. Implements exactly
what docs/repair_lab_investigation_report.md scoped and recommended: a DIED
hypothesis's aggregate failure stats are diagnosed, an LLM proposes ONE
modification within an approved repair-scope boundary, and the modification
is retested on genuinely fresh data (historical reservation or forward
paper-tracking) -- capped at 4 LAUNCHED attempts per hypothesis, full chain
transparency, never silently reusing data any attempt (or the original run)
already touched.

SCOPE LOCK (Task 1): only VERDICT_DIED hypotheses are eligible. TOO_SLOW,
UNMEASURABLE, UNTESTABLE, SURVIVED, and PROMISING-WATCHLIST are all
explicitly out of scope for v1 -- see check_eligibility below and the
investigation report's own Task 3 reasoning (TOO_SLOW's only data-supported
repair lever is a threshold change on the same gate that rejected it, the
exact gate-gaming behavior frequency_gate.py exists to prevent).

CRITICAL SAFETY: this module (and nero_core.research_agent.repair_forward_
tracker, nero_core.research_agent.repair_historical_reservation) writes ONLY
to docs/site_data/repair_attempts.json and its own dedicated SQLite file
(data/repair_lab_forward_tracking.db -- see repair_forward_tracker.py's own
docstring). It imports nothing from nero_core.execution.live_scheduler and
never references nero_core.strategies.registry's default_registry -- see
test_research_agent_no_auto_wire.py's HARD TEST, extended by
test_repair_lab_no_auto_wire.py to cover every new file this feature adds.
A SURVIVED or PROMISING-WATCHLIST repair result only ever reaches the same
human-review queue any other research-agent output does (review_status=
"pending_human_approval", per auto_tester.py's own existing convention) --
nothing here, regardless of how many attempts succeed, ever registers a
strategy variant or schedules anything.

ANTI-P-HACKING (the investigation's own critical constraint, restated here
because every function below exists to enforce it): the LLM proposes exactly
ONE modification per repair attempt, decided from the DIAGNOSIS (aggregate,
already-computed statistics about the failed run) alone, before any retest
data is seen. The diagnosis step may see aggregate stats; a retest may never
run against data any prior attempt (or the original run) in the same chain
already touched -- enforced structurally by repair_historical_reservation's
non-overlap check and by forward-testing's own by-construction freshness
(the data didn't exist before the attempt was launched). No re-rolling, no
trying multiple modifications and keeping the best -- one attempt in this
module is one committed proposal, evaluated once.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nero_core.research_agent.auto_tester import VERDICT_SKIPPED, VERDICT_UNTESTABLE
from tools.backtest_statistics import VERDICT_DIED, VERDICT_PROMISING_WATCHLIST, VERDICT_SURVIVED

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPAIR_ATTEMPTS_PATH = REPO_ROOT / "docs" / "site_data" / "repair_attempts.json"
DEFAULT_REPAIR_CANDIDATES_PATH = REPO_ROOT / "docs" / "site_data" / "repair_candidates.json"

MAX_ATTEMPTS_PER_CHAIN = 4

# Attempt-level statuses. PENDING_FORWARD_DATA is deliberately its own value,
# never conflated with any of the resolved verdicts below -- see Task 4's
# forward-testing docstring and every test in test_repair_lab_chain_record.py
# asserting this distinction holds everywhere the chain is read.
ATTEMPT_REJECTED = "REJECTED"  # proposal never launched -- duplicate or out-of-boundary
ATTEMPT_PENDING_FORWARD_DATA = "PENDING_FORWARD_DATA"
ATTEMPT_DIED = VERDICT_DIED
ATTEMPT_SURVIVED = VERDICT_SURVIVED
ATTEMPT_PROMISING_WATCHLIST = VERDICT_PROMISING_WATCHLIST

RESOLVED_ATTEMPT_STATUSES = (ATTEMPT_DIED, ATTEMPT_SURVIVED, ATTEMPT_PROMISING_WATCHLIST)
TERMINAL_FAILURE_STATUSES = (ATTEMPT_DIED,)  # a resolved-but-failed attempt; PENDING_FORWARD_DATA is NOT terminal

# Chain-level statuses.
CHAIN_OPEN = "OPEN"
CHAIN_RESOLVED = "RESOLVED"  # an attempt reached SURVIVED or PROMISING-WATCHLIST; chain stops here
CHAIN_PERMANENTLY_DIED = "PERMANENTLY_DIED"


# ---------------------------------------------------------------------------
# TASK 1 -- ELIGIBILITY GATE
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str


def check_eligibility(original_result: dict) -> EligibilityResult:
    """The FIRST check anything calling into Repair Lab must pass. Returns a
    clear, explicit EligibilityResult either way -- NEVER silently no-ops and
    NEVER silently accepts an out-of-scope hypothesis. `original_result` is
    the exact dict shape auto_tester.TestResult.to_dict() (or run_hypothesis_
    live's own "result" key) produces: at minimum "verdict" and, when verdict
    is SKIPPED, "frequency_classification".

    Only VERDICT_DIED is eligible. Every other verdict is rejected with a
    reason naming the ACTUAL classification that disqualified it (not a
    generic "not DIED") -- SKIPPED hypotheses report their frequency_
    classification (TOO_SLOW or UNMEASURABLE) specifically, since "SKIPPED"
    alone would hide which of the two distinct frequency-gate rejections this
    was. See docs/repair_lab_investigation_report.md Task 3 for the full
    reasoning on why TOO_SLOW is excluded from v1: its only data-supported
    repair lever (loosen the entry gate) is the exact gate-gaming behavior
    frequency_gate.py exists to prevent."""
    verdict = original_result.get("verdict")

    if verdict == VERDICT_DIED:
        return EligibilityResult(True, "eligible: DIED verdict clears Repair Lab v1's scope")

    if verdict == VERDICT_SKIPPED:
        freq = original_result.get("frequency_classification", "UNKNOWN")
        return EligibilityResult(
            False,
            f"not_eligible: {freq} hypotheses are out of scope for Repair Lab v1 "
            f"(see repair-lab-investigation report, Task 3)",
        )

    if verdict == VERDICT_UNTESTABLE:
        return EligibilityResult(
            False,
            "not_eligible: UNTESTABLE hypotheses are out of scope for Repair Lab v1 "
            "(see repair-lab-investigation report, Task 3) -- the entry_rule/exit_plan "
            "isn't machine-checkable at all, which is a different problem than a tested "
            "mechanism with no edge",
        )

    if verdict in (VERDICT_SURVIVED, VERDICT_PROMISING_WATCHLIST):
        return EligibilityResult(
            False,
            f"not_eligible: {verdict} hypotheses don't need repair -- Repair Lab v1 only "
            f"handles DIED hypotheses (see repair-lab-investigation report, Task 3)",
        )

    return EligibilityResult(
        False,
        f"not_eligible: unrecognized verdict {verdict!r} -- Repair Lab v1 only accepts a "
        f"result whose verdict is exactly {VERDICT_DIED!r}",
    )
