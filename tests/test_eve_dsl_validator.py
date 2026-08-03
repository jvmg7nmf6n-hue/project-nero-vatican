"""Regression tests for the pre-submit DSL validator added after Session 0
(eve-20260803T095520Z-394385c7): all 4 hypotheses that real session proposed
came back UNTESTABLE_BY_DSL purely on key-naming mismatches (e.g.
"compare_to" instead of "compare_to_field") -- a spec defect, not an Eve
capability finding, since the DSL supported every mechanism she proposed.
nero_core.eve.session._process_proposed_hypotheses now runs every
propose_hypothesis call through the same rule_dsl parser scoring.py later
scores with, and gives Eve up to MAX_DSL_RETRIES chances to correct a
key-naming failure before it is recorded and scored honestly as
UNTESTABLE_BY_DSL -- "a schema typo should cost one cheap correction turn,
not an entire session."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.eve import llm_client, session, storage


def _without_generated_at(raw_hypothesis: dict) -> dict:
    """build_hypothesis_record now always stamps a server-side generated_at
    (Session 0-B follow-up fix) -- strips it back off so a finalized
    record's raw_hypothesis can still be compared against the original
    fixture dict, which never included that field."""
    return {k: v for k, v in raw_hypothesis.items() if k != "generated_at"}


class _IsolatedStorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self._patches = [
            patch.object(storage, "DEFAULT_HYPOTHESES_PATH", tmp_root / "eve_hypotheses.json"),
            patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", tmp_root / "eve_budget_ledger.json"),
            patch.object(storage, "EVE_SESSIONS_DIR", tmp_root / "eve_sessions"),
            patch("nero_core.eve.context.DEFAULT_QUANT_METRICS_PATH", tmp_root / "quant_metrics.json"),
            patch("nero_core.eve.context.DEFAULT_FAILURE_PATTERNS_PATH", tmp_root / "failure_patterns.json"),
            patch("nero_core.eve.context.DEFAULT_ADAM_HYPOTHESES_PATH", tmp_root / "agent_hypotheses.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


# The exact real-world failure mode from Session 0: "compare_to" instead of
# "compare_to_field" -- structurally malformed per rule_dsl's own
# _parse_condition (has_value=False, has_compare_field=False -> "must set
# exactly one of 'value'/'compare_to_field'").
BROKEN_KEY_NAME_HYPOTHESIS = {
    "hypothesis_name": "SESSION0_STYLE_TYPO",
    "mechanism": "golden cross",
    "asset": "BTC",
    "timeframe": "4h",
    "structured_entry_rule": {"conditions": [{"field": "ma20", "op": "cross_above", "compare_to": "ma50"}]},
    "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0},
}

CORRECTED_HYPOTHESIS = {
    **BROKEN_KEY_NAME_HYPOTHESIS,
    "structured_entry_rule": {"conditions": [{"field": "ma20", "op": "cross_above", "compare_to_field": "ma50"}]},
}

VALID_HYPOTHESIS = {
    "hypothesis_name": "ALWAYS_VALID",
    "mechanism": "trivially valid DSL shape",
    "asset": "BTC",
    "timeframe": "1h",
    "structured_entry_rule": {"conditions": [{"field": "close", "op": "gt", "value": 0}]},
    "structured_exit_plan": {"stop_atr_multiple": 1.0, "target_r_multiple": 1.0},
}


def _propose_result(tool_use_id: str, hypothesis: dict, extra_text: str = "") -> llm_client.LlmTurnResult:
    content = []
    if extra_text:
        content.append({"type": "text", "text": extra_text})
    content.append({
        "type": "tool_use",
        "id": tool_use_id,
        "name": "propose_hypothesis",
        "input": {"hypothesis": hypothesis},
    })
    return llm_client.LlmTurnResult(content_blocks=content, usage={"input_tokens": 1000, "output_tokens": 100}, stop_reason="tool_use", raw_response={"content": content})


def _end_session_result() -> llm_client.LlmTurnResult:
    content = [{"type": "tool_use", "id": "toolu_end", "name": "end_session", "input": {"summary": "done", "n_hypotheses_proposed": 1}}]
    return llm_client.LlmTurnResult(content_blocks=content, usage={"input_tokens": 1100, "output_tokens": 50}, stop_reason="tool_use", raw_response={"content": content})


class ProcessProposedHypothesesUnitTest(unittest.TestCase):
    """Direct unit tests of session._process_proposed_hypotheses -- no LLM
    loop involved, isolates the validator's own decision logic."""

    def test_testable_hypothesis_finalizes_immediately_with_plain_ack(self) -> None:
        content = [{"type": "tool_use", "id": "toolu_1", "name": "propose_hypothesis", "input": {"hypothesis": VALID_HYPOTHESIS}}]
        retry_counts: dict = {}
        correction_log: list = []
        finalized, tool_result_text = session._process_proposed_hypotheses(
            content, "s1", 0, retry_counts, correction_log, datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(len(finalized), 1)
        self.assertEqual(tool_result_text["toolu_1"], session.PROPOSE_HYPOTHESIS_ACK_TEXT)
        self.assertEqual(correction_log, [])

    def test_untestable_hypothesis_first_attempt_is_offered_a_retry_not_finalized(self) -> None:
        content = [{"type": "tool_use", "id": "toolu_1", "name": "propose_hypothesis", "input": {"hypothesis": BROKEN_KEY_NAME_HYPOTHESIS}}]
        retry_counts: dict = {}
        correction_log: list = []
        finalized, tool_result_text = session._process_proposed_hypotheses(
            content, "s1", 0, retry_counts, correction_log, datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(finalized, [], "a hypothesis with retries remaining must not be finalized yet")
        self.assertIn("compare_to_field", tool_result_text["toolu_1"])
        self.assertEqual(len(correction_log), 1)
        self.assertEqual(correction_log[0]["outcome"], "retry_offered")
        self.assertEqual(correction_log[0]["hypothesis_name"], "SESSION0_STYLE_TYPO")
        self.assertEqual(correction_log[0]["attempt_number"], 1)
        self.assertIn("compare_to", correction_log[0]["parser_error"])

    def test_retry_counter_increments_across_calls_for_the_same_name(self) -> None:
        content = [{"type": "tool_use", "id": "toolu_1", "name": "propose_hypothesis", "input": {"hypothesis": BROKEN_KEY_NAME_HYPOTHESIS}}]
        retry_counts: dict = {}
        correction_log: list = []
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        session._process_proposed_hypotheses(content, "s1", 0, retry_counts, correction_log, now)
        session._process_proposed_hypotheses(content, "s1", 1, retry_counts, correction_log, now)
        self.assertEqual(retry_counts["name:SESSION0_STYLE_TYPO"], 2)
        self.assertEqual([e["attempt_number"] for e in correction_log], [1, 2])

    def test_retries_exhausted_finalizes_as_untestable_not_discarded(self) -> None:
        content = [{"type": "tool_use", "id": "toolu_1", "name": "propose_hypothesis", "input": {"hypothesis": BROKEN_KEY_NAME_HYPOTHESIS}}]
        retry_counts = {"name:SESSION0_STYLE_TYPO": session.MAX_DSL_RETRIES}
        correction_log: list = []
        finalized, tool_result_text = session._process_proposed_hypotheses(
            content, "s1", 2, retry_counts, correction_log, datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(len(finalized), 1, "retries exhausted must still record the hypothesis, never discard it")
        self.assertEqual(_without_generated_at(finalized[0]["raw_hypothesis"]), BROKEN_KEY_NAME_HYPOTHESIS)
        self.assertIn("generated_at", finalized[0]["raw_hypothesis"])
        self.assertIn("UNTESTABLE_BY_DSL", tool_result_text["toolu_1"])
        self.assertEqual(correction_log[0]["outcome"], "retries_exhausted")

    def test_corrected_resubmission_under_the_same_name_finalizes_as_testable(self) -> None:
        retry_counts = {"name:SESSION0_STYLE_TYPO": 1}
        correction_log: list = []
        content = [{"type": "tool_use", "id": "toolu_2", "name": "propose_hypothesis", "input": {"hypothesis": CORRECTED_HYPOTHESIS}}]
        finalized, tool_result_text = session._process_proposed_hypotheses(
            content, "s1", 1, retry_counts, correction_log, datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(len(finalized), 1)
        self.assertEqual(tool_result_text["toolu_2"], session.PROPOSE_HYPOTHESIS_ACK_TEXT)
        self.assertEqual(correction_log, [], "a successful correction is not itself logged as a correction attempt")

    def test_malformed_hypothesis_input_is_skipped_not_fabricated(self) -> None:
        content = [{"type": "tool_use", "id": "toolu_bad", "name": "propose_hypothesis", "input": {"hypothesis": "not-an-object"}}]
        finalized, tool_result_text = session._process_proposed_hypotheses(
            content, "s1", 0, {}, [], datetime(2026, 8, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(finalized, [])
        self.assertEqual(tool_result_text, {})

    def test_unnamed_hypothesis_never_accumulates_retries_across_different_tool_use_ids(self) -> None:
        unnamed = {k: v for k, v in BROKEN_KEY_NAME_HYPOTHESIS.items() if k != "hypothesis_name"}
        retry_counts: dict = {}
        correction_log: list = []
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        content_1 = [{"type": "tool_use", "id": "toolu_a", "name": "propose_hypothesis", "input": {"hypothesis": unnamed}}]
        content_2 = [{"type": "tool_use", "id": "toolu_b", "name": "propose_hypothesis", "input": {"hypothesis": unnamed}}]
        session._process_proposed_hypotheses(content_1, "s1", 0, retry_counts, correction_log, now)
        session._process_proposed_hypotheses(content_2, "s1", 1, retry_counts, correction_log, now)
        # Each got its own key (unnamed:toolu_a / unnamed:toolu_b), so both
        # attempts show as attempt_number=1 -- a known, documented limitation
        # (see _hypothesis_retry_key's own docstring), not a crash or a
        # silent merge into the wrong hypothesis's retry budget.
        self.assertEqual([e["attempt_number"] for e in correction_log], [1, 1])


class RetryLoopEndToEndTest(_IsolatedStorageTestCase):
    """Drives session.run_session with a mocked call_turn to prove the full
    turn-by-turn retry loop actually reaches Eve and back correctly, not
    just the isolated validator function."""

    def test_full_retry_then_success_flow_produces_exactly_one_finalized_record(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        turn_0 = _propose_result("toolu_1", BROKEN_KEY_NAME_HYPOTHESIS)
        turn_1 = _propose_result("toolu_2", CORRECTED_HYPOTHESIS)
        turn_2 = _end_session_result()
        captured_messages: list = []

        import copy

        def _side_effect(messages, *args, **kwargs):
            captured_messages.append(copy.deepcopy(messages))
            results = [turn_0, turn_1, turn_2]
            return results[len(captured_messages) - 1]

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=_side_effect):
            result = session.run_session(api_key="fake-key", stub=False, now=now)

        self.assertEqual(result.n_proposed, 1, "one retry + one success is ONE hypothesis, not two")
        self.assertEqual(_without_generated_at(result.hypothesis_records[0]["raw_hypothesis"]), CORRECTED_HYPOTHESIS)

        # The message sent right after the broken first attempt must carry
        # the parser's own error back to Eve, not a generic ack.
        second_call_messages = captured_messages[1]
        tool_result = next(b for b in second_call_messages[-1]["content"] if b.get("type") == "tool_result")
        self.assertEqual(tool_result["tool_use_id"], "toolu_1")
        self.assertIn("compare_to_field", tool_result["content"])

        self.assertEqual(len(result.record["dsl_correction_log"]), 1)
        self.assertEqual(result.record["dsl_correction_log"][0]["outcome"], "retry_offered")
        self.assertEqual(result.record["ablation_metadata"]["n_hypotheses_recovered_by_dsl_correction"], 1)
        self.assertEqual(result.record["ablation_metadata"]["n_dsl_correction_attempts"], 1)
        self.assertEqual(result.record["ablation_metadata"]["n_hypotheses_dsl_retries_exhausted"], 0)

    def test_never_corrected_hypothesis_is_recorded_after_retries_exhausted(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        # MAX_DSL_RETRIES=2 -> 3 total attempts before it's finalized as-is.
        attempts = [_propose_result(f"toolu_{i}", BROKEN_KEY_NAME_HYPOTHESIS) for i in range(session.MAX_DSL_RETRIES + 1)]
        turns = attempts + [_end_session_result()]
        call_count = {"n": 0}

        def _side_effect(messages, *args, **kwargs):
            result = turns[call_count["n"]]
            call_count["n"] += 1
            return result

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=_side_effect):
            result = session.run_session(api_key="fake-key", stub=False, now=now)

        self.assertEqual(result.n_proposed, 1, "still exactly one hypothesis record, never discarded")
        self.assertEqual(_without_generated_at(result.hypothesis_records[0]["raw_hypothesis"]), BROKEN_KEY_NAME_HYPOTHESIS)
        outcomes = [e["outcome"] for e in result.record["dsl_correction_log"]]
        self.assertEqual(outcomes, ["retry_offered", "retry_offered", "retries_exhausted"])
        self.assertEqual(result.record["ablation_metadata"]["n_hypotheses_dsl_retries_exhausted"], 1)
        self.assertEqual(result.record["ablation_metadata"]["n_hypotheses_recovered_by_dsl_correction"], 0)

    def test_dsl_correction_does_not_break_stub_mode_behavior(self) -> None:
        # The stub script's own propose_hypothesis call is already
        # DSL-valid -- confirms the validator is a no-op for it, same as
        # every pre-existing stub-mode test already asserts.
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertEqual(result.n_proposed, 1)
        self.assertEqual(result.record["dsl_correction_log"], [])


if __name__ == "__main__":
    unittest.main()
