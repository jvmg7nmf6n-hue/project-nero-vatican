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
        # CC-1 directive item 3 (2026-08-05): truth-in-labeling reframe --
        # the original phrase was genuinely ambiguous between "each session's
        # own family, corrected independently" (what apply_fdr_correction
        # actually does, confirmed at its nero_core/eve/pipeline.py call
        # site) and "one family spanning all 8 sessions" (the more natural
        # reading). eve_must_clear now states the per-session reality
        # plainly; the original wording is preserved byte-identical below,
        # never silently lost.
        self.assertEqual(
            pre_reg["eve_must_clear"],
            "5% OOS survival, FDR-corrected PER SESSION (each of the 8 pre-registered sessions independently "
            "clears its own 5%-FDR-corrected bar -- this is NOT one pooled correction spanning all 8 sessions' "
            "hypotheses together)",
        )
        self.assertEqual(
            pre_reg["eve_must_clear_original_wording"],
            "5% OOS survival, FDR-corrected, across the full cross-asset family",
        )
        self.assertIn("8", pre_reg["sessions_budgeted"])

    def test_fdr_reframe_provenance_is_recorded_with_real_not_stale_numbers(self) -> None:
        # Item 3a: the provenance note must cite REAL re-derived counts, not
        # a remembered/stale "0/0" -- see docs/investigations/
        # factory_loop_implementation_report.md for full sourcing.
        provenance = self.registry["pre_registration"]["eve_must_clear_reframe_provenance"]
        self.assertTrue(provenance["reason"])
        counts = provenance["real_counts_at_time_of_reframe"]
        self.assertEqual(counts["adam_survived_combined"], 0)
        self.assertEqual(counts["adam_promising_watchlist_combined"], 0)
        self.assertEqual(counts["eve_survived_combined"], 0)
        self.assertEqual(counts["eve_promising_watchlist_combined"], 0)
        self.assertIn("BTC_VOL_EXPANSION_BREAKOUT", counts["eve_note"])
        baseline = counts["random_baseline_k200_promising_watchlist"]
        self.assertEqual(baseline["ETH_4h"], 3)
        self.assertEqual(baseline["PAXG_4h"], 8)

    def test_no_session_reason_asserts_the_stale_pooled_fdr_claim(self) -> None:
        # Regression guard: the ambiguous "evaluated across all 8 sessions
        # together, not session-by-session" phrasing must never reappear in
        # a session's own reason text -- apply_fdr_correction has always
        # been per-session (0d), so a session record asserting the pooled
        # reading would misstate the code's real behavior.
        for entry in self.registry["sessions"]:
            self.assertNotIn(
                "evaluated across all 8 sessions together, not session-by-session",
                entry.get("reason", ""),
                f"{entry['session_id']}'s reason text still asserts the stale pooled-FDR-family claim",
            )

    def test_every_session_entry_has_a_counts_flag_and_a_reason(self) -> None:
        for entry in self.registry["sessions"]:
            self.assertIn("session_id", entry)
            self.assertIn("counts_toward_pre_registered_8", entry)
            self.assertIsInstance(entry["counts_toward_pre_registered_8"], bool)
            self.assertTrue(entry.get("reason"), f"{entry['session_id']} has no reason recorded")

    def test_exactly_one_session_counts_so_far(self) -> None:
        # 2026-08-04: eve-20260804T020749Z-4cf6e4c9 is Session 1 of 8 -- the
        # first session to run to completion under the fully-corrected
        # system. Every OTHER entry (2 spec-defect sessions, 3 crashed
        # attempts) must still not count.
        counting = [e for e in self.registry["sessions"] if e["counts_toward_pre_registered_8"]]
        self.assertEqual(len(counting), 1)
        self.assertEqual(counting[0]["session_id"], "eve-20260804T020749Z-4cf6e4c9")
        self.assertEqual(self.registry["next_countable_session_number"], 2)

    def test_freshness_gate_reversal_is_recorded_with_dates_and_confirmed_homogeneity(self) -> None:
        # CC-1 correction directive (2026-08-05): the binding freshness gate
        # (item 4e/7c, shipped in commit 61d78a8) was reverted to
        # informational-only the same day. This provenance entry must never
        # silently disappear -- mirrors test_fdr_reframe_provenance_is_
        # recorded_with_real_not_stale_numbers's own style for item 3a.
        provenance = self.registry["pre_registration"]["freshness_gate_reversal_provenance"]
        self.assertEqual(provenance["enabled_commit"], "61d78a8")
        self.assertEqual(provenance["enabled_dated"], "2026-08-05")
        self.assertTrue(provenance["reverted_dated"])
        self.assertTrue(provenance["reason"])
        # The reason must state the REAL cause (session-scoped attribution),
        # not just "it disqualified too much" -- a future reader must be
        # able to see WHY retuning the window would not have fixed it.
        self.assertIn("SESSION-SCOPED", provenance["reason"])
        self.assertIn("unsatisfiable", provenance["reason"])
        # Homogeneity must be a CONFIRMED fact, not an assumption -- see the
        # provenance's own basis field for how this was derived from data.
        self.assertFalse(provenance["any_countable_session_ran_while_binding"])
        self.assertTrue(provenance["any_countable_session_ran_while_binding_basis"])
        self.assertIn("homogeneous", provenance["homogeneity_confirmation"])

    def test_per_hypothesis_citation_freshness_provenance_is_recorded(self) -> None:
        # CC-1 directive (2026-08-05): per-hypothesis freshness attribution
        # via explicit source citation. Mirrors the freshness_gate_reversal_
        # provenance test's own style: this provenance entry must never
        # silently disappear, and must state the mechanism stays strictly
        # informational.
        provenance = self.registry["pre_registration"]["per_hypothesis_citation_freshness_provenance"]
        self.assertTrue(provenance["reason"])
        self.assertIn("16", provenance["pre_citation_backfill"])
        self.assertIn("unscoreable_pre_citation", provenance["pre_citation_backfill"])
        self.assertIn("UNLEARNABLE", provenance["incentive_analysis"])

    def test_session_count_reconciliation_is_recorded_not_silently_changed(self) -> None:
        # 2026-08-03: the pre-registered session count was reconciled from an
        # earlier N=5 (docs/investigations/eve_engine_v1_report.md's original
        # kill-criterion section, predating the 3 Aug pre-registration) to the
        # authoritative N=8 -- this must be provenance-tracked, never a silent
        # overwrite of a number that once said something else.
        provenance = self.registry["pre_registration"]["session_count_provenance"]
        self.assertEqual(provenance["authoritative_value"], 8)
        self.assertEqual(provenance["superseded_prior_value"], 5)
        self.assertTrue(provenance["reason"])


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

    def test_every_countable_session_has_at_least_one_hypothesis_record(self) -> None:
        # CC-1 Master Directive, Phase 1.1e: the registry's own counting_rule
        # field is prose in a hand-maintained JSON file -- "a session counts
        # only once it produces at least one hypothesis that was actually
        # eligible to be scored against real data." Nothing before this test
        # code-enforced that rule; a human could type
        # counts_toward_pre_registered_8=true for a session with zero real
        # hypothesis records and nothing would catch it. This cross-checks
        # every registry entry marked true against the REAL, committed
        # docs/site_data/eve_hypotheses.json -- not the registry's own
        # prose, and not the (possibly crashed, possibly file-less)
        # eve_sessions/*.json record.
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        hypotheses = json.loads(storage.DEFAULT_HYPOTHESES_PATH.read_text(encoding="utf-8"))
        hypothesis_session_ids = {r.get("session_id") for r in hypotheses if isinstance(r, dict)}

        for entry in registry["sessions"]:
            if entry.get("counts_toward_pre_registered_8"):
                self.assertIn(
                    entry["session_id"],
                    hypothesis_session_ids,
                    f"{entry['session_id']} is marked counts_toward_pre_registered_8=true but has "
                    f"ZERO hypothesis records under that session_id in {storage.DEFAULT_HYPOTHESES_PATH} "
                    f"-- a countable session must have produced at least one real, scoreable data point.",
                )


if __name__ == "__main__":
    unittest.main()
