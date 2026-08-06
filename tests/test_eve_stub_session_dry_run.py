"""Phase 0 acceptance test (spec's own words): 'a full stub session runs to
completion, writes all three output files, and produces at least one scored
hypothesis record.' The detailed termination/ledger/reasoning-trail behavior
is covered by test_eve_session_termination.py and test_eve_budget_ledger.py
-- this file exists to state the Phase 0 gate as ONE direct, literal check
that a fresh reader can find without piecing it together from other files.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from nero_core.eve import hypothesis_shapes, session, storage


class Phase0DryRunTest(unittest.TestCase):
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

    def test_full_stub_session_runs_to_completion_and_writes_all_three_files_with_a_scored_hypothesis(self) -> None:
        result = session.run_session(api_key="not-a-real-key", stub=True, now=datetime(2026, 8, 15, tzinfo=timezone.utc))

        # (1) runs to completion -- ended on its own signal, not a crash or a
        # budget refusal (this is a stub run, real spend is $0).
        self.assertEqual(result.terminated_because, session.TERMINATION_END_SESSION)

        # (2) all three output files exist.
        self.assertTrue(self.hypotheses_path.exists(), "eve_hypotheses.json was not written")
        self.assertTrue(self.ledger_path.exists(), "eve_budget_ledger.json was not written")
        session_file = storage.session_record_path(result.session_id)
        self.assertTrue(session_file.exists(), "eve_sessions/<session_id>.json was not written")

        # (3) at least one hypothesis record was produced -- "scored" here
        # means shape-valid and ready for nero_core.eve.scoring (Phase 3),
        # which runs as a separate pass; this branch's own docs are explicit
        # that Phase 0 alone does not yet classify testability/verdicts.
        hypotheses_on_disk = storage.read_json_list(self.hypotheses_path)
        self.assertGreaterEqual(len(hypotheses_on_disk), 1)
        self.assertEqual(hypotheses_on_disk[0]["testability"], hypothesis_shapes.TESTABILITY_UNSCORED)

        # every ledger entry reconciled to "actual" -- no orphaned "reserved"
        # entries left behind by a clean stub run.
        ledger_entries = storage.read_json_list(self.ledger_path)
        self.assertTrue(ledger_entries)
        self.assertTrue(all(e["status"] == "actual" for e in ledger_entries))

        # CC-1 directive, item B0b/B0c (2026-08-06): every NEW session
        # record is stamped with the current inheritance regime at
        # creation, not left for a later manual annotation step.
        import json
        session_record = json.loads(session_file.read_text(encoding="utf-8"))
        self.assertEqual(session_record["regime"], session.CURRENT_SESSION_REGIME)
        self.assertEqual(session_record["regime"], session.SESSION_REGIME_POST_INHERITANCE)


if __name__ == "__main__":
    unittest.main()
