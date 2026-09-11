# -*- coding: utf-8 -*-
"""Integration tests for the fork-project registry module.

Covers src/qwenpaw/agents/fork_project.py (586 uncovered lines):
worktree path resolution, allowed fork directory validation,
integration project pointer binding, active scope read/write,
Windows lock-conflict classification, registry paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# path derivation helpers
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_project_dir_from_worktree(tmp_path: Path) -> None:
    """Worktree paths map back three levels to the project root."""
    from qwenpaw.agents.fork_project import project_dir_from_worktree

    project = tmp_path / "proj"
    worktree = project / ".qwenpaw" / "worktrees" / "abc123"
    worktree.mkdir(parents=True)

    assert project_dir_from_worktree(worktree) == project.resolve()


@pytest.mark.integration
@pytest.mark.p1
def test_registry_path_for_project(tmp_path: Path) -> None:
    """Registry path lives under .qwenpaw of the project."""
    from qwenpaw.agents.fork_project import _registry_path_for_project

    project = tmp_path / "proj"
    project.mkdir()
    registry = _registry_path_for_project(project)
    assert registry == project / ".qwenpaw" / "fork_registry.json"


@pytest.mark.integration
@pytest.mark.p1
def test_fork_finalize_lock_path_deterministic(tmp_path: Path) -> None:
    """Lock paths derive deterministically from branch names."""
    from qwenpaw.agents.fork_project import _fork_finalize_lock_path

    path_a = _fork_finalize_lock_path(tmp_path, "feature/x")
    path_b = _fork_finalize_lock_path(tmp_path, "feature/x")
    path_c = _fork_finalize_lock_path(tmp_path, "feature/y")
    assert path_a == path_b
    assert path_a != path_c
    assert path_a.parent == tmp_path / ".qwenpaw" / "fork_locks"
    assert path_a.suffix == ".lock"


# ------------------------------------------------------------------ #
# allowed fork directory validation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_allowed_fork_dir_under_worktree(tmp_path: Path) -> None:
    """A directory under the allowed worktree area is accepted."""
    from qwenpaw.agents.fork_project import (
        resolve_allowed_fork_project_dir,
    )

    project = tmp_path / "proj"
    worktree = project / ".qwenpaw" / "worktrees" / "wt1"
    worktree.mkdir(parents=True)

    result = resolve_allowed_fork_project_dir(
        str(worktree),
        project_dirs=[project],
    )
    assert result == worktree.resolve()


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_allowed_fork_dir_outside_rejected(tmp_path: Path) -> None:
    """Directories outside the worktree area are rejected."""
    from qwenpaw.agents.fork_project import (
        resolve_allowed_fork_project_dir,
    )

    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    result = resolve_allowed_fork_project_dir(
        str(outside),
        project_dirs=[project],
    )
    assert result is None


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_allowed_fork_dir_invalid_inputs(tmp_path: Path) -> None:
    """Empty, blank, missing, and non-string inputs are rejected."""
    from qwenpaw.agents.fork_project import (
        resolve_allowed_fork_project_dir,
    )

    project = tmp_path / "proj"
    project.mkdir()
    assert resolve_allowed_fork_project_dir(None) is None
    assert resolve_allowed_fork_project_dir("") is None
    assert resolve_allowed_fork_project_dir("   ") is None
    assert resolve_allowed_fork_project_dir(123) is None  # type: ignore
    missing = tmp_path / "no-such-dir"
    assert (
        resolve_allowed_fork_project_dir(
            str(missing),
            project_dirs=[project],
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_allowed_fork_dir_workspace_allowed(
    tmp_path: Path,
) -> None:
    """The agent workspace is also an allowed root for forks."""
    from qwenpaw.agents.fork_project import (
        resolve_allowed_fork_project_dir,
    )

    workspace = tmp_path / "ws"
    worktree = workspace / ".qwenpaw" / "worktrees" / "wt"
    worktree.mkdir(parents=True)

    result = resolve_allowed_fork_project_dir(
        str(worktree),
        workspace_dir=workspace,
    )
    assert result == worktree.resolve()


# ------------------------------------------------------------------ #
# integration project pointer
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_bind_workspace_integration_project(tmp_path: Path) -> None:
    """Binding writes the pointer file with the resolved project."""
    from qwenpaw.agents.fork_project import (
        INTEGRATION_PROJECT_REL,
        bind_workspace_integration_project,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    project = tmp_path / "proj"
    project.mkdir()

    bind_workspace_integration_project(ws, project)
    pointer = ws / INTEGRATION_PROJECT_REL
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8").strip() == str(
        project.resolve(),
    )


@pytest.mark.integration
@pytest.mark.p1
def test_bind_workspace_integration_project_none_workspace() -> None:
    """None workspace is a no-op."""
    from qwenpaw.agents.fork_project import (
        bind_workspace_integration_project,
    )

    bind_workspace_integration_project(None, "/tmp/whatever")  # no error


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_integration_project_dir_with_pointer(
    tmp_path: Path,
) -> None:
    """A valid pointer resolves to the referenced git project."""
    from qwenpaw.agents.fork_project import (
        INTEGRATION_PROJECT_REL,
        resolve_integration_project_dir,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".git").mkdir()

    pointer = ws / INTEGRATION_PROJECT_REL
    pointer.parent.mkdir(parents=True)
    pointer.write_text(str(project.resolve()) + "\n", encoding="utf-8")

    assert resolve_integration_project_dir(ws) == project.resolve()


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_integration_project_dir_invalid_pointer(
    tmp_path: Path,
) -> None:
    """Pointers at missing or non-git dirs are not usable."""
    from qwenpaw.agents.fork_project import (
        INTEGRATION_PROJECT_REL,
        resolve_integration_project_dir,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    pointer = ws / INTEGRATION_PROJECT_REL
    pointer.parent.mkdir(parents=True)
    pointer.write_text(str(tmp_path / "gone") + "\n", encoding="utf-8")

    assert resolve_integration_project_dir(ws) is None


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_integration_project_dir_none_workspace() -> None:
    """None workspace yields None."""
    from qwenpaw.agents.fork_project import resolve_integration_project_dir

    assert resolve_integration_project_dir(None) is None


# ------------------------------------------------------------------ #
# active scope persistence
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_active_scope_read_write_roundtrip(tmp_path: Path) -> None:
    """Active scope round-trips through the scope file."""
    from qwenpaw.agents.fork_project import (
        _read_active_scope,
        _write_active_scope,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    assert _read_active_scope(ws) == ""

    _write_active_scope(ws, "scope-123")
    assert _read_active_scope(ws) == "scope-123"

    _write_active_scope(ws, "scope-456")
    assert _read_active_scope(ws) == "scope-456"


# ------------------------------------------------------------------ #
# lock conflict classification
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_windows_lock_conflict_permission_error() -> None:
    """PermissionError signals another lock holder."""
    from qwenpaw.agents.fork_project import _windows_lock_conflict

    assert _windows_lock_conflict(PermissionError("locked")) is True


@pytest.mark.integration
@pytest.mark.p1
def test_windows_lock_conflict_winerror() -> None:
    """Windows sharing-violation winerrors are conflicts."""
    from qwenpaw.agents.fork_project import (
        _WINDOWS_LOCK_CONFLICT_WINERRORS,
        _windows_lock_conflict,
    )

    exc = OSError("locked")
    exc.winerror = next(iter(_WINDOWS_LOCK_CONFLICT_WINERRORS))
    assert _windows_lock_conflict(exc) is True


@pytest.mark.integration
@pytest.mark.p1
def test_windows_lock_conflict_plain_error() -> None:
    """Plain OS errors are not lock conflicts."""
    from qwenpaw.agents.fork_project import _windows_lock_conflict

    assert _windows_lock_conflict(OSError("something else")) is False


# ------------------------------------------------------------------ #
# git-backed fork flows
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_git_project_dir_none_for_non_git(tmp_path: Path) -> None:
    """Workspaces without a git repo yield None."""
    from qwenpaw.agents.fork_project import resolve_git_project_dir

    ws = tmp_path / "plain-ws"
    ws.mkdir()
    assert resolve_git_project_dir(ws) is None


@pytest.mark.integration
@pytest.mark.p1
def test_begin_fork_scope_creates_active_scope(tmp_path: Path) -> None:
    """begin_fork_scope writes a fresh active scope id."""
    from qwenpaw.agents.fork_project import (
        _read_active_scope,
        begin_fork_scope,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    scope = begin_fork_scope(ws)
    assert isinstance(scope, str)
    assert len(scope) == 12
    assert _read_active_scope(ws) == scope


@pytest.mark.integration
@pytest.mark.p1
def test_begin_fork_scope_none_workspace() -> None:
    """None workspace yields an empty scope without error."""
    from qwenpaw.agents.fork_project import begin_fork_scope

    assert begin_fork_scope(None) == ""
