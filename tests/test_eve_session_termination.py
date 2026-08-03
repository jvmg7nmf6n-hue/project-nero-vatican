from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.eve import budget_ledger as bl
from nero_core.eve import session, storage


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
        session_id = session._new_session_id(now)
        exhausting_entry = bl.reserve_entry(session_id=session_id, turn_index=0, projected_cost_usd=bl.DEFAULT_SESSION_BUDGET_USD, now=now)
        reconciled = bl.reconcile_entry(exhausting_entry, {"input_tokens": 1, "output_tokens": 1}, now=now)
        reconciled["actual_cost_usd"] = bl.DEFAULT_SESSION_BUDGET_USD
        bl.append_entry(reconciled, path=self.ledger_path)

        # run_session mints its OWN session_id internally, so we can't force
        # a collision directly -- instead, seed a ledger entry with a huge
        # month-wide spend under a DIFFERENT unrelated session id AND leave
        # the session's own budget comfortably free; this test instead
        # verifies the session-budget branch via a monkeypatched session id
        # generator so the pre-seeded entry actually matches.
        with patch("nero_core.eve.session._new_session_id", return_value=session_id):
            result = session.run_session(api_key="fake-key", stub=True, now=now)

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
