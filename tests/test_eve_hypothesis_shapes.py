from __future__ import annotations

import unittest

from nero_core.eve import hypothesis_shapes


class BuildHypothesisRecordTest(unittest.TestCase):
    def test_preserves_raw_hypothesis_verbatim(self) -> None:
        raw = {"anything": "goes", "nested": {"a": [1, 2, 3]}, "not_dsl_shaped_at_all": True}
        record = hypothesis_shapes.build_hypothesis_record(raw, session_id="s1", turn_index=2, tool_use_id="toolu_1")
        self.assertEqual(record["raw_hypothesis"], raw)

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
