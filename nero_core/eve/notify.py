"""Eve session notifications -- reuses nero_core.execution.notify_ntfy's
existing ntfy.sh path directly (same topic, same best-effort/never-raises
delivery semantics) rather than inventing a second notification pipeline.
Allowed: nero_core.execution is NOT nero_core.research_agent -- this import
does not violate nero_core/eve/'s research_agent isolation rule (see
test_eve_no_auto_wire.py, which only restricts research_agent imports).

Eve sends exactly one notification per invocation of
nero_core.eve.pipeline.run_pipeline: either an end-of-session summary (at
least one real turn happened, however it ended) or a failure notification
(preflight rejection, an unhandled crash, or the ledger was already
exhausted before a single turn could run). A silent failure here is the
exact same failure class as Adam's stale-key 401 going unnoticed for
weeks -- see nero_core.eve.preflight's own module docstring."""
from __future__ import annotations

from nero_core.execution.notify_ntfy import NTFY_URL, send_ntfy_notification


def build_session_summary_message(
    session_id: str,
    terminated_because: str,
    n_proposed: int,
    n_testable: int,
    verdict_counts: dict[str, int],
    real_cost_usd: float,
    session_file_path: str,
) -> str:
    verdict_line = ", ".join(f"{k}={v}" for k, v in sorted(verdict_counts.items())) or "(none testable)"
    return (
        f"Eve session {session_id} finished ({terminated_because}). "
        f"Proposed {n_proposed} hypotheses, {n_testable} testable. "
        f"OOS verdicts: {verdict_line}. "
        f"Cost: ${real_cost_usd:.4f}. "
        f"Transcript: {session_file_path}"
    )


def build_failure_message(reason: str, session_id: str | None = None, cost_hint_usd: float | None = None) -> str:
    header = f"Eve session {session_id} FAILED" if session_id else "Eve session FAILED (before a session id was assigned)"
    cost_part = f" Cost incurred: ${cost_hint_usd:.4f}." if cost_hint_usd is not None else " Cost incurred: unknown -- check docs/site_data/eve_budget_ledger.json for this run's own entries."
    return f"{header}: {reason}.{cost_part}"


def send_session_summary(
    session_id: str,
    terminated_because: str,
    n_proposed: int,
    n_testable: int,
    verdict_counts: dict[str, int],
    real_cost_usd: float,
    session_file_path: str,
) -> bool:
    message = build_session_summary_message(
        session_id, terminated_because, n_proposed, n_testable, verdict_counts, real_cost_usd, session_file_path
    )
    return send_ntfy_notification(message, url=NTFY_URL)


def send_failure(reason: str, session_id: str | None = None, cost_hint_usd: float | None = None) -> bool:
    message = build_failure_message(reason, session_id=session_id, cost_hint_usd=cost_hint_usd)
    return send_ntfy_notification(message, url=NTFY_URL)
