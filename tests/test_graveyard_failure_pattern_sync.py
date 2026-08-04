"""CC-1 follow-up (urgent items, item 1): regression guard against
docs/site_data/graveyard.json (public /graveyard page, read by nothing in
nero_core/) and docs/site_data/failure_patterns.json (the file Adam and Eve
actually read as graveyard context -- see nero_core.eve.context and
nero_core.research_agent.hypothesis_gen/pipeline) silently re-diverging.

Both files are 100% hand-curated -- no code anywhere writes either one (a
human writes an investigation markdown doc, then hand-types a JSON entry).
As of 2026-08-04, 9 real graveyard.json entries (FVG_REVERSION cross-asset
extension; all 4 MACRO_RISK_ON extensions; REGIME_TRANSITION; RANGE_MATURITY
gate; REGIME_ALLOCATOR; the RMR EUR/USD-4h/ETH-4h variant experiments) had
never been distilled into failure_patterns.json -- meaning Adam and Eve were
reasoning, on every real session, with zero knowledge of 9 already-diagnosed
failures, and hypothesis_gen.check_graveyard_match's own duplicate-detection
could never flag a new hypothesis resembling any of them either, since that
function only ever compares against failure_patterns.json's own entries.

This test enforces the ONE direction that actually matters for that harm:
every graveyard.json name must be represented in failure_patterns.json.
The reverse is NOT enforced here -- failure_patterns.json legitimately
carries at least one entry (RANGE_MEAN_REVERSION) that has no graveyard.json
counterpart by that exact name, because it represents a still-open repair
candidate (see docs/site_data/repair_candidates.json's own
RMR_CONFIRMATION_METALS_WEEKLY entry) rather than a permanently-closed
graveyard.json family -- a real, legitimate scope difference between the two
files, not a bug."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAVEYARD_PATH = REPO_ROOT / "docs" / "site_data" / "graveyard.json"
FAILURE_PATTERNS_PATH = REPO_ROOT / "docs" / "site_data" / "failure_patterns.json"

REQUIRED_FAILURE_PATTERN_FIELDS = ("name", "family", "failure_pattern", "fixable", "source_doc")

# Mirrors website/lib/types.ts's own closed `FailurePattern` union type --
# NOT independently duplicated by choice, this is the ONE place on the
# Python side that enforces it (hypothesis_gen.py/context.py both treat
# failure_pattern as free text with zero validation). Caught for real during
# this fix: a first draft used "no-improvement-over-baseline" for
# REGIME_ALLOCATOR, a value outside this closed set that would have violated
# the frontend's own type contract silently (TS types are compile-time only,
# so a bad value here would not fail any build, only look wrong -- or
# untyped -- on the live site). If website/lib/types.ts's FailurePattern
# union ever changes, update this tuple to match in the same commit.
ALLOWED_FAILURE_PATTERN_VALUES = frozenset({
    "regime-filter-only", "grid-shift-artifact", "edge-over-random-negative",
    "sample-too-thin", "data-blocked", "mechanism-doesn't-transfer",
})


class GraveyardFailurePatternSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graveyard = json.loads(GRAVEYARD_PATH.read_text(encoding="utf-8"))
        self.failure_patterns = json.loads(FAILURE_PATTERNS_PATH.read_text(encoding="utf-8"))
        self.failure_pattern_names = {e["name"] for e in self.failure_patterns}

    def test_every_graveyard_entry_is_represented_in_failure_patterns(self) -> None:
        # The actual invariant that broke: Adam/Eve's own context (built
        # exclusively from failure_patterns.json) must never be missing a
        # real, already-diagnosed graveyard entry.
        missing = [e["name"] for e in self.graveyard if e["name"] not in self.failure_pattern_names]
        self.assertEqual(
            missing, [],
            f"{len(missing)} graveyard.json entries have no failure_patterns.json counterpart -- "
            f"Adam and Eve are reasoning without this context and check_graveyard_match cannot catch "
            f"a duplicate of any of these: {missing}",
        )

    def test_graveyard_and_failure_pattern_names_are_each_internally_unique(self) -> None:
        # A silent duplicate name in either file would make the membership
        # check above pass without actually proving what it claims to.
        graveyard_names = [e["name"] for e in self.graveyard]
        failure_pattern_names = [e["name"] for e in self.failure_patterns]
        self.assertEqual(len(graveyard_names), len(set(graveyard_names)), "duplicate name in graveyard.json")
        self.assertEqual(len(failure_pattern_names), len(set(failure_pattern_names)), "duplicate name in failure_patterns.json")

    def test_every_failure_pattern_entry_has_the_required_fields(self) -> None:
        for entry in self.failure_patterns:
            for field in REQUIRED_FAILURE_PATTERN_FIELDS:
                self.assertIn(field, entry, f"{entry.get('name')!r} is missing required field {field!r}")
            self.assertIsInstance(entry["fixable"], bool, f"{entry['name']!r}'s fixable field must be a real bool, not a string/None")

    def test_every_failure_pattern_value_is_in_the_closed_vocabulary(self) -> None:
        # See website/lib/types.ts's FailurePattern union -- nothing on the
        # Python-writing side enforces this today except this test.
        bad = {e["name"]: e["failure_pattern"] for e in self.failure_patterns if e["failure_pattern"] not in ALLOWED_FAILURE_PATTERN_VALUES}
        self.assertEqual(bad, {}, f"failure_pattern value(s) outside website/lib/types.ts's closed FailurePattern union: {bad}")


if __name__ == "__main__":
    unittest.main()
