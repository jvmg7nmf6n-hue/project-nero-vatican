"""CC-1 Factory Loop directive, item 6: TEST -> GRAVEYARD, with distillation.

Covers: family grouping from real DIED records (both agents), the
DIED-count trigger, the LLM draft step (closed-taxonomy validation,
structural fields computed from members not trusted from the LLM), the
REVIEW_PENDING human-approval gate (EntryNotApprovedError), the two-file
atomic commit (item 6a), the cap-and-merge behavior (item 6b), and item 6d's
success-feedback reader."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nero_core.research_agent import graveyard_distillation as gd


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _claude_payload(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}], "usage": {"input_tokens": 100, "output_tokens": 100}}


FAILURE_PATTERNS = [
    {"name": "FVG_REVERSION", "family": "Fair Value Gap", "failure_pattern": "edge-over-random-negative", "fixable": True, "source_doc": "doc1"},
    {"name": "REGIME_TRANSITION", "family": "Regime Filter", "failure_pattern": "regime-filter-only", "fixable": False, "source_doc": "doc2"},
]


class LoadDiedRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, data) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(data))
        return path

    def test_adam_died_record_uses_precomputed_matched_pattern_name(self) -> None:
        test_results_path = self._write("agent_test_results.json", [
            {"hypothesis_name": "FVG_VARIANT_2", "verdict": "DIED", "test": {"bootstrap_ci": {"mean_r": -0.2}}},
            {"hypothesis_name": "SURVIVED_ONE", "verdict": "SURVIVED"},
        ])
        hypotheses_path = self._write("agent_hypotheses.json", [
            {
                "hypothesis_name": "FVG_VARIANT_2", "mechanism": "gap fade", "origin_agent": "adam", "run_id": "run-1",
                "graveyard_check": {"is_likely_repeat": True, "matched_pattern_name": "FVG_REVERSION"},
            },
        ])
        eve_path = self._write("eve_hypotheses.json", [])

        died = gd.load_died_records(test_results_path, hypotheses_path, eve_path, failure_patterns=FAILURE_PATTERNS)
        self.assertEqual(len(died), 1)
        self.assertEqual(died[0].hypothesis_name, "FVG_VARIANT_2")
        self.assertEqual(died[0].matched_family, "Fair Value Gap")
        self.assertEqual(died[0].origin_agent, "adam")

    def test_eve_died_record_computes_family_fresh_via_check_graveyard_match(self) -> None:
        test_results_path = self._write("agent_test_results.json", [])
        hypotheses_path = self._write("agent_hypotheses.json", [])
        eve_path = self._write("eve_hypotheses.json", [
            {
                "verdict_combined": "DIED", "origin_agent": "eve", "session_id": "eve-1",
                "raw_hypothesis": {"hypothesis_name": "FVG_EVE_VARIANT", "mechanism": "fair value gap fade entry"},
            },
        ])

        died = gd.load_died_records(test_results_path, hypotheses_path, eve_path, failure_patterns=FAILURE_PATTERNS)
        self.assertEqual(len(died), 1)
        self.assertEqual(died[0].origin_agent, "eve")
        # May or may not match depending on lexical overlap threshold -- just
        # confirm it ran the real function and returned SOME classification
        # (None or a real family name), not a crash.
        self.assertIn(died[0].matched_family, (None, "Fair Value Gap"))

    def test_unmatched_died_record_has_no_family(self) -> None:
        test_results_path = self._write("agent_test_results.json", [
            {"hypothesis_name": "TOTALLY_NOVEL_MECHANISM", "verdict": "DIED"},
        ])
        hypotheses_path = self._write("agent_hypotheses.json", [
            {"hypothesis_name": "TOTALLY_NOVEL_MECHANISM", "mechanism": "something never seen before", "origin_agent": "adam",
             "graveyard_check": {"is_likely_repeat": False, "matched_pattern_name": None}},
        ])
        eve_path = self._write("eve_hypotheses.json", [])

        died = gd.load_died_records(test_results_path, hypotheses_path, eve_path, failure_patterns=FAILURE_PATTERNS)
        self.assertIsNone(died[0].matched_family)
        self.assertEqual(gd.find_unmatched_died_records(died), died)
        self.assertEqual(gd.group_died_by_family(died), {})


class FamilyGroupingTest(unittest.TestCase):
    def _died(self, name: str, family: str | None, agent: str = "adam") -> gd.DiedRecord:
        return gd.DiedRecord(hypothesis_name=name, mechanism="m", origin_agent=agent, matched_family=family, p_value_oos=0.5)

    def test_family_ready_once_threshold_reached(self) -> None:
        records = [self._died("A", "Fair Value Gap"), self._died("B", "Fair Value Gap"), self._died("C", "Fair Value Gap")]
        ready = gd.find_families_ready_for_distillation(records, threshold=3)
        self.assertIn("Fair Value Gap", ready)
        self.assertEqual(len(ready["Fair Value Gap"]), 3)

    def test_family_below_threshold_not_ready(self) -> None:
        records = [self._died("A", "Fair Value Gap"), self._died("B", "Fair Value Gap")]
        ready = gd.find_families_ready_for_distillation(records, threshold=3)
        self.assertEqual(ready, {})

    def test_default_threshold_is_three(self) -> None:
        self.assertEqual(gd.DIED_COUNT_TRIGGER, 3)


class DraftDistillationEntryTest(unittest.TestCase):
    def _members(self) -> list:
        return [
            gd.DiedRecord("A", "gap fade mechanism", "adam", "Fair Value Gap", 0.4),
            gd.DiedRecord("B", "gap fade mechanism variant", "eve", "Fair Value Gap", 0.6),
            gd.DiedRecord("C", "gap fade mechanism third", "adam", "Fair Value Gap", 0.3),
        ]

    def test_valid_draft_produces_review_pending_entry_with_computed_structural_fields(self) -> None:
        payload = _claude_payload({
            "name": "FVG_CROSS_ASSET", "failure_pattern": "edge-over-random-negative",
            "why_it_died": "the gap-touch trigger adds no value beyond randomly-timed entries",
            "fixable": True, "source_doc": "doc.md",
            "n_no_oos_pvalue": 0,  # all 3 fixture members have a real p_value_oos
        })
        with patch("nero_core.research_agent.graveyard_distillation.requests.post", return_value=_FakeResponse(payload)):
            result = gd.draft_distillation_entry("Fair Value Gap", self._members(), "fake-key")

        self.assertIsNone(result.error)
        entry = result.entry
        self.assertEqual(entry["review_status"], gd.REVIEW_PENDING)
        self.assertEqual(entry["family"], "Fair Value Gap")
        self.assertEqual(set(entry["covers"]), {"A", "B", "C"})
        self.assertEqual(entry["origin_agent_breakdown"], {"adam": 2, "eve": 1})

    def test_miscounted_no_oos_pvalue_claim_is_rejected_not_trusted(self) -> None:
        # CC-1 directive item 1c: regression guard on the real 2026-08-06
        # "Range Mean Reversion" incident -- the LLM was shown the correct
        # data but still miscounted in its own free-text prose. This is the
        # ONE claim in the drafted output that's mechanically checkable, so
        # it must never be trusted from the LLM's own arithmetic.
        members = [
            gd.DiedRecord("A", "m", "adam", "Fair Value Gap", None),
            gd.DiedRecord("B", "m", "eve", "Fair Value Gap", None),
            gd.DiedRecord("C", "m", "adam", "Fair Value Gap", 0.3),
        ]
        payload = _claude_payload({
            "name": "FVG_CROSS_ASSET", "failure_pattern": "edge-over-random-negative",
            "why_it_died": "x", "fixable": True, "source_doc": "d",
            "n_no_oos_pvalue": 1,  # real count is 2 (A and B both have p_value_oos=None)
        })
        with patch("nero_core.research_agent.graveyard_distillation.requests.post", return_value=_FakeResponse(payload)):
            result = gd.draft_distillation_entry("Fair Value Gap", members, "fake-key")

        self.assertIsNone(result.entry)
        self.assertIn("real count", result.error)
        self.assertIn("2", result.error)
        # Still billed -- the call reached Anthropic and was processed,
        # matching this module's own existing "rejected but billed" pattern
        # for an invalid failure_pattern.
        self.assertGreater(result.cost_usd, 0.0)

    def test_correct_no_oos_pvalue_claim_with_some_none_and_some_real_is_accepted(self) -> None:
        members = [
            gd.DiedRecord("A", "m", "adam", "Fair Value Gap", None),
            gd.DiedRecord("B", "m", "eve", "Fair Value Gap", 0.5),
        ]
        payload = _claude_payload({
            "name": "FVG_CROSS_ASSET", "failure_pattern": "edge-over-random-negative",
            "why_it_died": "x", "fixable": True, "source_doc": "d",
            "n_no_oos_pvalue": 1,  # correct: only A has p_value_oos=None
        })
        with patch("nero_core.research_agent.graveyard_distillation.requests.post", return_value=_FakeResponse(payload)):
            result = gd.draft_distillation_entry("Fair Value Gap", members, "fake-key")

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.entry)

    def test_failure_pattern_outside_closed_vocabulary_is_rejected_not_coerced(self) -> None:
        payload = _claude_payload({
            "name": "BAD_ENTRY", "failure_pattern": "no-improvement-over-baseline",
            "why_it_died": "x", "fixable": True, "source_doc": "d",
        })
        with patch("nero_core.research_agent.graveyard_distillation.requests.post", return_value=_FakeResponse(payload)):
            result = gd.draft_distillation_entry("Fair Value Gap", self._members(), "fake-key")

        self.assertIsNone(result.entry)
        self.assertIn("closed vocabulary", result.error)

    def test_no_api_key_makes_no_call(self) -> None:
        with patch("nero_core.research_agent.graveyard_distillation.requests.post") as mock_post:
            result = gd.draft_distillation_entry("Fair Value Gap", self._members(), "")
        mock_post.assert_not_called()
        self.assertIsNone(result.entry)


class CommitGraveyardEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.graveyard_path = self.tmp / "graveyard.json"
        self.failure_patterns_path = self.tmp / "failure_patterns.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _approved_entry(self, **overrides) -> dict:
        entry = {
            "name": "FVG_CROSS_ASSET", "family": "Fair Value Gap", "failure_pattern": "edge-over-random-negative",
            "why_it_died": "no edge over random", "fixable": True, "source_doc": "doc.md",
            "covers": ["A", "B", "C"], "origin_agent_breakdown": {"adam": 2, "eve": 1},
            "review_status": "approved",
        }
        entry.update(overrides)
        return entry

    def test_refuses_to_write_a_still_pending_entry(self) -> None:
        entry = self._approved_entry(review_status=gd.REVIEW_PENDING)
        with self.assertRaises(gd.EntryNotApprovedError):
            gd.commit_graveyard_entry(entry, self.graveyard_path, self.failure_patterns_path)
        self.assertFalse(self.graveyard_path.exists())
        self.assertFalse(self.failure_patterns_path.exists())

    def test_approved_entry_writes_both_files(self) -> None:
        self.graveyard_path.write_text("[]")
        self.failure_patterns_path.write_text("[]")
        entry = self._approved_entry()
        gd.commit_graveyard_entry(entry, self.graveyard_path, self.failure_patterns_path, cap=30)

        graveyard = json.loads(self.graveyard_path.read_text())
        failure_patterns = json.loads(self.failure_patterns_path.read_text())
        self.assertEqual({g["name"] for g in graveyard}, {"A", "B", "C"})
        self.assertEqual(len(failure_patterns), 1)
        self.assertEqual(failure_patterns[0]["name"], "FVG_CROSS_ASSET")
        self.assertEqual(failure_patterns[0]["covers"], ["A", "B", "C"])

    def test_does_not_duplicate_an_existing_graveyard_name(self) -> None:
        self.graveyard_path.write_text(json.dumps([{"name": "A", "family": "Fair Value Gap", "what_was_tested": "A", "why_it_died": "x", "source_doc": "d"}]))
        self.failure_patterns_path.write_text("[]")
        entry = self._approved_entry()
        gd.commit_graveyard_entry(entry, self.graveyard_path, self.failure_patterns_path, cap=30)

        graveyard = json.loads(self.graveyard_path.read_text())
        names = [g["name"] for g in graveyard]
        self.assertEqual(names.count("A"), 1)
        self.assertIn("B", names)
        self.assertIn("C", names)

    def test_at_cap_merges_into_existing_same_family_entry_instead_of_appending(self) -> None:
        self.graveyard_path.write_text("[]")
        existing = [
            {"name": f"OLD_{i}", "family": "Regime Filter" if i else "Fair Value Gap", "failure_pattern": "regime-filter-only",
             "fixable": False, "source_doc": "d", "covers": [f"OLD_{i}"], "origin_agent_breakdown": {"adam": 1}}
            for i in range(30)
        ]
        self.failure_patterns_path.write_text(json.dumps(existing))
        entry = self._approved_entry()
        result = gd.commit_graveyard_entry(entry, self.graveyard_path, self.failure_patterns_path, cap=30)

        self.assertTrue(result["failure_patterns_merged"])
        failure_patterns = json.loads(self.failure_patterns_path.read_text())
        self.assertEqual(len(failure_patterns), 30)  # no new entry appended
        merged = next(fp for fp in failure_patterns if fp["name"] == "OLD_0")
        self.assertEqual(set(merged["covers"]), {"OLD_0", "A", "B", "C"})
        self.assertEqual(merged["origin_agent_breakdown"]["adam"], 1 + 2)
        self.assertEqual(merged["origin_agent_breakdown"]["eve"], 1)

    def test_at_cap_with_no_matching_family_raises_rather_than_guessing(self) -> None:
        self.graveyard_path.write_text("[]")
        existing = [
            {"name": f"OLD_{i}", "family": "Regime Filter", "failure_pattern": "regime-filter-only",
             "fixable": False, "source_doc": "d"}
            for i in range(30)
        ]
        self.failure_patterns_path.write_text(json.dumps(existing))
        entry = self._approved_entry(family="Never Before Seen Family")
        with self.assertRaises(ValueError):
            gd.commit_graveyard_entry(entry, self.graveyard_path, self.failure_patterns_path, cap=30)
        # neither file touched on failure
        self.assertEqual(json.loads(self.failure_patterns_path.read_text()), existing)


class LoadSurvivedTrialContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty_list(self) -> None:
        path = self.tmp / "forward_trial.json"
        self.assertEqual(gd.load_survived_trial_context(path), [])

    def test_filters_to_survived_trial_status_only(self) -> None:
        path = self.tmp / "forward_trial.json"
        path.write_text(json.dumps([
            {"trial_id": "t1", "status": "OPEN"},
            {"trial_id": "t2", "status": "SURVIVED_TRIAL"},
            {"trial_id": "t3", "status": "FAILED_TRIAL"},
        ]))
        result = gd.load_survived_trial_context(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trial_id"], "t2")


if __name__ == "__main__":
    unittest.main()
