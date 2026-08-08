"""CC-1 directive Part A, item A4: proves tools/repair_alert.py's real
eligibility scan -- fires only for a candidate whose parent_strategy
resolves to a genuine Adam or Eve DIED record with cap headroom, never
for a human-engineered candidate whose parent name matches nothing in
either agent's committed data (the real state of all 3 committed
docs/site_data/repair_candidates.json entries as of 2026-08-08)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import repair_alert

ADAM_HYPOTHESIS = {
    "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "asset": "ETH", "timeframe": "4h",
    "structured_entry_rule": {"conditions": [{"field": "close", "op": "lt", "compare_to_field": "bb_lower"}]},
    "structured_exit_plan": {"stop_pct_of_entry": 0.02, "target_pct_of_entry": 0.04},
}
ADAM_RESULT_DIED = {"hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "verdict": "DIED"}
ADAM_RESULT_SURVIVED = {"hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H", "verdict": "SURVIVED"}

EVE_RECORD_DIED = {
    "raw_hypothesis": {"hypothesis_name": "PAXG_RISKOFF_VIX_SPIKE_LONG_4H", "asset": "PAXG", "timeframe": "4h"},
    "verdict_combined": "DIED",
    "frequency_classification": "FAST",
}

REPAIR_CANDIDATE_ADAM_PARENT = {
    "parent_strategy": "EXT_WISE_MAN_HOLD_V5_ETH_4H",
    "failure_pattern": "sample-too-thin",
    "diagnosis": "d", "proposed_fix": "f",
    "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H_REPAIR", "status": "candidate",
}
REPAIR_CANDIDATE_EVE_PARENT = {
    "parent_strategy": "PAXG_RISKOFF_VIX_SPIKE_LONG_4H",
    "failure_pattern": "sample-too-thin",
    "diagnosis": "d", "proposed_fix": "f",
    "hypothesis_name": "PAXG_RISKOFF_REPAIR", "status": "candidate",
}
REPAIR_CANDIDATE_UNBACKFILLABLE = {
    "parent_strategy": "RANGE_MEAN_REVERSION",  # a family name, never a real hypothesis_name -- real, current repair_candidates.json state
    "failure_pattern": "sample-too-thin",
    "diagnosis": "d", "proposed_fix": "f",
    "hypothesis_name": "RMR_CONFIRMATION_METALS_WEEKLY", "status": "candidate",
}


class FindNewlyLaunchableCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.candidates_path = self.tmp / "repair_candidates.json"
        self.events_path = self.tmp / "repair_attempts.json"
        self.hypotheses_path = self.tmp / "agent_hypotheses.json"
        self.results_path = self.tmp / "agent_test_results.json"
        self.eve_hypotheses_path = self.tmp / "eve_hypotheses.json"
        self.events_path.write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path: Path, data) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def _find(self):
        return repair_alert.find_newly_launchable_candidates(
            candidates_path=self.candidates_path,
            events_path=self.events_path,
            hypotheses_path=self.hypotheses_path,
            results_path=self.results_path,
            eve_hypotheses_path=self.eve_hypotheses_path,
        )

    def test_fires_for_a_real_died_adam_parent_with_cap_headroom(self) -> None:
        self._write(self.candidates_path, [REPAIR_CANDIDATE_ADAM_PARENT])
        self._write(self.hypotheses_path, [ADAM_HYPOTHESIS])
        self._write(self.results_path, [ADAM_RESULT_DIED])
        self._write(self.eve_hypotheses_path, [])

        found = self._find()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["parent_strategy"], "EXT_WISE_MAN_HOLD_V5_ETH_4H")
        self.assertEqual(found[0]["parent_origin_agent"], "adam")
        self.assertEqual(found[0]["attempts_launched"], 0)

    def test_fires_for_a_real_died_eve_parent(self) -> None:
        self._write(self.candidates_path, [REPAIR_CANDIDATE_EVE_PARENT])
        self._write(self.hypotheses_path, [])
        self._write(self.results_path, [])
        self._write(self.eve_hypotheses_path, [EVE_RECORD_DIED])

        found = self._find()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["parent_origin_agent"], "eve")

    def test_never_fires_for_an_unbackfillable_human_engineered_candidate(self) -> None:
        # Mirrors real, current docs/site_data/repair_candidates.json: parent_strategy
        # is a graveyard family name, not any real hypothesis_name Adam or Eve ever
        # proposed -- confirmed zero matches in either agent's committed data.
        self._write(self.candidates_path, [REPAIR_CANDIDATE_UNBACKFILLABLE])
        self._write(self.hypotheses_path, [ADAM_HYPOTHESIS])  # unrelated real record present
        self._write(self.results_path, [ADAM_RESULT_DIED])
        self._write(self.eve_hypotheses_path, [EVE_RECORD_DIED])  # unrelated real record present

        found = self._find()

        self.assertEqual(found, [])

    def test_never_fires_for_a_non_died_parent(self) -> None:
        self._write(self.candidates_path, [REPAIR_CANDIDATE_ADAM_PARENT])
        self._write(self.hypotheses_path, [ADAM_HYPOTHESIS])
        self._write(self.results_path, [ADAM_RESULT_SURVIVED])
        self._write(self.eve_hypotheses_path, [])

        self.assertEqual(self._find(), [])

    def test_never_fires_once_the_four_attempt_cap_is_reached(self) -> None:
        self._write(self.candidates_path, [REPAIR_CANDIDATE_ADAM_PARENT])
        self._write(self.hypotheses_path, [ADAM_HYPOTHESIS])
        self._write(self.results_path, [ADAM_RESULT_DIED])
        self._write(self.eve_hypotheses_path, [])
        from nero_core.research_agent import repair_lab

        chain_id = "RC-EXT_WISE_MAN_HOLD_V5_ETH_4H_REPAIR"
        events = [{"event": repair_lab.EVENT_CHAIN_OPENED, "repair_chain_id": chain_id, "original_hypothesis_name": "x", "opened_at": "2026-08-08T00:00:00+00:00"}]
        for i in range(1, 5):
            events.append({
                "event": repair_lab.EVENT_ATTEMPT_LAUNCHED, "repair_chain_id": chain_id, "attempt_id": f"A{i}",
                "fresh_data_method": "forward_testing", "launched_at": "2026-08-08T00:00:00+00:00",
            })
        self._write(self.events_path, events)

        self.assertEqual(self._find(), [])

    def test_real_committed_repair_candidates_file_currently_finds_nothing(self) -> None:
        # The real production check, against the real committed file -- confirms
        # today's honest answer is zero, not a fabricated example.
        found = repair_alert.find_newly_launchable_candidates()
        self.assertEqual(found, [])


class FormatMessageTest(unittest.TestCase):
    def test_message_names_the_candidate_parent_and_origin_never_a_url_claim(self) -> None:
        title, body = repair_alert._format_message({
            "hypothesis_name": "EXT_WISE_MAN_HOLD_V5_ETH_4H_REPAIR",
            "parent_strategy": "EXT_WISE_MAN_HOLD_V5_ETH_4H",
            "parent_origin_agent": "adam",
        })
        self.assertIn("EXT_WISE_MAN_HOLD_V5_ETH_4H_REPAIR", title)
        self.assertIn("EXT_WISE_MAN_HOLD_V5_ETH_4H", body)
        self.assertIn("adam", body)
        # No public Operator Panel URL exists (LOCAL ONLY, never deployed) -- the
        # message must never claim a hosted link.
        self.assertNotIn("https://", body.replace("127.0.0.1", ""))


if __name__ == "__main__":
    unittest.main()
