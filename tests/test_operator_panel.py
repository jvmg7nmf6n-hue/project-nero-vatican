"""CC-1 directive, item 4: Local Operator Panel endpoint tests.

Every endpoint that writes anything is verified to write through the SAME
existing function a human/script already uses elsewhere in this codebase --
never a new write path. fastapi/httpx are deliberately NOT in the main
requirements.txt every CI workflow installs (see requirements-operator-
panel.txt's own docstring) -- this whole module skips cleanly, not a
failure, when they are not installed."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi/httpx not installed -- see requirements-operator-panel.txt")
class OperatorPanelEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        from tools.operator_panel import app as app_module

        self.app_module = app_module
        self.client = TestClient(app_module.app)
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_index_serves_the_static_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Operator Panel", response.text)

    def test_budget_endpoint_reads_real_ledger_shape(self) -> None:
        ledger_path = self.tmp / "ledger.json"
        ledger_path.write_text(json.dumps([
            {"status": "actual", "actual_cost_usd": 1.5, "session_id": "s1"},
            {"status": "reserved", "projected_cost_usd": 0.3, "session_id": "s2"},
        ]), encoding="utf-8")
        with patch.object(self.app_module, "EVE_BUDGET_LEDGER_PATH", ledger_path):
            response = self.client.get("/api/budget")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertAlmostEqual(data["eve_actual_spend_usd"], 1.5)
        self.assertEqual(data["eve_orphaned_reservations"]["count"], 1)
        self.assertAlmostEqual(data["eve_orphaned_reservations"]["total_usd"], 0.3)
        self.assertAlmostEqual(data["pre_registration_remaining_usd"], 14.0 - 1.8)
        # item 1a's own confirmed gap -- never fabricated.
        self.assertIsNone(data["adam_unknown_cost_calls"])

    def test_factory_loop_live_requires_explicit_confirm(self) -> None:
        response = self.client.post("/api/factory-loop/live", json={"confirm": False})
        self.assertEqual(response.status_code, 400)

    def test_eve_run_requires_explicit_confirm(self) -> None:
        response = self.client.post("/api/eve/run", json={"confirm": False})
        self.assertEqual(response.status_code, 400)

    # CC-1 directive, "fix Operator Panel automation" (Item 4d): the panel
    # now commits+pushes automatically after a run, but ONLY the specific,
    # machine-derived files each workflow's own established policy already
    # allows -- never a blanket add, never the raw-proposal-text/human-
    # judgment files that are deliberately excluded. These are regression
    # guards against scope creep silently widening what gets auto-committed.
    def test_adam_run_commit_paths_never_include_raw_hypotheses_json(self) -> None:
        names = {p.name for p in self.app_module.ADAM_RUN_COMMIT_PATHS}
        self.assertNotIn("agent_hypotheses.json", names)
        self.assertEqual(
            names,
            {"agent_test_results.json", "agent_run_summaries.json", "agent_performance.json"},
        )

    def test_eve_run_commit_paths_never_include_session_registry(self) -> None:
        names = {p.name for p in self.app_module.EVE_RUN_COMMIT_PATHS}
        # eve_session_registry.json is a human-curated classification file,
        # not one of nero_core.eve.storage's own allowlisted write paths --
        # must never be silently auto-committed by this fix.
        self.assertNotIn("eve_session_registry.json", names)
        self.assertEqual(names, {"eve_hypotheses.json", "eve_budget_ledger.json", "eve_sessions"})

    def test_commit_and_report_yields_a_success_banner_event(self) -> None:
        from tools.operator_panel.git_ops import GitOpsResult

        fake_result = GitOpsResult(
            changed=True, committed=True, commit_sha="abc123def456", pushed=True, verified=True,
            origin_log="abc123d Record Eve session results (Operator Panel)",
        )
        with patch.object(self.app_module, "commit_and_push", return_value=fake_result) as mock_commit:
            events = list(self.app_module._commit_and_report([self.tmp / "x.json"], "msg", "Eve"))
        mock_commit.assert_called_once()
        git_result_events = [e for e in events if "event: git_result" in e]
        self.assertEqual(len(git_result_events), 1)
        payload = json.loads(git_result_events[0].split("data: ", 1)[1])
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["commit_sha"], "abc123def456")

    def test_commit_and_report_yields_a_failure_banner_event_with_the_real_error(self) -> None:
        from tools.operator_panel.git_ops import GitOpsResult

        fake_result = GitOpsResult(changed=True, committed=True, pushed=False, verified=False, error="git push failed: rejected")
        with patch.object(self.app_module, "commit_and_push", return_value=fake_result):
            events = list(self.app_module._commit_and_report([self.tmp / "x.json"], "msg", "Adam"))
        git_result_events = [e for e in events if "event: git_result" in e]
        payload = json.loads(git_result_events[0].split("data: ", 1)[1])
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["pushed"])
        self.assertIn("rejected", payload["error"])

    def test_approve_draft_writes_through_commit_graveyard_entry_only(self) -> None:
        # Regression guard on item 4's own "no new write path" requirement:
        # approving must call the REAL graveyard_distillation.
        # commit_graveyard_entry, never write graveyard.json/failure_
        # patterns.json directly.
        drafts_path = self.tmp / "drafts.json"
        drafts_path.write_text(json.dumps([
            {"name": "DRAFT_A", "family": "Test Family", "failure_pattern": "sample-too-thin",
             "why_it_died": "...", "fixable": True, "source_doc": "...", "covers": ["DRAFT_A"],
             "origin_agent_breakdown": {"adam": 1}, "review_status": "pending_human_approval"},
        ]), encoding="utf-8")
        with patch.object(self.app_module, "DISTILLATION_DRAFTS_PATH", drafts_path), \
             patch.object(self.app_module.graveyard_distillation, "commit_graveyard_entry", return_value={"graveyard_entries_added": 1, "failure_patterns_merged": False}) as mock_commit:
            response = self.client.post("/api/approval-queue/DRAFT_A/approve")

        self.assertEqual(response.status_code, 200)
        mock_commit.assert_called_once()
        called_entry = mock_commit.call_args.args[0]
        self.assertEqual(called_entry["review_status"], "approved")
        # The persisted drafts file must also reflect the same status change
        # (the "same field a human would edit by hand").
        persisted = json.loads(drafts_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted[0]["review_status"], "approved")

    def test_reject_draft_never_calls_commit_graveyard_entry(self) -> None:
        drafts_path = self.tmp / "drafts.json"
        drafts_path.write_text(json.dumps([
            {"name": "DRAFT_B", "family": "Test Family", "review_status": "pending_human_approval"},
        ]), encoding="utf-8")
        with patch.object(self.app_module, "DISTILLATION_DRAFTS_PATH", drafts_path), \
             patch.object(self.app_module.graveyard_distillation, "commit_graveyard_entry") as mock_commit:
            response = self.client.post("/api/approval-queue/DRAFT_B/reject")

        self.assertEqual(response.status_code, 200)
        mock_commit.assert_not_called()
        persisted = json.loads(drafts_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted[0]["review_status"], "rejected")

    def test_approve_unknown_draft_is_404_not_a_silent_noop(self) -> None:
        drafts_path = self.tmp / "drafts.json"
        drafts_path.write_text("[]", encoding="utf-8")
        with patch.object(self.app_module, "DISTILLATION_DRAFTS_PATH", drafts_path):
            response = self.client.post("/api/approval-queue/NOT_A_REAL_NAME/approve")
        self.assertEqual(response.status_code, 404)

    def test_repair_propose_requires_a_known_candidate(self) -> None:
        with patch.object(self.app_module.repair_lab, "load_repair_candidates", return_value=[]):
            response = self.client.post("/api/repair/propose", json={"hypothesis_name": "NOT_REAL"})
        self.assertEqual(response.status_code, 404)

    def test_app_module_never_calls_append_repair_event_directly(self) -> None:
        # Regression guard on item 4/2d's "no new write path" requirement:
        # even now that this panel CAN launch (commit) a repair chain, the
        # actual append_repair_event write must happen only inside tools.
        # repair_chain_launch.commit_repair_launch -- this file itself must
        # never call append_repair_event directly. AST-based (not a
        # substring scan) so this survives the module's own docstring/
        # comments naming append_repair_event in PROSE to explain the
        # design -- that prose must not itself trip this guard.
        import ast
        import inspect

        from tools.operator_panel import app as app_module

        tree = ast.parse(inspect.getsource(app_module))
        calls = [
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("append_repair_event", calls)

    def test_repair_candidates_uses_get_candidate_status(self) -> None:
        # /api/repair/candidates must be a thin wrapper around
        # repair_chain_launch.get_candidate_status -- the SAME function the
        # CLI uses -- not a second, independently-maintained computation
        # that could silently drift from it (this was a real inconsistency
        # found and fixed in this directive: chain_id used to be computed
        # inline here as the raw hypothesis_name, while the launcher module
        # used the prefixed RC-{name} convention).
        fake_status = [{"hypothesis_name": "H1", "parent_strategy": "P1", "chain_id": "RC-H1",
                         "attempts_launched": 0, "can_launch_new_attempt": True, "cap_reason": "ok",
                         "original_data_available": False}]
        with patch.object(self.app_module.repair_chain_launch, "get_candidate_status", return_value=fake_status) as mock_status:
            response = self.client.get("/api/repair/candidates")
        self.assertEqual(response.status_code, 200)
        mock_status.assert_called_once()
        self.assertEqual(response.json(), {"candidates": fake_status})

    def test_repair_launch_requires_explicit_confirm(self) -> None:
        response = self.client.post("/api/repair/launch", json={
            "hypothesis_name": "H1", "proposal": {}, "confirm": False,
        })
        self.assertEqual(response.status_code, 400)

    def test_repair_launch_requires_a_known_candidate(self) -> None:
        with patch.object(self.app_module.repair_lab, "load_repair_candidates", return_value=[]):
            response = self.client.post("/api/repair/launch", json={
                "hypothesis_name": "NOT_REAL", "proposal": {}, "confirm": True,
            })
        self.assertEqual(response.status_code, 404)

    def test_repair_launch_requires_original_data(self) -> None:
        candidate = {"hypothesis_name": "H1", "parent_strategy": "MISSING_PARENT"}
        with patch.object(self.app_module.repair_lab, "load_repair_candidates", return_value=[candidate]), \
             patch.object(self.app_module, "DEFAULT_HYPOTHESES_PATH", self.tmp / "no_such_hyp.json"), \
             patch.object(self.app_module, "AGENT_TEST_RESULTS_PATH", self.tmp / "no_such_res.json"):
            response = self.client.post("/api/repair/launch", json={
                "hypothesis_name": "H1", "proposal": {"hypothesis_name": "X"}, "confirm": True,
            })
        self.assertEqual(response.status_code, 422)

    def test_repair_launch_writes_through_commit_repair_launch_only(self) -> None:
        # Regression guard: launching must call the REAL tools.
        # repair_chain_launch.commit_repair_launch -- never append_
        # repair_event directly, never a second write path.
        candidate = {"hypothesis_name": "H1", "parent_strategy": "PARENT1"}
        hyp_path = self.tmp / "hyps.json"
        res_path = self.tmp / "results.json"
        hyp_path.write_text(json.dumps([{"hypothesis_name": "PARENT1", "origin_agent": "adam"}]), encoding="utf-8")
        res_path.write_text(json.dumps([{"hypothesis_name": "PARENT1", "verdict": "DIED"}]), encoding="utf-8")
        fake_result = self.app_module.repair_chain_launch.LaunchResult(
            launched=True, reason="ok", chain_id="RC-H1", attempt_id="attempt-1",
        )
        with patch.object(self.app_module.repair_lab, "load_repair_candidates", return_value=[candidate]), \
             patch.object(self.app_module, "DEFAULT_HYPOTHESES_PATH", hyp_path), \
             patch.object(self.app_module, "AGENT_TEST_RESULTS_PATH", res_path), \
             patch.object(self.app_module.repair_chain_launch, "commit_repair_launch", return_value=fake_result) as mock_commit:
            response = self.client.post("/api/repair/launch", json={
                "hypothesis_name": "H1", "proposal": {"hypothesis_name": "PARENT1_V2"}, "confirm": True,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"launched": True, "chain_id": "RC-H1", "attempt_id": "attempt-1", "reason": "ok"})
        mock_commit.assert_called_once()

    def test_repair_launch_failure_from_launcher_is_409_not_silently_ok(self) -> None:
        candidate = {"hypothesis_name": "H1", "parent_strategy": "PARENT1"}
        hyp_path = self.tmp / "hyps.json"
        res_path = self.tmp / "results.json"
        hyp_path.write_text(json.dumps([{"hypothesis_name": "PARENT1", "origin_agent": "adam"}]), encoding="utf-8")
        res_path.write_text(json.dumps([{"hypothesis_name": "PARENT1", "verdict": "DIED"}]), encoding="utf-8")
        fake_result = self.app_module.repair_chain_launch.LaunchResult(
            launched=False, reason="cap reached", chain_id="RC-H1", attempt_id=None,
        )
        with patch.object(self.app_module.repair_lab, "load_repair_candidates", return_value=[candidate]), \
             patch.object(self.app_module, "DEFAULT_HYPOTHESES_PATH", hyp_path), \
             patch.object(self.app_module, "AGENT_TEST_RESULTS_PATH", res_path), \
             patch.object(self.app_module.repair_chain_launch, "commit_repair_launch", return_value=fake_result):
            response = self.client.post("/api/repair/launch", json={
                "hypothesis_name": "H1", "proposal": {"hypothesis_name": "PARENT1_V2"}, "confirm": True,
            })
        self.assertEqual(response.status_code, 409)

    def test_kill_unknown_run_id_is_404(self) -> None:
        response = self.client.post("/api/kill/not-a-real-run-id")
        self.assertEqual(response.status_code, 404)

    def test_factory_loop_dry_run_never_writes_forward_trial(self) -> None:
        with patch.object(self.app_module.factory_loop_run, "load_adam_candidates", return_value=[]), \
             patch.object(self.app_module.factory_loop_run, "load_eve_candidates", return_value=[]), \
             patch.object(self.app_module, "append_json_list") as mock_append:
            response = self.client.post("/api/factory-loop/dry-run")
        self.assertEqual(response.status_code, 200)
        mock_append.assert_not_called()


if __name__ == "__main__":
    unittest.main()
