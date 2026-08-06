"""CC-1 directive, item 1b: one-time, idempotent correction of the real
"RANGE_MEAN_REVERSION_GRAVEYARD" distillation draft
(docs/site_data/graveyard_distillation_drafts.json), drafted 2026-08-06 by
tools/factory_loop_run.py --live, still at review_status=pending_human_
approval, never approved or committed to graveyard.json.

WHY: the drafted text had two real, confirmed-from-data errors --
(1) it claimed "two had no OOS p-value" when the real count (re-verified
directly against docs/site_data/eve_hypotheses.json) is three
(PAXG_PEG_REVERSION, SOL_TREND_ALIGNED_PULLBACK, PAXG_PREMIUM_FADE_
DYNAMIC_EXIT all have p_value_oos=None; only BTC_VOL_EXPANSION_BREAKOUT
has a real one, 0.2599); (2) it collapsed two different failure shapes
(two records were PROMISING_WATCHLIST in-sample before dying
out-of-sample; two died outright) into one "none produced usable
evidence" narrative. Root cause (see this directive's own closing report):
the LLM was shown the correct p_value_oos data but miscounted it in its
own free-text synthesis; verdict_is/verdict_oos were never in the prompt
at all, so the IS/OOS distinction was structurally unavailable to it, not
just missed.

Hand-corrected here rather than re-drafted via a second real LLM call --
strictly more reliable for a purely factual correction (no risk of a
second, different synthesis error), and the graveyard_distillation.py fix
(item 1c, the n_no_oos_pvalue structural check) already prevents this
specific error class in every FUTURE draft.

Idempotent: running this twice is a no-op the second time (checks the
draft's own text before rewriting)."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFTS_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard_distillation_drafts.json"

TARGET_NAME = "RANGE_MEAN_REVERSION_GRAVEYARD"

# The real, re-verified data this correction is built from (see this
# module's own docstring) -- not re-derived at runtime, since the LLM's
# original mechanism/asset descriptions in the drafted prose (already
# accurate) are kept, only the WHY_IT_DIED synthesis is replaced.
CORRECTED_WHY_IT_DIED = (
    "Across four Eve hypotheses on this family (two testing PAXG's own redemption-arbitrage "
    "mechanism long and short, one on BTC volatility expansion, one on SOL trend-aligned pullback), "
    "the real evidence splits into two distinct failure shapes, not one: SOL_TREND_ALIGNED_PULLBACK "
    "and PAXG_PEG_REVERSION failed outright without ever producing a usable out-of-sample read "
    "(SOL died on both the in-sample and out-of-sample halves; PAXG_PEG_REVERSION died in-sample and "
    "never accumulated enough out-of-sample trades to reach a verdict at all). BTC_VOL_EXPANSION_"
    "BREAKOUT and PAXG_PREMIUM_FADE_DYNAMIC_EXIT looked promising in-sample (both PROMISING_WATCHLIST) "
    "but both died out-of-sample -- BTC_VOL_EXPANSION_BREAKOUT's own out-of-sample p-value (0.2599) "
    "explicitly failed significance, and PAXG_PREMIUM_FADE_DYNAMIC_EXIT produced no out-of-sample "
    "p-value at all. Three of the four records carry no real out-of-sample p-value whatsoever -- only "
    "BTC_VOL_EXPANSION_BREAKOUT reported one, and it failed. The plausible economic stories (redemption "
    "arbitrage, volatility regime shift, trend-confirmed pullback) were never actually tested against "
    "enough out-of-sample data to distinguish real edge from noise, and the two that looked promising "
    "in-sample did not survive contact with fresh data."
)

# fixable: FLIPPED from the original draft's False to True -- see the
# directive's own report for the full reasoning. Summary: two of the four
# records showed real in-sample promise (PROMISING_WATCHLIST) that a thin
# out-of-sample sample couldn't confirm or deny -- this project's own
# established precedent (the ORIGINAL hand-curated RANGE_MEAN_REVERSION
# graveyard entry, repair_candidates.json's RMR_CONFIRMATION_METALS_WEEKLY)
# already treats "sample-too-thin" failures as the most fixable kind, not
# a structurally dead mechanism -- "sample-too-thin" paired with
# fixable=false was an internal tension in the original draft that a human
# reviewer should be able to see resolved one way, not asked to untangle.
CORRECTED_FIXABLE = True
CORRECTED_FIXABLE_NOTE = (
    "Corrected 2026-08-06 from the original draft's fixable=false: 2 of the 4 records were "
    "PROMISING_WATCHLIST in-sample (BTC_VOL_EXPANSION_BREAKOUT, PAXG_PREMIUM_FADE_DYNAMIC_EXIT) -- a "
    "real positive in-sample signal a thin out-of-sample sample could not confirm or deny, matching "
    "this project's own established 'sample-too-thin is the most fixable failure_pattern' precedent "
    "(the original hand-curated RANGE_MEAN_REVERSION entry, repair_candidates.json's own "
    "RMR_CONFIRMATION_METALS_WEEKLY). A human reviewer may still disagree -- this is a corrected "
    "recommendation, not a final decision; review_status stays pending_human_approval."
)


def correct() -> bool:
    """Returns True if a correction was applied, False if already correct
    (idempotent) or the target entry isn't present."""
    if not DRAFTS_PATH.exists():
        print(f"{DRAFTS_PATH} does not exist -- nothing to correct.")
        return False
    drafts = json.loads(DRAFTS_PATH.read_text(encoding="utf-8"))
    entry = next((d for d in drafts if d.get("name") == TARGET_NAME), None)
    if entry is None:
        print(f"{TARGET_NAME!r} not found in {DRAFTS_PATH} -- nothing to correct.")
        return False
    if entry.get("review_status") != "pending_human_approval":
        raise RuntimeError(
            f"{TARGET_NAME!r} is at review_status={entry.get('review_status')!r}, not "
            f"pending_human_approval -- refusing to correct an already-decided entry."
        )
    if entry.get("why_it_died") == CORRECTED_WHY_IT_DIED and entry.get("fixable") == CORRECTED_FIXABLE:
        print(f"{TARGET_NAME!r} is already corrected -- no-op.")
        return False

    entry["why_it_died"] = CORRECTED_WHY_IT_DIED
    entry["fixable"] = CORRECTED_FIXABLE
    entry["fixable_note"] = CORRECTED_FIXABLE_NOTE
    entry["correction_provenance"] = {
        "corrected_at": "2026-08-06T05:30:00+00:00",
        "reason": (
            "CC-1 directive item 1: original draft claimed 'two had no OOS p-value' -- real count is "
            "three (PAXG_PEG_REVERSION, SOL_TREND_ALIGNED_PULLBACK, PAXG_PREMIUM_FADE_DYNAMIC_EXIT all "
            "have p_value_oos=None); original draft also collapsed two distinct failure shapes "
            "(IS-promising/OOS-died vs. died-on-both-halves) into one narrative. Root cause: the LLM "
            "was shown the correct p_value_oos data (confirmed via the real reconstructed prompt) but "
            "miscounted in its own free-text synthesis; verdict_is/verdict_oos were never in the prompt "
            "at all. Hand-corrected rather than re-drafted via a second LLM call -- see this script's "
            "own module docstring for the full reasoning."
        ),
        "original_why_it_died": (
            "Across a physically-arbitraged asset (PAXG long and short) and two crypto variants (BTC "
            "volatility breakout, SOL trend pullback), none produced usable evidence: two had no OOS "
            "p-value at all and the one that reported a p-value (0.26) failed significance, meaning the "
            "plausible economic stories (redemption arbitrage, volatility regime shift, trend-confirmed "
            "pullback) were never actually tested against enough data to distinguish real edge from "
            "noise. The family dies not because the mechanisms are disproven but because they were "
            "asserted via narrative and never survived contact with sufficient out-of-sample trades."
        ),
        "original_fixable": False,
    }
    DRAFTS_PATH.write_text(json.dumps(drafts, indent=2) + "\n", encoding="utf-8")
    print(f"Corrected {TARGET_NAME!r} in {DRAFTS_PATH}. Still review_status=pending_human_approval -- not approved.")
    return True


if __name__ == "__main__":
    correct()
