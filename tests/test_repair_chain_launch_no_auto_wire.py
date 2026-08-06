"""CC-1 directive, item 2: tools/repair_chain_launch.py must never be
auto-invoked -- same discipline as repair_to_trial.py's own no-auto-wire
test (tests/test_repair_to_trial.py::RepairToTrialNoAutoWireTest), applied
to this new file. A human (the Operator Panel's own confirm-gated button,
or a human running the CLI) is the only allowed caller."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_research_agent_no_auto_wire import _forbidden_references

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPO_ROOT / "tools" / "repair_chain_launch.py"


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


class RepairChainLaunchNoAutoWireTest(unittest.TestCase):
    def test_launcher_file_has_zero_forbidden_references(self) -> None:
        self.assertTrue(LAUNCHER_PATH.exists())
        hits = _forbidden_references(LAUNCHER_PATH)
        self.assertEqual(hits, [], f"repair_chain_launch.py references live_scheduler/default_registry: {hits}")

    def test_no_workflow_or_scheduler_file_calls_commit_repair_launch(self) -> None:
        offenders = []
        execution_dir = REPO_ROOT / "nero_core" / "execution"
        for path in execution_dir.glob("*.py"):
            if "commit_repair_launch" in "\n".join(_non_comment_lines(path.read_text(encoding="utf-8", errors="ignore"))):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        for path in workflows_dir.glob("*.yml"):
            if "commit_repair_launch" in "\n".join(_non_comment_lines(path.read_text(encoding="utf-8", errors="ignore"))):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [], f"a workflow/execution file calls commit_repair_launch automatically: {offenders}")

    def test_factory_loop_run_never_calls_commit_repair_launch(self) -> None:
        # The Factory Loop runner (tools/factory_loop_run.py) admits, drafts,
        # and ticks -- it must never launch a repair chain on its own.
        path = REPO_ROOT / "tools" / "factory_loop_run.py"
        text = "\n".join(_non_comment_lines(path.read_text(encoding="utf-8")))
        self.assertNotIn("commit_repair_launch", text)


if __name__ == "__main__":
    unittest.main()
