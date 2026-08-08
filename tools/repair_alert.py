"""CC-1 directive, Part A: ntfy alert for "a repair chain is now launchable."

"Launchable" here means the exact real mechanical gate this codebase
already enforces before a chain can actually launch --
repair_lab.check_eligibility (parent's real verdict must be DIED) AND
repair_lab.can_launch_new_attempt (the 4-attempt cap not reached) -- AND
the candidate's parent_strategy resolves to a REAL Adam or Eve hypothesis
record. Confirmed by reading repair_lab.py and repair_chain_launch.py in
full (2026-08-08): as of today, ALL 3 committed repair_candidates.json
entries (RANGE_MEAN_REVERSION, BOS_CONTINUATION, LEADLAG_FOLLOW) are
human-engineered family names with no matching hypothesis_name in either
agent's committed data -- none can ever launch under current data, and
this alert correctly finds zero eligible candidates right now.

ONE REAL GAP found and deliberately NOT silently patched here:
tools.repair_chain_launch's own parent lookup (get_candidate_status) only
checks Adam's agent_hypotheses.json/agent_test_results.json, never Eve's
eve_hypotheses.json -- so an Eve-origin parent would resolve as
"unavailable" there even if a human later created a matching
repair_candidates.json row. Since this alert's own job (per the
directive's A1) is to recognize "parent is a real Adam OR Eve record,"
_lookup_original below checks BOTH, independently of
repair_chain_launch.py's own (narrower) lookup -- this file does not
modify that module or anything about what CAN actually launch (out of
scope: this alert only WATCHES for eligibility, never launches).

ANOTHER REAL DISCREPANCY, honestly reported: the directive's own framing
of "launchable" also named review_status=approved / fixable=true --
fields that live on a graveyard/distillation entry (e.g.
docs/site_data/graveyard_distillation_drafts.json), not on a
repair_candidates.json row. Confirmed by reading graveyard_distillation.py,
repair_lab.py, and repair_chain_launch.py in full: NEITHER field is read
by any real launch-eligibility code path today, and there is no existing
mechanism linking a distillation entry to a repair_candidates.json row (a
human creates that row by hand, independently). Checking review_status/
fixable here would therefore not affect anything: even the one entry that
IS review_status="approved"/fixable=true today (family "Range Mean
Reversion") has no corresponding repair_candidates.json row at all. This
alert checks the REAL mechanical gate above instead, since asserting
"eligible" on a field the actual launch code never consults would make
this alert's claim inconsistent with what a real launch attempt would
find. If a distillation-to-candidate linkage is ever built, this alert
should be revisited to also require it.

Mirrors signal_alerts.js's own ntfy pattern (NTFY_TOPIC env var, read
once, never logged; a small local JSON state file for dedup) -- ported to
Python since the real eligibility check lives in nero_core, not JS.
DEDUP, deliberately not a time-based cooldown: keyed by
f"{parent_strategy}:{attempts_launched}", mirroring signal_alerts.js's own
reasoning for why a discrete event needs permanent-until-state-changes
dedup rather than an expiring cooldown -- a fresh alert is warranted only
when the attempt count actually changes (e.g. a human launches attempt 1,
it later DIES, and attempt 2 becomes launchable), never on every run
while nothing has changed.

DELIBERATELY NOT AUTO-WIRED into any pipeline or scheduler entrypoint --
matches tools/repair_chain_launch.py's own precedent. Runs only from its
own workflow, .github/workflows/repair_alert.yml.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from nero_core.research_agent import repair_lab
from nero_core.research_agent.hypothesis_gen import DEFAULT_HYPOTHESES_PATH
from nero_core.research_agent.storage import read_json_list
from tools.repair_chain_launch import AGENT_TEST_RESULTS_PATH, get_repair_chain_id

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVE_HYPOTHESES_PATH = REPO_ROOT / "docs" / "site_data" / "eve_hypotheses.json"
STATE_PATH = REPO_ROOT / "repair_alert_state.json"

NTFY_URL_TEMPLATE = "https://ntfy.sh/{topic}"


def _lookup_original(
    parent_strategy: str,
    hypotheses_path: Path = DEFAULT_HYPOTHESES_PATH,
    results_path: Path = AGENT_TEST_RESULTS_PATH,
    eve_hypotheses_path: Path = DEFAULT_EVE_HYPOTHESES_PATH,
) -> tuple[dict | None, dict | None, str | None]:
    """Real parent lookup across BOTH agents -- Adam first (matches
    repair_chain_launch.py's own field names exactly), then Eve (whose
    per-hypothesis verdict lives in a differently-shaped record; remapped
    onto the same {"verdict": ...} shape repair_lab.check_eligibility
    expects, since she has no separate test-results file). Returns
    (hypothesis, result, origin_agent) -- (None, None, None) if neither
    agent has ever proposed a hypothesis by this exact name."""
    hypotheses_by_name = {
        h.get("hypothesis_name"): h for h in read_json_list(hypotheses_path) if h.get("hypothesis_name")
    }
    if parent_strategy in hypotheses_by_name:
        results_by_name = {
            r.get("hypothesis_name"): r for r in read_json_list(results_path) if r.get("hypothesis_name")
        }
        result = results_by_name.get(parent_strategy)
        if result is not None:
            return hypotheses_by_name[parent_strategy], result, "adam"

    for record in read_json_list(eve_hypotheses_path):
        raw = record.get("raw_hypothesis") if isinstance(record.get("raw_hypothesis"), dict) else {}
        if raw.get("hypothesis_name") == parent_strategy and record.get("verdict_combined") is not None:
            result = {
                "verdict": record["verdict_combined"],
                "frequency_classification": record.get("frequency_classification"),
            }
            return raw, result, "eve"

    return None, None, None


def find_newly_launchable_candidates(
    candidates_path: Path = repair_lab.DEFAULT_REPAIR_CANDIDATES_PATH,
    events_path: Path = repair_lab.DEFAULT_REPAIR_ATTEMPTS_PATH,
    hypotheses_path: Path = DEFAULT_HYPOTHESES_PATH,
    results_path: Path = AGENT_TEST_RESULTS_PATH,
    eve_hypotheses_path: Path = DEFAULT_EVE_HYPOTHESES_PATH,
) -> list[dict]:
    """Every real repair_candidates.json entry that clears BOTH real gates
    right now. Pure/read-only -- never writes anything, mirrors
    tools.repair_chain_launch.get_candidate_status's own discipline."""
    candidates = repair_lab.load_repair_candidates(candidates_path)
    events = read_json_list(events_path)
    out: list[dict] = []
    for c in candidates:
        parent = c.get("parent_strategy")
        original_hypothesis, original_result, origin_agent = _lookup_original(
            parent, hypotheses_path, results_path, eve_hypotheses_path,
        )
        if original_hypothesis is None or original_result is None:
            continue
        eligibility = repair_lab.check_eligibility(original_result)
        if not eligibility.eligible:
            continue
        chain_id = get_repair_chain_id(c.get("hypothesis_name", ""))
        attempts = repair_lab.reconstruct_chain_state(chain_id, events)["attempts"]
        can_launch, cap_reason = repair_lab.can_launch_new_attempt(attempts)
        if not can_launch:
            continue
        out.append({
            **c,
            "chain_id": chain_id,
            "parent_origin_agent": origin_agent,
            "attempts_launched": len(attempts),
            "eligibility_reason": eligibility.reason,
        })
    return out


def _push(title: str, body: str, topic: str) -> bool:
    req = Request(
        NTFY_URL_TEMPLATE.format(topic=topic),
        data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "default", "Tags": "wrench"},
        method="POST",
    )
    try:
        urlopen(req, timeout=15)
        return True
    except Exception as exc:  # non-fatal, matches signal_alerts.js's own try/catch
        print(f"push failed (non-fatal): {exc}")
        return False


def _load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _format_message(candidate: dict) -> tuple[str, str]:
    name = candidate.get("hypothesis_name", "unknown")
    parent = candidate.get("parent_strategy", "unknown")
    origin = candidate.get("parent_origin_agent", "unknown")
    title = f"Vatican | Repair chain launchable | {name}"
    body = (
        f"Parent {parent} ({origin}, DIED) is repair-eligible -- proposed fix: {name}. "
        f"Run locally: python -m tools.repair_chain_launch (report-only) or start the "
        f"Operator Panel: python -m uvicorn tools.operator_panel.app:app --host 127.0.0.1 --port 8765 "
        f"(local only, never deployed)."
    )
    return title, body


def main() -> None:
    topic = os.environ.get("NTFY_TOPIC", "")
    candidates = find_newly_launchable_candidates()
    state = _load_state()
    new_alerts = 0

    for c in candidates:
        key = f"{c.get('parent_strategy')}:{c.get('attempts_launched')}"
        if key in state:
            continue
        title, body = _format_message(c)
        if topic:
            _push(title, body, topic)
        else:
            print(f"NTFY_TOPIC not set -- skipping push, dry run only: {title}")
        state[key] = {"hypothesis_name": c.get("hypothesis_name"), "chain_id": c.get("chain_id")}
        new_alerts += 1

    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Done. {new_alerts} new repair-launchable alert(s), {len(candidates)} currently-eligible candidate(s).")


if __name__ == "__main__":
    main()
