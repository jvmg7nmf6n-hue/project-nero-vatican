"""CC-1 follow-up (urgent items, item 1) + CC-1 Factory Loop directive item
6c: regression guard against docs/site_data/graveyard.json (public
/graveyard page, the uncapped full record) and docs/site_data/
failure_patterns.json (the file Adam and Eve actually read as graveyard
context, capped at graveyard_distillation.FAILURE_PATTERNS_CAP -- see
nero_core.eve.context and nero_core.research_agent.hypothesis_gen/pipeline)
silently re-diverging.

Until item 6 (nero_core.research_agent.graveyard_distillation) landed, both
files were 100% hand-curated -- no code wrote either one. As of 2026-08-04,
9 real graveyard.json entries had never been distilled into failure_
patterns.json at all. Since item 6 landed, graveyard_distillation.
commit_graveyard_entry is the only writer, and it writes to both files in
one operation -- but the same divergence risk exists any time either file
is hand-edited outside that path, so this test still enforces it directly
against the real committed files, not just against the writer's own logic.

COVERAGE, NOT ONE-TO-ONE EQUALITY (item 6c, locked decision): once
failure_patterns.json is capped, a distillation MERGES entries rather than
appending, which is a real, intentional divergence from a 1:1 name mapping.
The invariant that survives the cap is coverage: every graveyard.json name
must be covered by EXACTLY ONE failure_patterns.json entry. An un-merged
entry implicitly covers only its own `name` (no `covers` field needed on
the 22 pre-item-6 hand-curated entries -- backward compatible, zero data
changes required for existing entries). A merged entry explicitly lists the
graveyard names it covers in its own `covers` field. A graveyard name
covered by ZERO entries (not yet distilled) or by TWO OR MORE (an
inconsistent double-cover) is a loud test failure either way.

The reverse (every failure_patterns entry must correspond to a graveyard
entry) is NOT enforced -- failure_patterns.json legitimately carries at
least one entry (RANGE_MEAN_REVERSION) that has no graveyard.json
counterpart, because it represents a still-open repair candidate (see
docs/site_data/repair_candidates.json's own RMR_CONFIRMATION_METALS_WEEKLY
entry) rather than a permanently-closed graveyard.json family -- a real,
legitimate scope difference between the two files, not a bug."""
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

    def _coverage_counts(self) -> dict:
        # Every failure_patterns entry covers itself by default (`covers`
        # defaults to [entry["name"]] when absent -- the 22 pre-item-6
        # hand-curated entries all take this default path, requiring zero
        # data migration) plus whatever additional names an explicit
        # `covers` list adds (a merged, capped-distillation entry).
        counts: dict[str, int] = {}
        for entry in self.failure_patterns:
            covers = entry.get("covers") or [entry["name"]]
            for name in covers:
                counts[name] = counts.get(name, 0) + 1
        return counts

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

    def test_every_graveyard_entry_is_covered_by_exactly_one_failure_pattern_entry(self) -> None:
        # Item 6c: coverage, not one-to-one equality -- survives item 6's
        # cap-and-merge behavior. A name covered by 0 entries (silently
        # never distilled) or 2+ entries (an inconsistent double-cover,
        # e.g. a merge that duplicated a name into two different targets)
        # is exactly the failure this test exists to catch.
        counts = self._coverage_counts()
        zero_covered = [e["name"] for e in self.graveyard if counts.get(e["name"], 0) == 0]
        double_covered = [e["name"] for e in self.graveyard if counts.get(e["name"], 0) >= 2]
        self.assertEqual(zero_covered, [], f"graveyard.json name(s) covered by ZERO failure_patterns.json entries: {zero_covered}")
        self.assertEqual(double_covered, [], f"graveyard.json name(s) covered by 2+ failure_patterns.json entries (inconsistent merge): {double_covered}")

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
