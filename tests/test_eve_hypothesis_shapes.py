from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.eve import hypothesis_shapes


class BuildHypothesisRecordTest(unittest.TestCase):
    def test_preserves_raw_hypothesis_verbatim_except_the_injected_generated_at(self) -> None:
        # generated_at is the ONE deliberate exception to "verbatim" -- see
        # _inject_generated_at's own docstring (Session 0-B follow-up fix).
        raw = {"anything": "goes", "nested": {"a": [1, 2, 3]}, "not_dsl_shaped_at_all": True}
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        record = hypothesis_shapes.build_hypothesis_record(raw, session_id="s1", turn_index=2, tool_use_id="toolu_1", now=now)
        self.assertEqual({k: v for k, v in record["raw_hypothesis"].items() if k != "generated_at"}, raw)
        self.assertEqual(record["raw_hypothesis"]["generated_at"], now.isoformat())

    def test_does_not_mutate_the_input_raw_hypothesis_dict(self) -> None:
        raw = {"hypothesis_name": "X"}
        hypothesis_shapes.build_hypothesis_record(raw, session_id="s1", turn_index=0, tool_use_id="toolu_1")
        self.assertEqual(raw, {"hypothesis_name": "X"}, "the caller's own dict must never be mutated in place")

    def test_generated_at_is_always_stamped_with_the_real_proposal_time_never_eves_own_value(self) -> None:
        # Eve has no reason to supply this field, but if she somehow did,
        # the platform's own clock must win -- trusting a self-reported
        # value would reopen the lookahead-cutoff manipulation risk this
        # field exists to close.
        raw = {"hypothesis_name": "X", "generated_at": "2000-01-01T00:00:00+00:00"}
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        record = hypothesis_shapes.build_hypothesis_record(raw, session_id="s1", turn_index=0, tool_use_id="toolu_1", now=now)
        self.assertEqual(record["raw_hypothesis"]["generated_at"], now.isoformat())

    def test_fails_loudly_on_a_non_dict_raw_hypothesis_rather_than_silently_proceeding(self) -> None:
        with self.assertRaises(TypeError):
            hypothesis_shapes.build_hypothesis_record("not-a-dict", session_id="s1", turn_index=0, tool_use_id="toolu_1")

    def test_starts_unscored(self) -> None:
        record = hypothesis_shapes.build_hypothesis_record({}, session_id="s1", turn_index=0, tool_use_id="toolu_1")
        self.assertEqual(record["testability"], hypothesis_shapes.TESTABILITY_UNSCORED)
        self.assertIsNone(record["verdict_is"])
        self.assertIsNone(record["verdict_oos"])
        self.assertEqual(record["contamination_tags"], [])

    def test_carries_session_linkage(self) -> None:
        record = hypothesis_shapes.build_hypothesis_record({}, session_id="s1", turn_index=3, tool_use_id="toolu_9")
        self.assertEqual(record["session_id"], "s1")
        self.assertEqual(record["turn_index"], 3)
        self.assertEqual(record["tool_use_id"], "toolu_9")


class ExtractProposedHypothesesTest(unittest.TestCase):
    def test_extracts_one_record_per_propose_call(self) -> None:
        blocks = [
            {"type": "text", "text": "reasoning"},
            {"type": "tool_use", "id": "toolu_a", "name": "propose_hypothesis", "input": {"hypothesis": {"name": "A"}}},
            {"type": "tool_use", "id": "toolu_b", "name": "propose_hypothesis", "input": {"hypothesis": {"name": "B"}}},
            {"type": "tool_use", "id": "toolu_c", "name": "end_session", "input": {"summary": "x", "n_hypotheses_proposed": 2}},
        ]
        records = hypothesis_shapes.extract_proposed_hypotheses(blocks, session_id="s1", turn_index=0)
        self.assertEqual(len(records), 2)
        self.assertEqual({r["raw_hypothesis"]["name"] for r in records}, {"A", "B"})

    def test_no_propose_calls_returns_empty_list(self) -> None:
        blocks = [{"type": "text", "text": "just thinking out loud"}]
        self.assertEqual(hypothesis_shapes.extract_proposed_hypotheses(blocks, session_id="s1", turn_index=0), [])

    def test_malformed_hypothesis_input_is_skipped_not_fabricated(self) -> None:
        blocks = [{"type": "tool_use", "id": "toolu_bad", "name": "propose_hypothesis", "input": {"hypothesis": "not-an-object"}}]
        self.assertEqual(hypothesis_shapes.extract_proposed_hypotheses(blocks, session_id="s1", turn_index=0), [])


if __name__ == "__main__":
    unittest.main()
