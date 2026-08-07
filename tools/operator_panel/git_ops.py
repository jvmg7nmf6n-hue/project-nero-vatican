"""CC-1 directive, "Scope the Learning Curve page + fix Operator Panel
automation", Item 4d -- the owner has decided full commit+push automation
after an Operator-Panel-triggered Adam/Eve run is a REQUIREMENT, not a
proposal: confirmed here that neither `/api/adam/run` nor `/api/eve/run`
in app.py did any git operation at all before this fix (both simply
streamed a subprocess's stdout) -- every one of this project's real Eve
sessions to date has in fact required a manual, later, separate commit,
exactly the risk this directive's owner named. This module is the fix:
one small, explicit, path-scoped commit+push+verify helper, reused by both
run endpoints, never a blanket `git add -A`.

SAFETY, confirmed empirically before writing this (not assumed): `git pull
--rebase` refuses outright ("You have unstaged changes") the instant ANY
file in the working tree is dirty, even one with zero path overlap with
what this helper is committing -- reproduced live against this exact repo
while this directive's own unrelated Rung-2 files were sitting uncommitted.
This is why every call here stashes whatever is dirty OUTSIDE the explicit
path list before rebasing, and restores it afterward -- the same
stash-rebase-pop pattern this project's own CC-1 sessions have used by
hand throughout this repo's history. If restoring that stash ever
conflicts, this module refuses to auto-resolve it: the stash is left in
`git stash list` untouched and the failure is reported plainly, because
guessing how to merge someone else's unrelated in-progress work is a much
worse failure mode than a clearly-reported manual step.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitOpsError(Exception):
    """Raised only for a caller-error precondition (e.g. no paths given);
    every real git-command failure is reported through GitOpsResult
    instead, never an exception, so the panel can always show *why*."""


@dataclass
class GitOpsResult:
    changed: bool  # False means: nothing to commit, a legitimate no-op.
    committed: bool = False
    commit_sha: str | None = None
    pushed: bool = False
    verified: bool = False
    stash_restored: bool = True  # only meaningful if a stash was created.
    error: str | None = None
    log_lines: list[str] = field(default_factory=list)  # human-readable, streamed to the panel UI.
    origin_log: str | None = None  # `git log origin/main --oneline -3`, captured on success.

    @property
    def ok(self) -> bool:
        return self.changed is False or (self.committed and self.pushed and self.verified and self.stash_restored)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def commit_and_push(paths: list[Path], message: str, cwd: Path) -> GitOpsResult:
    """Stages exactly `paths` (never a blanket add), commits, integrates
    with origin/main, pushes, and VERIFIES the push landed by fetching and
    comparing origin/main's own sha against the commit just made -- never
    just trusting `git push`'s exit code, per this directive's own explicit
    "verify, don't assume" requirement. Any unrelated dirty file in the
    working tree is stashed first and restored after, regardless of
    outcome (short of an unresolvable stash-pop conflict, which is
    reported, never silently discarded)."""
    if not paths:
        raise GitOpsError("commit_and_push called with no paths -- nothing to stage")

    result = GitOpsResult(changed=False)
    rel_paths = [str(p) for p in paths]

    add = _run(["add", "--", *rel_paths], cwd)
    if add.returncode != 0:
        result.error = f"git add failed: {add.stderr.strip()}"
        return result

    diff = _run(["diff", "--cached", "--quiet"], cwd)
    if diff.returncode == 0:
        result.log_lines.append("No changes in the tracked result files -- nothing to commit.")
        return result  # changed=False: a legitimate, honest no-op.

    result.changed = True

    # Stash anything ELSE dirty so `pull --rebase` below doesn't refuse --
    # confirmed necessary against this repo's own real working state, see
    # module docstring. `--keep-index` so our just-staged files ride
    # through the stash untouched and stay staged for the commit below.
    stash_needed = _run(["status", "--porcelain"], cwd).stdout.strip() != ""
    if stash_needed:
        stash = _run(["stash", "push", "-u", "--keep-index", "-m", "operator-panel-autostash"], cwd)
        if stash.returncode != 0:
            result.changed = False
            result.error = f"could not stash unrelated dirty files before committing: {stash.stderr.strip()}"
            return result

    commit = _run(["commit", "-m", message], cwd)
    if commit.returncode != 0:
        result.error = f"git commit failed: {commit.stderr.strip()}"
        if stash_needed:
            _restore_stash(cwd, result)
        return result
    result.committed = True
    result.commit_sha = _run(["rev-parse", "HEAD"], cwd).stdout.strip()
    result.log_lines.append(f"Committed {result.commit_sha[:12]}: {message}")

    pull = _run(["pull", "--rebase", "origin", "main"], cwd)
    if pull.returncode != 0:
        _run(["rebase", "--abort"], cwd)
        result.error = (
            "could not integrate with origin/main (likely a real conflict) -- your commit is safe "
            f"locally at {result.commit_sha[:12]}, but push was NOT attempted; resolve manually. "
            f"git output: {pull.stderr.strip()}"
        )
        if stash_needed:
            _restore_stash(cwd, result)
        return result
    result.log_lines.append("Rebased onto latest origin/main.")

    push = _run(["push", "origin", "main"], cwd)
    if push.returncode != 0:
        result.error = f"git push failed: {push.stderr.strip()}"
        if stash_needed:
            _restore_stash(cwd, result)
        return result
    result.pushed = True

    _run(["fetch", "origin", "main"], cwd)
    origin_sha = _run(["rev-parse", "origin/main"], cwd).stdout.strip()
    local_sha = _run(["rev-parse", "HEAD"], cwd).stdout.strip()
    result.verified = origin_sha == local_sha and origin_sha != ""
    if not result.verified:
        result.error = (
            f"push reported success but verification failed: origin/main is {origin_sha[:12] or 'unknown'}, "
            f"local HEAD is {local_sha[:12]} -- do not assume the push landed."
        )
    else:
        result.origin_log = _run(["log", "origin/main", "--oneline", "-3"], cwd).stdout.strip()
        result.log_lines.append(f"Verified: origin/main now at {origin_sha[:12]}.")

    if stash_needed:
        _restore_stash(cwd, result)
    return result


def _restore_stash(cwd: Path, result: GitOpsResult) -> None:
    pop = _run(["stash", "pop"], cwd)
    if pop.returncode != 0:
        result.stash_restored = False
        stash_list = _run(["stash", "list"], cwd).stdout.strip()
        note = (
            "IMPORTANT: your other, unrelated uncommitted work was stashed before this operation and could NOT be "
            f"restored automatically (likely conflicts with the rebase above) -- it has NOT been lost, run "
            f"`git stash pop` by hand to resolve it. Current stash list: {stash_list or '(empty -- unexpected)'}"
        )
        result.error = f"{result.error} {note}" if result.error else note
    else:
        result.log_lines.append("Restored your other unrelated uncommitted work from stash.")
