"""CC-1 directive, "Scope the Learning Curve page + fix Operator Panel
automation", Item 4d. Real git repositories (a bare "origin" + a working
clone), not mocked subprocess calls -- this module's whole job is getting
real git plumbing right (stash/rebase/push/verify), and a mock would just
assert its own assumptions back at itself."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.operator_panel.git_ops import GitOpsError, commit_and_push


def _run(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


class GitOpsRealRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        self.work = self.tmp / "work"
        _run(["init", "--bare", "-b", "main", str(self.origin)], self.tmp)
        _run(["clone", str(self.origin), str(self.work)], self.tmp)
        _run(["config", "user.email", "test@example.com"], self.work)
        _run(["config", "user.name", "Test"], self.work)
        (self.work / "seed.txt").write_text("seed\n", encoding="utf-8")
        _run(["add", "seed.txt"], self.work)
        _run(["commit", "-m", "seed"], self.work)
        _run(["push", "origin", "main"], self.work)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_commits_pushes_and_verifies(self) -> None:
        target = self.work / "result.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")
        result = commit_and_push([target], "Record result", self.work)

        self.assertTrue(result.changed)
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertTrue(result.verified)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.origin_log)
        self.assertTrue(result.ok)

        # Real, independent proof the push actually landed: a fresh clone
        # of the bare "origin" has the file, not just this working copy.
        fresh = self.tmp / "verify_clone"
        _run(["clone", str(self.origin), str(fresh)], self.tmp)
        self.assertTrue((fresh / "result.json").exists())

    def test_no_changes_is_an_honest_no_op(self) -> None:
        target = self.work / "unchanged.json"
        target.write_text("{}\n", encoding="utf-8")
        _run(["add", "unchanged.json"], self.work)
        _run(["commit", "-m", "pre-existing"], self.work)
        _run(["push", "origin", "main"], self.work)

        result = commit_and_push([target], "should be a no-op", self.work)
        self.assertFalse(result.changed)
        self.assertFalse(result.committed)
        self.assertFalse(result.pushed)
        self.assertTrue(result.ok)

    def test_raises_on_empty_paths(self) -> None:
        with self.assertRaises(GitOpsError):
            commit_and_push([], "message", self.work)

    def test_never_stages_unrelated_dirty_files(self) -> None:
        target = self.work / "result.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")
        unrelated = self.work / "unrelated_scratch.py"
        unrelated.write_text("# not part of this run\n", encoding="utf-8")

        result = commit_and_push([target], "Record result only", self.work)

        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertTrue(result.verified)
        # The unrelated file must never have been committed...
        show = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=self.work, capture_output=True, text=True)
        self.assertNotIn("unrelated_scratch.py", show.stdout)
        # ...and must be restored to the working tree afterward, untouched.
        self.assertTrue(unrelated.exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "# not part of this run\n")
        self.assertTrue(result.stash_restored)

    def test_integrates_a_non_conflicting_remote_change_before_pushing(self) -> None:
        # Simulate another commit having landed on origin/main in between
        # (e.g. one of this project's own periodic automated data commits)
        # via a second clone, BEFORE this helper's own commit+push runs.
        other = self.tmp / "other_clone"
        _run(["clone", str(self.origin), str(other)], self.tmp)
        _run(["config", "user.email", "bot@example.com"], other)
        _run(["config", "user.name", "Bot"], other)
        (other / "bot_written.json").write_text("{}\n", encoding="utf-8")
        _run(["add", "bot_written.json"], other)
        _run(["commit", "-m", "bot commit"], other)
        _run(["push", "origin", "main"], other)

        target = self.work / "result.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")
        result = commit_and_push([target], "Record result", self.work)

        self.assertTrue(result.pushed)
        self.assertTrue(result.verified)
        # Both the bot's change and ours must be present on origin/main.
        fresh = self.tmp / "verify_clone2"
        _run(["clone", str(self.origin), str(fresh)], self.tmp)
        self.assertTrue((fresh / "bot_written.json").exists())
        self.assertTrue((fresh / "result.json").exists())

    def test_reports_a_real_conflict_without_pushing_and_keeps_commit_local(self) -> None:
        # A second clone commits a CONFLICTING change to the exact same
        # file this helper is about to commit -- rebase must fail cleanly,
        # push must never be attempted, and the local commit must survive.
        other = self.tmp / "other_clone"
        _run(["clone", str(self.origin), str(other)], self.tmp)
        _run(["config", "user.email", "bot@example.com"], other)
        _run(["config", "user.name", "Bot"], other)
        (other / "result.json").write_text('{"conflicting": true}\n', encoding="utf-8")
        _run(["add", "result.json"], other)
        _run(["commit", "-m", "conflicting bot commit"], other)
        _run(["push", "origin", "main"], other)

        target = self.work / "result.json"
        target.write_text('{"a": 1}\n', encoding="utf-8")
        result = commit_and_push([target], "Record result", self.work)

        self.assertTrue(result.committed)
        self.assertFalse(result.pushed)
        self.assertFalse(result.verified)
        self.assertIsNotNone(result.error)
        self.assertIn("conflict", result.error.lower())
        # The commit must still exist locally -- nothing was thrown away.
        log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=self.work, capture_output=True, text=True)
        self.assertIn("Record result", log.stdout)


if __name__ == "__main__":
    unittest.main()
