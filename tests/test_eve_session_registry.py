"""Regression tests for docs/site_data/eve_session_registry.json -- the
explicit, durable record of which Eve sessions count toward the
pre-registered 8-session bar (spec item 1, added after Session 0). This is
real repo data, not synthetic fixtures: these tests cross-check the registry
against the actual budget ledger and the actual session record file, so the
registry can never silently drift out of sync with what really happened."""
from __future__ import annotations

import json
import unittest

from nero_core.eve import storage

REGISTRY_PATH = storage.REPO_ROOT / "docs" / "site_data" / "eve_session_registry.json"


class RegistryShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def test_pre_registration_bar_is_unchanged_from_its_own_stated_numbers(self) -> None:
        pre_reg = self.registry["pre_registration"]
        self.assertEqual(pre_reg["eve_must_clear"], "5% OOS survival, FDR-corrected, across the full cross-asset family")
        self.assertIn("8", pre_reg["sessions_budgeted"])

    def test_every_session_entry_has_a_counts_flag_and_a_reason(self) -> None:
        for entry in self.registry["sessions"]:
            self.assertIn("session_id", entry)
            self.assertIn("counts_toward_pre_registered_8", entry)
            self.assertIsInstance(entry["counts_toward_pre_registered_8"], bool)
            self.assertTrue(entry.get("reason"), f"{entry['session_id']} has no reason recorded")

    def test_no_session_counts_yet(self) -> None:
        # As of this fix landing, nothing has run under the corrected system
        # yet -- every existing session predates the DSL vocabulary + validator.
        self.assertTrue(all(not e["counts_toward_pre_registered_8"] for e in self.registry["sessions"]))
        self.assertEqual(self.registry["next_countable_session_number"], 1)


class RegistryMatchesRealLedgerTest(unittest.TestCase):
    """Cross-checks the registry's session_ids against the real, actual
    docs/site_data/eve_budget_ledger.json -- every session_id the ledger has
    ever seen must be accounted for in the registry (accounted for, not
    necessarily countable)."""

    def test_every_ledger_session_id_is_present_in_the_registry(self) -> None:
        ledger = json.loads(storage.DEFAULT_BUDGET_LEDGER_PATH.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

        ledger_session_ids = {entry["session_id"] for entry in ledger}
        registry_session_ids = {entry["session_id"] for entry in registry["sessions"]}

        missing = ledger_session_ids - registry_session_ids
        self.assertEqual(missing, set(), f"ledger has session_id(s) the registry never accounts for: {missing}")

    def test_the_one_real_session_file_that_exists_matches_its_registry_classification(self) -> None:
        session_files = sorted(storage.EVE_SESSIONS_DIR.glob("*.json"))
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        registry_by_id = {e["session_id"]: e for e in registry["sessions"]}

        for path in session_files:
            record = json.loads(path.read_text(encoding="utf-8"))
            session_id = record["session_id"]
            self.assertIn(session_id, registry_by_id, f"{session_id} has a real session file but no registry entry")
            self.assertEqual(
                record.get("counts_toward_pre_registered_8"),
                registry_by_id[session_id]["counts_toward_pre_registered_8"],
                f"{session_id}'s own file and the registry disagree on whether it counts",
            )


if __name__ == "__main__":
    unittest.main()
