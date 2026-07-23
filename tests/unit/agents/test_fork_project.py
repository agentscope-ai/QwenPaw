# -*- coding: utf-8 -*-
"""Unit tests for fork worktree path + integration helpers."""

from __future__ import annotations

import errno
import importlib.util
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.agents.fork_project import (
    REGISTRY_REL,
    begin_fork_scope,
    bind_fork_task,
    bind_workspace_integration_project,
    finalize_fork_for_task,
    finalize_fork_worktree,
    finalize_fork_worktree_or_fail,
    forks_merged_into_head,
    mark_fork_failed,
    register_fork,
    resolve_allowed_fork_project_dir,
    resolve_git_project_dir,
    resolve_integration_project_dir,
    update_fork_head,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FORK_GUARD = (
    _REPO_ROOT
    / "plugins"
    / "bundle"
    / "omp_workflows"
    / "shared"
    / "fork_guard.py"
)


def _load_fork_guard():
    spec = importlib.util.spec_from_file_location(
        "omp_fork_guard",
        _FORK_GUARD,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README").write_text("base\n", encoding="utf-8")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")


def test_forks_integrated_rejects_truthy_strings() -> None:
    forks_integrated = _load_fork_guard().forks_integrated
    assert forks_integrated({"forks_integrated": "false"}) is False
    assert forks_integrated({"forks_integrated": "true"}) is False
    # No workspace_dir → fail closed (cannot evaluate).
    assert forks_integrated({"forks_integrated": True}) is False


def test_gate_allows_no_project_when_flag_true(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-git workspace with no pointer: no-fork protocol must pass."""
    workspace = tmp_path / "agent_ws"
    workspace.mkdir()
    # Unrelated active agent with a coding project must not leak in.
    other = tmp_path / "other_proj"
    _init_repo(other)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "other-agent",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(other),
            ),
            workspace_dir=str(tmp_path / "other_ws"),
        ),
    )
    forks_integrated = _load_fork_guard().forks_integrated
    assert resolve_git_project_dir(workspace) is None
    assert resolve_integration_project_dir(workspace) is None
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_register_fork_requires_workspace_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "code_proj"
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    # No context and no agent-config fallback → refuse.
    monkeypatch.setattr(
        "qwenpaw.agents.fork_project._fallback_agent_workspace_dir",
        lambda **_kwargs: None,
    )
    assert register_fork(str(wt), branch, workspace_dir=None) is False
    # Refused → nothing in registry.
    assert forks_merged_into_head(project) is True


def test_register_fork_falls_back_to_agent_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    monkeypatch.setattr(
        "qwenpaw.agents.fork_project._fallback_agent_workspace_dir",
        lambda **_kwargs: workspace.resolve(),
    )
    assert register_fork(str(wt), branch, workspace_dir=None) is True
    assert resolve_integration_project_dir(workspace) == project.resolve()


def test_bind_fork_task_does_not_create_ghost_entry(tmp_path: Path) -> None:
    """Without register_fork, bind_fork_task must not invent registry rows."""
    project = tmp_path / "code_proj"
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert bind_fork_task(str(wt), branch, "task-ghost") is False
    assert forks_merged_into_head(project) is True


def test_register_fork_writes_pointer_on_agent_workspace(
    tmp_path: Path,
) -> None:
    """Dual-root: register must bind agent workspace → coding project."""
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    # Workspace itself is also a git root (empty registry) — without a
    # pointer, gates would wrongly inspect the workspace.
    _init_repo(workspace)

    scope = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=workspace,
        scope_id=scope,
    )
    assert resolve_integration_project_dir(workspace) == project.resolve()
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(
        str(wt),
        branch,
        message="feat",
        expected_scope=scope,
    )

    forks_integrated = _load_fork_guard().forks_integrated
    # Unmerged fork on coding project must block (not workspace empty).
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )
    assert forks_merged_into_head(project, scope_id=scope) is False


def test_resolve_allowed_fork_project_dir(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    wt = project / ".qwenpaw" / "worktrees" / "abc"
    wt.mkdir(parents=True)
    outside = tmp_path / "other"
    outside.mkdir()

    assert (
        resolve_allowed_fork_project_dir(
            str(wt),
            workspace_dir=project,
        )
        == wt.resolve()
    )
    assert (
        resolve_allowed_fork_project_dir(
            str(outside),
            workspace_dir=project,
        )
        is None
    )


def test_failed_fork_blocks_current_scope_not_next(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    project = tmp_path / "proj"
    workspace.mkdir()
    _init_repo(project)
    bind_workspace_integration_project(workspace, project)

    scope1 = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=workspace,
        scope_id=scope1,
    )
    mark_fork_failed(
        str(wt),
        branch,
        reason="cancelled",
        expected_scope=scope1,
    )

    forks_integrated = _load_fork_guard().forks_integrated
    # Failed forks must not yield an empty-active pass in the same scope.
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )

    # New workflow scope — prior failed entries are pruned.
    scope2 = begin_fork_scope(workspace)
    assert scope2 != scope1
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_finalize_does_not_resurrect_pruned_fork(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    # Active agent pointing elsewhere must not steal begin_fork_scope prune.
    other = tmp_path / "other_proj"
    _init_repo(other)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "other-agent",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(other),
            ),
            workspace_dir=str(tmp_path / "other_ws"),
        ),
    )
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    (wt / "feat.txt").write_text("x\n", encoding="utf-8")

    # New scope supersedes + prunes the old pending entry.
    begin_fork_scope(project)
    assert (
        finalize_fork_worktree(
            str(wt),
            branch,
            message="late",
            expected_scope=scope1,
        )
        is False
    )
    # No ghost finalized entry without scope should appear.
    assert forks_merged_into_head(project) is True


def test_matching_agent_dual_root_bind(tmp_path: Path, monkeypatch) -> None:
    """Active agent may bind coding project only when workspace matches."""
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "agent-a",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(project),
            ),
            workspace_dir=str(workspace),
        ),
    )
    scope = begin_fork_scope(workspace)
    assert scope
    assert resolve_integration_project_dir(workspace) == project.resolve()


def test_mark_fork_failed_waits_for_finalize_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Watchdog blocks on the finalize lock and cannot overwrite success."""
    from qwenpaw.agents import fork_project as fp

    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    registry = project / REGISTRY_REL

    hold = threading.Event()
    release = threading.Event()
    failed_done = threading.Event()
    real_commit = fp.commit_dirty_worktree

    def _slow_commit(worktree_path: str, message: str = "x") -> bool:
        hold.set()
        assert release.wait(timeout=10)
        return real_commit(worktree_path, message)

    monkeypatch.setattr(fp, "commit_dirty_worktree", _slow_commit)

    results: list[bool] = []

    def _run_finalize() -> None:
        results.append(
            finalize_fork_worktree(
                str(wt),
                branch,
                message="feat",
                expected_scope=scope,
            ),
        )

    def _watchdog() -> None:
        assert hold.wait(timeout=5)
        mark_fork_failed(
            str(wt),
            branch,
            reason="watchdog timeout",
            expected_scope=scope,
        )
        failed_done.set()

    t_fin = threading.Thread(target=_run_finalize)
    t_watch = threading.Thread(target=_watchdog)
    t_fin.start()
    t_watch.start()
    assert hold.wait(timeout=5)
    # Watchdog must stay blocked while git finalize still holds the lock.
    time.sleep(0.2)
    assert not failed_done.is_set()
    release.set()
    t_fin.join(timeout=10)
    assert failed_done.wait(timeout=5)
    t_watch.join(timeout=5)
    assert results == [True]
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"


def test_recover_crashed_finalizing_clean_worktree(tmp_path: Path) -> None:
    """Crash leftover + clean worktree is healed to finalized."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert (
        finalize_fork_worktree(str(wt), branch, expected_scope=scope) is True
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"
    assert after["forks"][branch]["no_changes"] is True


def test_recover_crashed_finalizing_dirty_worktree(tmp_path: Path) -> None:
    """Crash leftover + dirty worktree re-runs commit and finalizes."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")

    assert (
        finalize_fork_worktree(
            str(wt),
            branch,
            message="feat",
            expected_scope=scope,
        )
        is True
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"
    assert after["forks"][branch]["no_changes"] is False


def test_mark_fork_failed_heals_clean_finalizing_with_commit(
    tmp_path: Path,
) -> None:
    """Failure path still heals when HEAD moved (commit evidence exists)."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert (
        finalize_fork_worktree(
            str(wt),
            branch,
            message="feat",
            expected_scope=scope,
        )
        is True
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    # Simulate crash after commit succeeded but before registry write.
    data["forks"][branch]["status"] = "finalizing"
    data["forks"][branch]["finalized"] = False
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    mark_fork_failed(
        str(wt),
        branch,
        reason="watchdog timeout",
        expected_scope=scope,
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"
    assert after["forks"][branch]["finalized"] is True
    assert after["forks"][branch]["no_changes"] is False


def test_mark_fork_failed_rejects_clean_no_commit_finalizing(
    tmp_path: Path,
) -> None:
    """Clean HEAD==base finalizing must not become finalized/no_changes."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    # Crash right after writing finalizing, before any git work.
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    mark_fork_failed(
        str(wt),
        branch,
        reason="worker crashed",
        expected_scope=scope,
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "failed"
    assert after["forks"][branch].get("finalized") is not True
    assert after["forks"][branch].get("fail_reason") == "worker crashed"


def test_update_fork_head_requires_matching_scope(tmp_path: Path) -> None:
    """Stale head updates must not rewrite a newer scope's registry row."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    registry = project / REGISTRY_REL
    before = json.loads(registry.read_text(encoding="utf-8"))
    old_head = before["forks"][branch]["head"]

    # Without expected_scope, scoped rows are not rewritten.
    assert update_fork_head(str(wt), branch) == old_head
    mid = json.loads(registry.read_text(encoding="utf-8"))
    assert mid["forks"][branch]["head"] == old_head

    # Matching scope may refresh head (still base here — no new commit).
    assert update_fork_head(str(wt), branch, expected_scope=scope1) == old_head

    # New scope reuses the branch; stale scope1 must not rewrite it.
    scope2 = begin_fork_scope(project)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope2,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    _git(wt, "add", "feat.txt")
    _git(wt, "commit", "-m", "feat")
    new_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(wt),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert update_fork_head(str(wt), branch, expected_scope=scope1) == new_head
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["scope_id"] == scope2
    # Stale update must leave the new scope row untouched.
    assert after["forks"][branch]["head"] != new_head

    assert update_fork_head(str(wt), branch, expected_scope=scope2) == new_head
    after2 = json.loads(registry.read_text(encoding="utf-8"))
    assert after2["forks"][branch]["head"] == new_head


def test_bind_fork_task_requires_matching_scope(tmp_path: Path) -> None:
    """Stale bind must not attach a task_id to a newer scope's fork row."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    # Scoped row without expected_scope is fail-closed.
    assert bind_fork_task(str(wt), branch, "task-old") is False

    scope2 = begin_fork_scope(project)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope2,
    )
    # Stale scope must not bind onto the new row.
    assert (
        bind_fork_task(
            str(wt),
            branch,
            "task-old",
            expected_scope=scope1,
        )
        is False
    )
    assert (
        bind_fork_task(
            str(wt),
            branch,
            "task-new",
            expected_scope=scope2,
        )
        is True
    )
    registry = project / REGISTRY_REL
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["task_id"] == "task-new"
    assert after["forks"][branch]["scope_id"] == scope2
    assert after["by_task"]["task-new"]["scope_id"] == scope2
    assert "task-old" not in after.get("by_task", {})


def test_finalize_fork_for_task_ignores_stale_scope(tmp_path: Path) -> None:
    """Stale by_task must not finalize a newer scope reusing the branch."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    assert bind_fork_task(
        str(wt),
        branch,
        "task-old",
        expected_scope=scope1,
    )

    scope2 = begin_fork_scope(project)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope2,
    )
    registry = project / REGISTRY_REL
    # register_fork clears by_task for the reused branch.
    cleared = json.loads(registry.read_text(encoding="utf-8"))
    assert "task-old" not in cleared.get("by_task", {})
    assert finalize_fork_for_task("task-old", project_dir=project) is False

    # Even a manually resurrected stale binding must not finalize scope2.
    cleared["by_task"] = {
        "task-old": {
            "branch": branch,
            "worktree": str(wt.resolve()),
            "project_dir": str(project.resolve()),
            "scope_id": scope1,
        },
    }
    registry.write_text(
        json.dumps(cleared, indent=2) + "\n",
        encoding="utf-8",
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_for_task("task-old", project_dir=project) is False
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["scope_id"] == scope2
    assert after["forks"][branch]["status"] == "pending"

    assert bind_fork_task(
        str(wt),
        branch,
        "task-new",
        expected_scope=scope2,
    )
    assert finalize_fork_for_task("task-new", project_dir=project) is True
    after2 = json.loads(registry.read_text(encoding="utf-8"))
    assert after2["forks"][branch]["status"] == "finalized"
    assert after2["forks"][branch]["scope_id"] == scope2


def test_mark_fork_failed_pending_ignores_new_scope(tmp_path: Path) -> None:
    """Stale pending-fail must not poison a newer scope reusing the branch."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    # Without expected_scope, scoped pending rows are not failed.
    mark_fork_failed(str(wt), branch, reason="stale no scope")
    registry = project / REGISTRY_REL
    mid = json.loads(registry.read_text(encoding="utf-8"))
    assert mid["forks"][branch]["status"] == "pending"

    scope2 = begin_fork_scope(project)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope2,
    )
    mark_fork_failed(
        str(wt),
        branch,
        reason="old worker failed",
        expected_scope=scope1,
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    row = after["forks"][branch]
    assert row["scope_id"] == scope2
    assert row["status"] == "pending"
    assert row.get("fail_reason") != "old worker failed"

    # Matching scope still marks failed.
    mark_fork_failed(
        str(wt),
        branch,
        reason="current failed",
        expected_scope=scope2,
    )
    after2 = json.loads(registry.read_text(encoding="utf-8"))
    assert after2["forks"][branch]["status"] == "failed"
    assert after2["forks"][branch]["fail_reason"] == "current failed"


def test_finalize_requires_matching_scope(tmp_path: Path) -> None:
    """Scoped finalize must not claim without scope or across scopes."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    registry = project / REGISTRY_REL

    # Omit expected_scope → fail closed; row stays pending.
    assert finalize_fork_worktree(str(wt), branch, message="x") is False
    assert (
        finalize_fork_worktree_or_fail(str(wt), branch, message="x") is False
    )
    mid = json.loads(registry.read_text(encoding="utf-8"))
    assert mid["forks"][branch]["status"] == "pending"
    assert mid["forks"][branch].get("fail_reason") is None

    scope2 = begin_fork_scope(project)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope2,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    # Stale scope1 must not finalize the newer row.
    assert (
        finalize_fork_worktree_or_fail(
            str(wt),
            branch,
            message="stale",
            expected_scope=scope1,
        )
        is False
    )
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["scope_id"] == scope2
    assert after["forks"][branch]["status"] == "pending"

    assert (
        finalize_fork_worktree_or_fail(
            str(wt),
            branch,
            message="current",
            expected_scope=scope2,
        )
        is True
    )
    after2 = json.loads(registry.read_text(encoding="utf-8"))
    assert after2["forks"][branch]["status"] == "finalized"
    assert after2["forks"][branch]["scope_id"] == scope2


def test_mark_fork_failed_dirty_recovery_ignores_new_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Stale dirty-fail must not poison a newer scope reusing the branch."""
    # pylint: disable=protected-access
    from qwenpaw.agents import fork_project as fp

    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (wt / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    real_apply = fp._apply_crash_recovery
    new_scope = {"id": ""}

    def _apply_then_register_new_scope(*args, **kwargs):
        result = real_apply(*args, **kwargs)
        assert result is None
        # Interleave a new workflow that reuses the same branch name.
        new_scope["id"] = begin_fork_scope(project)
        assert register_fork(
            str(wt),
            branch,
            workspace_dir=project,
            scope_id=new_scope["id"],
        )
        return result

    monkeypatch.setattr(
        fp,
        "_apply_crash_recovery",
        _apply_then_register_new_scope,
    )
    mark_fork_failed(
        str(wt),
        branch,
        reason="old worker failed",
        expected_scope=scope1,
    )

    after = json.loads(registry.read_text(encoding="utf-8"))
    row = after["forks"][branch]
    assert row["scope_id"] == new_scope["id"]
    assert row["status"] != "failed"
    assert row.get("fail_reason") != "old worker failed"


def test_forks_merged_rechecks_registry_after_git(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A fork registered during merge checks must keep the gate closed."""
    # pylint: disable=protected-access
    from qwenpaw.agents import fork_project as fp

    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt1 = project / ".qwenpaw" / "worktrees" / "w1"
    branch1 = "fork/w1"
    _git(project, "worktree", "add", str(wt1), "-b", branch1)
    register_fork(
        str(wt1),
        branch1,
        workspace_dir=project,
        scope_id=scope,
    )
    assert (
        finalize_fork_worktree(str(wt1), branch1, expected_scope=scope) is True
    )
    _git(project, "merge", "--no-ff", branch1, "-m", "integrate w1")

    wt2 = project / ".qwenpaw" / "worktrees" / "w2"
    branch2 = "fork/w2"
    inserted = {"done": False}
    real_is_ancestor = fp._is_ancestor

    def _insert_fork_during_check(project_dir: Path, tip: str) -> bool:
        if not inserted["done"]:
            inserted["done"] = True
            _git(project, "worktree", "add", str(wt2), "-b", branch2)
            assert register_fork(
                str(wt2),
                branch2,
                workspace_dir=project,
                scope_id=scope,
            )
        return real_is_ancestor(project_dir, tip)

    monkeypatch.setattr(fp, "_is_ancestor", _insert_fork_during_check)
    assert (
        forks_merged_into_head(project, scope_id=scope) is False
    ), "new pending fork during check must fail-closed"


def test_recovery_git_runs_outside_registry_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Crash-recovery Git must not hold the project registry lock."""
    # pylint: disable=protected-access
    from qwenpaw.agents import fork_project as fp

    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    holding = {"registry": False}
    real_registry = fp._registry_lock
    real_inspect = fp._inspect_worktree_recovery

    @contextmanager
    def _tracking_registry(project_dir: Path):
        holding["registry"] = True
        with real_registry(project_dir):
            yield
        holding["registry"] = False

    def _inspect_outside_registry(worktree: Path):
        assert holding["registry"] is False
        return real_inspect(worktree)

    monkeypatch.setattr(fp, "_registry_lock", _tracking_registry)
    monkeypatch.setattr(
        fp,
        "_inspect_worktree_recovery",
        _inspect_outside_registry,
    )
    assert (
        finalize_fork_worktree(str(wt), branch, expected_scope=scope) is True
    )


def test_finalize_lock_released_after_subprocess_crash(
    tmp_path: Path,
) -> None:
    """OS must release the finalize lock when the holding process dies."""
    # pylint: disable=protected-access
    from qwenpaw.agents.fork_project import (
        _exclusive_file_lock,
        _fork_finalize_lock_path,
    )

    project = tmp_path / "repo"
    project.mkdir()
    branch = "fork/crash"
    lock_path = _fork_finalize_lock_path(project.resolve(), branch)
    ready = tmp_path / "ready"
    child = (
        "import time\n"
        "from pathlib import Path\n"
        "from qwenpaw.agents.fork_project import _exclusive_file_lock\n"
        f"lock_path = Path({str(lock_path)!r})\n"
        f"ready = Path({str(ready)!r})\n"
        "with _exclusive_file_lock(lock_path, blocking=True) as ok:\n"
        "    assert ok\n"
        "    ready.write_text('1', encoding='utf-8')\n"
        "    time.sleep(120)\n"
    )
    with subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", child],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        try:
            deadline = time.time() + 10
            while not ready.is_file() and time.time() < deadline:
                if proc.poll() is not None:
                    err = proc.stderr.read() if proc.stderr else ""
                    raise AssertionError(
                        f"lock holder exited early: "
                        f"{proc.returncode} {err}",
                    )
                time.sleep(0.05)
            assert ready.is_file(), "child did not acquire finalize lock"
            with _exclusive_file_lock(lock_path, blocking=False) as held:
                assert held is False
            proc.kill()
            proc.wait(timeout=5)
            # Windows may keep the file handle briefly after kill; poll until
            # the OS lock is observable as free, then take it.
            started = time.monotonic()
            acquired = False
            while time.monotonic() - started < 5.0:
                with _exclusive_file_lock(lock_path, blocking=False) as held:
                    if held:
                        acquired = True
                        break
                time.sleep(0.05)
            assert acquired is True
            assert time.monotonic() - started < 5.0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_windows_blocking_lock_retries_past_ten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Windows blocking acquire must poll beyond msvcrt.LK_LOCK's ~10 tries."""
    # pylint: disable=protected-access
    from qwenpaw.agents import fork_project as fp

    monkeypatch.setattr(fp.os, "name", "nt")
    monkeypatch.setattr(fp, "_WINDOWS_LOCK_POLL_S", 0)
    attempts = {"n": 0}

    class _FakeMsvcrt:
        LK_NBLCK = 1
        LK_LOCK = 2
        LK_UNLCK = 3

        def locking(self, _fd: int, mode: int, _nbytes: int) -> None:
            if mode == self.LK_UNLCK:
                return
            attempts["n"] += 1
            # Exceed the historical LK_LOCK ~10-retry ceiling.
            if attempts["n"] <= 12:
                raise OSError(errno.EDEADLK, "lock conflict")

    monkeypatch.setitem(sys.modules, "msvcrt", _FakeMsvcrt())
    lock_path = tmp_path / "win.lock"
    with fp._exclusive_file_lock(lock_path, blocking=True) as acquired:
        assert acquired is True
    assert attempts["n"] == 13


def test_finalize_idempotent_and_mark_failed_skips_finalized(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert (
        finalize_fork_worktree(
            str(wt),
            branch,
            message="feat",
            expected_scope=scope,
        )
        is True
    )
    # Second finalize path (console hook / watcher / check_agent_task).
    assert (
        finalize_fork_worktree_or_fail(
            str(wt),
            branch,
            expected_scope=scope,
        )
        is True
    )
    mark_fork_failed(
        str(wt),
        branch,
        reason="losing race",
        expected_scope=scope,
    )
    assert forks_merged_into_head(project, scope_id=scope) is False
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_fork_registry_with_space_in_project_path(tmp_path: Path) -> None:
    """Paths with spaces must round-trip through register/finalize/merge."""
    project = tmp_path / "code project"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(
        str(wt),
        branch,
        message="feat",
        expected_scope=scope,
    )
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_concurrent_finalize_is_serialized(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")

    results: list[bool] = []

    def _run() -> None:
        results.append(
            finalize_fork_worktree_or_fail(
                str(wt),
                branch,
                message="feat",
                expected_scope=scope,
            ),
        )

    threads = [threading.Thread(target=_run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(results)
    assert forks_merged_into_head(project, scope_id=scope) is False
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_gate_uses_integration_project_not_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)

    scope = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=workspace,
        scope_id=scope,
    )
    assert resolve_integration_project_dir(workspace) == project.resolve()

    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert (
        finalize_fork_worktree(
            str(wt),
            branch,
            message="feat",
            expected_scope=scope,
        )
        is True
    )

    forks_integrated = _load_fork_guard().forks_integrated
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )

    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_unfinalized_tip_equals_base_does_not_pass(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)

    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=project,
        scope_id=scope,
    )

    assert forks_merged_into_head(project, scope_id=scope) is False

    # Explicit empty finalize (no_changes) is allowed.
    assert (
        finalize_fork_worktree(str(wt), branch, expected_scope=scope) is True
    )
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_commit_and_merge_verification(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)

    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(
        str(wt),
        branch,
        message="worker feat",
        expected_scope=scope,
    )

    forks_integrated = _load_fork_guard().forks_integrated
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=project,
        )
        is False
    )

    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=project,
        )
        is True
    )
