"""CC-1 directive: one-time, idempotent correction of the real, already-
approved-and-committed "RANGE_MEAN_REVERSION_GRAVEYARD" distillation entry
(commit e3d7b94) across all three files it touched --
docs/site_data/graveyard_distillation_drafts.json,
docs/site_data/failure_patterns.json, docs/site_data/graveyard.json.

WHY: the entry's source_doc ("eve-origin graveyard review: PAXG_PEG_
REVERSION, ...") was free text, neither a real docs/*.md path nor the
"no written report -- ..." sentinel graveyard_distillation.py's
_no_report_source_doc now computes for every future LLM-drafted entry
(item introduced in this same directive). Two real, confirmed
consequences: (1) website/__tests__/siteDataSchema.test.ts's regex test
failed against failure_patterns.json's copy; (2) GraveyardCard.tsx builds
a GitHub blob URL from source_doc unconditionally, so the live public
graveyard page's "Source report" link on all 4 of this entry's
graveyard.json rows pointed at a nonsense URL. The failure_patterns.json
copy also had no fix_rationale despite fixable=true (the LLM prompt never
asked for one at the time this entry was drafted -- also fixed in this
same directive), failing a second website test.

This script does NOT touch review_status, why_it_died, or fixable -- the
human approval decision and the substantive diagnosis are unchanged; only
the two schema-shape fields are corrected, using the exact same
_no_report_source_doc computation the code now uses for every future
entry (imported directly, not reimplemented) so this entry's provenance
string is byte-identical in form to what a fresh draft would produce
today. fix_rationale's content is drawn from this entry's own real,
already-approved fixable_note (docs/site_data/graveyard_distillation_
drafts.json) -- not invented -- trimmed to one sentence naming the
specific mechanism-justified improvement, matching every other
failure_patterns.json entry's fix_rationale style.

Idempotent: running this twice is a no-op the second time (checks the
current source_doc against the target value before rewriting each file).
"""
from __future__ import annotations

import json
from pathlib import Path

from nero_core.research_agent.graveyard_distillation import DiedRecord, _no_report_source_doc

REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFTS_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard_distillation_drafts.json"
FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"
GRAVEYARD_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard.json"

TARGET_NAME = "RANGE_MEAN_REVERSION_GRAVEYARD"
FAMILY = "Range Mean Reversion"
COVERED_NAMES = [
    "PAXG_PEG_REVERSION", "BTC_VOL_EXPANSION_BREAKOUT", "SOL_TREND_ALIGNED_PULLBACK", "PAXG_PREMIUM_FADE_DYNAMIC_EXIT",
]

# _no_report_source_doc only uses .hypothesis_name off each member -- the
# other DiedRecord fields are irrelevant to this computation and left at
# harmless placeholder values.
CORRECTED_SOURCE_DOC = _no_report_source_doc(
    FAMILY, [DiedRecord(hypothesis_name=n, mechanism="", origin_agent="eve", matched_family=FAMILY, p_value_oos=None) for n in COVERED_NAMES]
)

CORRECTED_FIX_RATIONALE = (
    "2 of the 4 records (BTC_VOL_EXPANSION_BREAKOUT, PAXG_PREMIUM_FADE_DYNAMIC_EXIT) were "
    "PROMISING_WATCHLIST in-sample but died on a thin out-of-sample sample -- a real positive signal "
    "a fuller out-of-sample sample could still confirm, matching this project's own precedent that "
    "'sample-too-thin' is its most fixable failure pattern (see the original RANGE_MEAN_REVERSION "
    "entry, repair_candidates.json's RMR_CONFIRMATION_METALS_WEEKLY)."
)


def _fix_drafts() -> bool:
    if not DRAFTS_PATH.exists():
        print(f"{DRAFTS_PATH} does not exist -- nothing to fix.")
        return False
    drafts = json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    entry = next((d for d in drafts if d.get("name") == TARGET_NAME), None)
    if entry is None:
        print(f"{TARGET_NAME!r} not found in {DRAFTS_PATH} -- nothing to fix.")
        return False
    if entry.get("source_doc") == CORRECTED_SOURCE_DOC:
        print(f"{DRAFTS_PATH.name}: {TARGET_NAME!r} source_doc already correct -- no-op.")
        return False
    entry["source_doc"] = CORRECTED_SOURCE_DOC
    entry["fix_rationale"] = CORRECTED_FIX_RATIONALE
    entry["source_doc_correction_provenance"] = {
        "corrected_at": "2026-08-06T00:00:00+00:00",
        "reason": (
            "CC-1 directive: original source_doc ('eve-origin graveyard review: ...') was free text, "
            "not a real docs/*.md path or the no-written-report sentinel. Replaced with the same "
            "_no_report_source_doc computation graveyard_distillation.py now uses for every future "
            "LLM-drafted entry. fix_rationale added (was entirely absent -- the drafting prompt never "
            "asked for one until this same directive)."
        ),
        "original_source_doc": "eve-origin graveyard review: PAXG_PEG_REVERSION, BTC_VOL_EXPANSION_BREAKOUT, SOL_TREND_ALIGNED_PULLBACK, PAXG_PREMIUM_FADE_DYNAMIC_EXIT",
    }
    DRAFTS_PATH.write_text(json.dumps(drafts, indent=2) + "\n", encoding="utf-8")
    print(f"Fixed {TARGET_NAME!r} source_doc/fix_rationale in {DRAFTS_PATH}.")
    return True


def _fix_failure_patterns() -> bool:
    if not FAILURE_PATTERNS_PATH.exists():
        print(f"{FAILURE_PATTERNS_PATH} does not exist -- nothing to fix.")
        return False
    patterns = json.loads(FAILURE_PATTERNS_PATH.read_text(encoding="utf-8"))
    entry = next((p for p in patterns if p.get("name") == TARGET_NAME), None)
    if entry is None:
        print(f"{TARGET_NAME!r} not found in {FAILURE_PATTERNS_PATH} -- nothing to fix.")
        return False
    if entry.get("source_doc") == CORRECTED_SOURCE_DOC and entry.get("fix_rationale") == CORRECTED_FIX_RATIONALE:
        print(f"{FAILURE_PATTERNS_PATH.name}: {TARGET_NAME!r} already correct -- no-op.")
        return False
    entry["source_doc"] = CORRECTED_SOURCE_DOC
    if entry.get("fixable"):
        entry["fix_rationale"] = CORRECTED_FIX_RATIONALE
    FAILURE_PATTERNS_PATH.write_text(json.dumps(patterns, indent=2) + "\n", encoding="utf-8")
    print(f"Fixed {TARGET_NAME!r} source_doc/fix_rationale in {FAILURE_PATTERNS_PATH}.")
    return True


def _fix_graveyard() -> bool:
    if not GRAVEYARD_PATH.exists():
        print(f"{GRAVEYARD_PATH} does not exist -- nothing to fix.")
        return False
    entries = json.loads(GRAVEYARD_PATH.read_text(encoding="utf-8"))
    changed = False
    for e in entries:
        if e.get("name") in COVERED_NAMES and e.get("source_doc") != CORRECTED_SOURCE_DOC:
            e["source_doc"] = CORRECTED_SOURCE_DOC
            changed = True
    if not changed:
        print(f"{GRAVEYARD_PATH.name}: covered entries already correct -- no-op.")
        return False
    GRAVEYARD_PATH.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"Fixed source_doc on {len(COVERED_NAMES)} covered entries in {GRAVEYARD_PATH}.")
    return True


def fix_all() -> bool:
    results = [_fix_drafts(), _fix_failure_patterns(), _fix_graveyard()]
    return any(results)


if __name__ == "__main__":
    fix_all()
