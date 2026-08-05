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

    def test_repair_propose_never_calls_append_repair_event(self) -> None:
        # Item 4's own explicit scope boundary: propose+validate only, this
        # panel must never launch/commit a chain. AST-based (not a substring
        # scan) so this survives the module's own docstring/comments naming
        # append_repair_event in PROSE to explain why it is deliberately
        # absent -- that prose must not itself trip this guard.
        import ast
        import inspect

        from tools.operator_panel import app as app_module

        tree = ast.parse(inspect.getsource(app_module))
        calls = [
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        self.assertNotIn("append_repair_event", calls)

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
