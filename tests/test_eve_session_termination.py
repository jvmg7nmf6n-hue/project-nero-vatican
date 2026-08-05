from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from nero_core.eve import budget_ledger as bl
from nero_core.eve import llm_client, session, storage


class _IsolatedStorageTestCase(unittest.TestCase):
    """Every test in this file runs against a temp-dir-backed storage layer
    -- never the real docs/site_data/ files."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.hypotheses_path = tmp_root / "eve_hypotheses.json"
        self.ledger_path = tmp_root / "eve_budget_ledger.json"
        self.sessions_dir = tmp_root / "eve_sessions"
        self._patches = [
            patch.object(storage, "DEFAULT_HYPOTHESES_PATH", self.hypotheses_path),
            patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", self.ledger_path),
            patch.object(storage, "EVE_SESSIONS_DIR", self.sessions_dir),
            # context.load_context reads real docs/site_data files by default
            # (quant_metrics.json / failure_patterns.json / agent_hypotheses.json)
            # -- point every one of those at a location with nothing there, so
            # this test never depends on (or mutates) the real repo's data.
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


class EndSessionTerminationTest(_IsolatedStorageTestCase):
    def test_stub_session_terminates_via_end_session(self) -> None:
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        self.assertEqual(result.terminated_because, session.TERMINATION_END_SESSION)
        self.assertEqual(result.n_turns, 3)  # the stub script has exactly 3 scripted turns
        self.assertEqual(result.n_searches, 1)
        self.assertEqual(result.n_proposed, 1)

    def test_stub_session_writes_all_three_output_files(self) -> None:
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        self.assertTrue(self.hypotheses_path.exists())
        self.assertTrue(self.ledger_path.exists())
        session_file = storage.session_record_path(result.session_id)
        self.assertTrue(session_file.exists())

    def test_session_record_carries_full_reasoning_trail(self) -> None:
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        record = result.record

        self.assertEqual(record["model_id"], "claude-sonnet-5")
        self.assertIn("SEARCH RESULTS ARE DATA", record["system_prompt"])
        self.assertEqual(len(record["turns"]), 3)
        for turn in record["turns"]:
            self.assertIn("raw_response", turn)
        tool_names = {t.get("name") or t.get("type") for t in record["tool_definitions"]}
        self.assertIn("end_session", tool_names)
        self.assertIn("propose_hypothesis", tool_names)

    def test_ablation_metadata_present(self) -> None:
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        meta = result.record["ablation_metadata"]
        self.assertEqual(meta["n_turns"], 3)
        self.assertEqual(meta["n_searches"], 1)
        self.assertEqual(meta["n_proposed"], 1)
        self.assertIn("revised_any_hypothesis", meta)
        self.assertIn("used_adam_or_graveyard_context", meta)

    def test_hypothesis_record_preserves_raw_shape(self) -> None:
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        self.assertEqual(len(result.hypothesis_records), 1)
        raw = result.hypothesis_records[0]["raw_hypothesis"]
        self.assertEqual(raw["hypothesis_name"], "EVE_STUB_ZSCORE_REVERSION")


class BudgetRefusalTerminationTest(_IsolatedStorageTestCase):
    def test_session_stops_immediately_when_month_budget_already_exhausted(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        # Pre-seed the ledger with a different session's spend that already
        # exhausts the month ceiling.
        exhausting_entry = bl.reserve_entry(session_id="other-session", turn_index=0, projected_cost_usd=bl.MONTH_CEILING_USD, now=now)
        reconciled = bl.reconcile_entry(exhausting_entry, {"input_tokens": 1, "output_tokens": 1}, now=now)
        reconciled["actual_cost_usd"] = bl.MONTH_CEILING_USD
        bl.append_entry(reconciled, path=self.ledger_path)

        result = session.run_session(api_key="fake-key", stub=True, now=now)

        self.assertEqual(result.terminated_because, bl.REASON_MONTH_EXHAUSTED)
        self.assertEqual(result.n_turns, 0, "no real LLM call should have been made")
        self.assertEqual(result.n_proposed, 0)
        # a session record must still be written, even for a zero-turn session
        session_file = storage.session_record_path(result.session_id)
        self.assertTrue(session_file.exists())

    def test_session_stops_immediately_when_session_budget_already_exhausted(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        session_id = session.new_session_id(now)
        exhausting_entry = bl.reserve_entry(session_id=session_id, turn_index=0, projected_cost_usd=bl.DEFAULT_SESSION_BUDGET_USD, now=now)
        reconciled = bl.reconcile_entry(exhausting_entry, {"input_tokens": 1, "output_tokens": 1}, now=now)
        reconciled["actual_cost_usd"] = bl.DEFAULT_SESSION_BUDGET_USD
        bl.append_entry(reconciled, path=self.ledger_path)

        # Seed a ledger entry with a huge session-wide spend under a
        # pre-minted session_id, then pass that SAME session_id into
        # run_session explicitly (CC-1 Master Directive Phase 1.1d added
        # this parameter) so the pre-seeded entry actually matches -- no
        # monkeypatching needed now that run_session accepts session_id
        # directly.
        result = session.run_session(api_key="fake-key", stub=True, now=now, session_id=session_id)

        self.assertEqual(result.terminated_because, bl.REASON_SESSION_EXHAUSTED)
        self.assertEqual(result.n_turns, 0)


class RejectedBeforeTokenProcessingTerminationTest(_IsolatedStorageTestCase):
    """A 401/403/429 on the real API call (Adam hit this exact failure once
    already -- commit 4189f6b) must stop the session immediately (not retry
    the same doomed call on every remaining turn) and must RELEASE the
    turn's pre-call budget reservation rather than leaving it permanently
    counted as spend -- see budget_ledger's own RELEASE, THE THIRD OUTCOME
    section."""

    def test_session_stops_immediately_and_releases_the_reservation(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        rejection = session.llm_client.RejectedBeforeTokenProcessingError(401, "401 Client Error: Unauthorized")

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=rejection):
            result = session.run_session(api_key="stale-key", stub=False, now=now)

        self.assertEqual(result.terminated_because, session.TERMINATION_REJECTED_BEFORE_TOKEN_PROCESSING)
        self.assertEqual(result.n_turns, 0, "a rejected call is not a completed turn")
        self.assertEqual(result.n_proposed, 0)
        self.assertEqual(result.session_spent_usd, 0.0, "a 401 costs $0 -- must not be counted as spend")

        # The reservation this turn made must be released, not left
        # "reserved" (which would count it as spend at its projected value
        # forever) and not "actual" (there was no real usage to reconcile).
        ledger_entries = bl.load_ledger(path=self.ledger_path)
        self.assertEqual(len(ledger_entries), 1)
        self.assertEqual(ledger_entries[0]["status"], bl.STATUS_RELEASED)
        self.assertEqual(ledger_entries[0]["actual_cost_usd"], 0.0)

        # And critically: this released entry must not block a subsequent
        # real session's budget check.
        check = bl.pre_call_check(ledger_entries, session_id="a-later-session", projected_cost_usd=0.5, now=now)
        self.assertTrue(check.allowed)

    def test_a_session_record_is_still_written_for_a_rejected_session(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        rejection = session.llm_client.RejectedBeforeTokenProcessingError(429, "429 Client Error: Too Many Requests")

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=rejection):
            result = session.run_session(api_key="fake-key", stub=False, now=now)

        session_file = storage.session_record_path(result.session_id)
        self.assertTrue(session_file.exists())
        self.assertEqual(len(result.record["turns"]), 1)
        self.assertTrue(result.record["turns"][0]["rejected_before_token_processing"])
        self.assertEqual(result.record["turns"][0]["status_code"], 429)

    def test_only_one_reservation_is_made_not_one_per_remaining_turn(self) -> None:
        # Before this fix's own precedent (Adam's commit 4189f6b), a repeated
        # 401 would have kept retrying once per remaining turn. Confirms
        # exactly one ledger entry exists even though max_turns allows many.
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        rejection = session.llm_client.RejectedBeforeTokenProcessingError(401, "401 Client Error: Unauthorized")

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=rejection):
            session.run_session(api_key="stale-key", stub=False, max_turns=40, now=now)

        ledger_entries = bl.load_ledger(path=self.ledger_path)
        self.assertEqual(len(ledger_entries), 1)


class CrashSafetyTest(_IsolatedStorageTestCase):
    """CC-1 Master Directive, Phase 1.1: a mid-session ReadTimeout (or any
    other exception escaping llm_client.call_turn that is NOT
    RejectedBeforeTokenProcessingError) must not destroy the whole session.
    Three real sessions were lost this exact way before this fix:
    eve-20260803T074058Z-df7df0f9, eve-20260803T075102Z-2b98a5f0,
    eve-20260804T015806Z-243d095f."""

    def _successful_turn_result(self, tool_use_id: str, hypothesis_name: str) -> llm_client.LlmTurnResult:
        content_blocks = [
            {"type": "text", "text": "Proposing a hypothesis."},
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": "propose_hypothesis",
                "input": {
                    "hypothesis": {
                        "hypothesis_name": hypothesis_name,
                        "mechanism": "test fixture",
                        "asset": "BTC",
                        "timeframe": "1h",
                        "structured_entry_rule": {"conditions": [{"field": "zscore20", "op": "lt", "value": -2.0}]},
                        "structured_exit_plan": {"stop_atr_multiple": 1.5, "target_r_multiple": 2.0, "max_holding_hours": 24.0},
                    }
                },
            },
        ]
        return llm_client.LlmTurnResult(
            content_blocks=content_blocks,
            usage={"input_tokens": 500, "output_tokens": 100},
            stop_reason="tool_use",
            raw_response={"content": content_blocks, "usage": {"input_tokens": 500, "output_tokens": 100}},
        )

    def test_hypotheses_from_earlier_successful_turns_survive_a_later_crash(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        turn0 = self._successful_turn_result("toolu_1", "SURVIVES_THE_CRASH")
        timeout = requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=[turn0, timeout]):
            with self.assertRaises(requests.exceptions.ReadTimeout):
                session.run_session(api_key="fake-key", stub=False, now=now)

        # Phase 1.1a: turn 0's hypothesis was persisted immediately, not
        # lost when turn 1 crashed.
        persisted = json.loads(self.hypotheses_path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["raw_hypothesis"]["hypothesis_name"], "SURVIVES_THE_CRASH")

    def test_a_partial_session_record_is_written_on_crash(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        turn0 = self._successful_turn_result("toolu_1", "SURVIVES_THE_CRASH")
        timeout = requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")

        session_id = "eve-crash-test-session"

        def _call_turn_side_effect(*args, **kwargs):
            if kwargs.get("call_index") == 0:
                return turn0
            raise timeout

        with patch("nero_core.eve.session.new_session_id", return_value=session_id):
            with patch("nero_core.eve.session.llm_client.call_turn", side_effect=_call_turn_side_effect):
                with self.assertRaises(requests.exceptions.ReadTimeout):
                    session.run_session(api_key="fake-key", stub=False, now=now)

        session_file = storage.session_record_path(session_id)
        self.assertTrue(session_file.exists(), "a crashed session must leave a visible artifact, not vanish")

        partial = json.loads(session_file.read_text(encoding="utf-8"))
        self.assertEqual(partial["session_id"], session_id)
        self.assertEqual(partial["terminated_because"], session.TERMINATION_CRASHED)
        self.assertIn("ReadTimeout", partial["crash_reason"])
        self.assertEqual(partial["turn_reached"], 1)
        self.assertTrue(partial["partial"])
        self.assertEqual(len(partial["hypothesis_records"]), 1)
        self.assertEqual(partial["hypothesis_records"][0]["raw_hypothesis"]["hypothesis_name"], "SURVIVES_THE_CRASH")

    def test_the_crashed_turns_reservation_is_marked_not_released(self) -> None:
        # Phase 1.1c: a ReadTimeout's real cost is genuinely UNKNOWN -- the
        # reservation must stay "reserved" (still conservatively counted),
        # never flipped to "released" (a confirmed $0 claim this project
        # cannot actually make). It must, however, be ANNOTATED with why,
        # so it is no longer a silent, unexplained orphan.
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        timeout = requests.exceptions.ReadTimeout("Read timed out. (read timeout=180)")

        with patch("nero_core.eve.session.llm_client.call_turn", side_effect=timeout):
            with self.assertRaises(requests.exceptions.ReadTimeout):
                session.run_session(api_key="fake-key", stub=False, now=now)

        ledger_entries = bl.load_ledger(path=self.ledger_path)
        self.assertEqual(len(ledger_entries), 1)
        self.assertEqual(ledger_entries[0]["status"], bl.STATUS_RESERVED, "must NOT be released -- cost is unknown, not confirmed $0")
        self.assertIn("ReadTimeout", ledger_entries[0]["crash_reason"])
        self.assertIsNotNone(ledger_entries[0]["crash_marked_at"])

        # And critically, the OPPOSITE of the RejectedBeforeTokenProcessing
        # case: this must still count as real (projected) spend against a
        # later session's budget check, since the true cost is unknown, not
        # confirmed zero.
        check = bl.pre_call_check(ledger_entries, session_id="a-later-session", projected_cost_usd=bl.MONTH_CEILING_USD, now=now)
        self.assertFalse(check.allowed)

    def test_normal_completion_does_not_double_write_hypotheses(self) -> None:
        # Phase 1.1a: per-turn persistence must not ALSO be written again in
        # bulk at the end of a normal (uncrashed) completion.
        result = session.run_session(api_key="fake-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))
        persisted = json.loads(self.hypotheses_path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted), 1, "the stub script proposes exactly one hypothesis -- must appear exactly once, not twice")
        self.assertEqual(len(result.hypothesis_records), 1)


class ToolResultProtocolTest(_IsolatedStorageTestCase):
    """Real incident, 2026-08-03: this project's first-ever real (non-stub)
    multi-turn session crashed with a real HTTP 400 from Anthropic --
    "tool_use ids were found without tool_result blocks immediately after"
    -- because the loop unconditionally appended a plain continue-text
    message after ANY turn, never checking whether that turn's assistant
    message left a client-defined tool_use (propose_hypothesis) call
    without a reply. Stub mode never caught this: the stub script's own
    propose_hypothesis turn is immediately followed by its end_session
    turn (which breaks the loop before another message is ever sent), so
    the missing-tool_result path was never actually exercised until a real,
    unscripted multi-turn conversation hit it."""

    def _propose_only_result(self, tool_use_id: str) -> llm_client.LlmTurnResult:
        content = [
            {"type": "text", "text": "Proposing one hypothesis, more research to come."},
            {
                "type": "tool_use",
                "id": tool_use_id,
                "name": "propose_hypothesis",
                "input": {"hypothesis": {"hypothesis_name": "TEST_HYPOTHESIS", "asset": "BTC", "timeframe": "4h"}},
            },
        ]
        return llm_client.LlmTurnResult(
            content_blocks=content,
            usage={"input_tokens": 1000, "output_tokens": 100},
            stop_reason="tool_use",
            raw_response={"content": content},
        )

    def _end_session_result(self) -> llm_client.LlmTurnResult:
        content = [
            {"type": "tool_use", "id": "toolu_end_1", "name": "end_session", "input": {"summary": "done", "n_hypotheses_proposed": 1}},
        ]
        return llm_client.LlmTurnResult(
            content_blocks=content,
            usage={"input_tokens": 1100, "output_tokens": 50},
            stop_reason="tool_use",
            raw_response={"content": content},
        )

    def _mock_call_turn_capturing_messages(self, results: list, captured: list) -> "callable":
        # `messages` is one list object the real loop mutates and re-appends to
        # in place across the whole session -- inspecting it AFTER run_session
        # returns would only ever show its FINAL state, not what was actually
        # sent on each individual call. Snapshots a deep copy at the exact
        # moment of each call instead, so each entry in `captured` reflects
        # exactly what that specific call_turn invocation received.
        import copy

        call_index = {"n": 0}

        def _side_effect(messages, *args, **kwargs):
            captured.append(copy.deepcopy(messages))
            result = results[call_index["n"]]
            call_index["n"] += 1
            return result

        return _side_effect

    def test_a_tool_result_block_is_sent_for_a_pending_propose_hypothesis_call(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        propose_result = self._propose_only_result("toolu_propose_1")
        end_result = self._end_session_result()
        captured: list = []

        with patch(
            "nero_core.eve.session.llm_client.call_turn",
            side_effect=self._mock_call_turn_capturing_messages([propose_result, end_result], captured),
        ) as mock_call:
            result = session.run_session(api_key="fake-key", stub=False, now=now)

        self.assertEqual(result.terminated_because, session.TERMINATION_END_SESSION)
        self.assertEqual(mock_call.call_count, 2)

        # captured[1] is exactly what the SECOND call_turn invocation received
        # -- it must contain a tool_result for toolu_propose_1, never a bare
        # continue-text message with the tool_use left dangling.
        second_call_messages = captured[1]
        last_message = second_call_messages[-1]
        self.assertEqual(last_message["role"], "user")
        tool_result_blocks = [b for b in last_message["content"] if b.get("type") == "tool_result"]
        self.assertEqual(len(tool_result_blocks), 1)
        self.assertEqual(tool_result_blocks[0]["tool_use_id"], "toolu_propose_1")

    def test_no_tool_result_block_when_the_turn_proposed_nothing(self) -> None:
        # A turn with only plain text (no propose_hypothesis, no end_session)
        # must still work exactly as before -- no tool_result blocks to add.
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        text_only = llm_client.LlmTurnResult(
            content_blocks=[{"type": "text", "text": "Still researching."}],
            usage={"input_tokens": 900, "output_tokens": 40},
            stop_reason="end_turn",
            raw_response={"content": [{"type": "text", "text": "Still researching."}]},
        )
        end_result = self._end_session_result()
        captured: list = []

        with patch(
            "nero_core.eve.session.llm_client.call_turn",
            side_effect=self._mock_call_turn_capturing_messages([text_only, end_result], captured),
        ):
            session.run_session(api_key="fake-key", stub=False, now=now)

        last_message = captured[1][-1]
        tool_result_blocks = [b for b in last_message["content"] if b.get("type") == "tool_result"]
        self.assertEqual(tool_result_blocks, [])

    def test_multiple_propose_hypothesis_calls_in_one_turn_each_get_their_own_tool_result(self) -> None:
        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        content = [
            {"type": "tool_use", "id": "toolu_a", "name": "propose_hypothesis", "input": {"hypothesis": {"hypothesis_name": "A"}}},
            {"type": "tool_use", "id": "toolu_b", "name": "propose_hypothesis", "input": {"hypothesis": {"hypothesis_name": "B"}}},
        ]
        two_proposals = llm_client.LlmTurnResult(
            content_blocks=content, usage={"input_tokens": 1000, "output_tokens": 150}, stop_reason="tool_use", raw_response={"content": content}
        )
        end_result = self._end_session_result()
        captured: list = []

        with patch(
            "nero_core.eve.session.llm_client.call_turn",
            side_effect=self._mock_call_turn_capturing_messages([two_proposals, end_result], captured),
        ):
            session.run_session(api_key="fake-key", stub=False, now=now)

        tool_result_ids = {b["tool_use_id"] for b in captured[1][-1]["content"] if b.get("type") == "tool_result"}
        self.assertEqual(tool_result_ids, {"toolu_a", "toolu_b"})


class MaxTurnsCapTest(_IsolatedStorageTestCase):
    def test_session_stops_at_max_turns_before_end_session_is_reached(self) -> None:
        # The stub script naturally ends (via end_session) on call_index 2;
        # capping max_turns at 2 means the loop must stop at the safety cap
        # instead, having taken exactly 2 turns.
        result = session.run_session(api_key="fake-key", stub=True, max_turns=2, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        self.assertEqual(result.terminated_because, session.TERMINATION_MAX_TURNS)
        self.assertEqual(result.n_turns, 2)


if __name__ == "__main__":
    unittest.main()
