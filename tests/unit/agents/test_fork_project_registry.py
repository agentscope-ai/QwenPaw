# -*- coding: utf-8 -*-
"""Tests for fork project registry I/O and path resolution.

Covers the fork registry read/write helpers (malformed-file tolerance),
the has_registered_forks status/scope filters, the integration project
pointer resolution, the git-root resolution (including the .git-file
worktree exclusion), the agent workspace fallback, and the unix branch
of the lock-file acquire helper.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.agents.fork_project import (
    _lock_file_acquire,
    _lock_file_release,
    _read_registry_unlocked,
    _registry_path_for_project,
    _write_registry_unlocked,
    has_registered_forks,
    resolve_git_project_dir,
    resolve_integration_project_dir,
    INTEGRATION_PROJECT_REL,
)


# ---------------------------------------------------------------------------
# registry read/write
# ---------------------------------------------------------------------------


class TestReadRegistry:
    def test_missing_file_returns_empty_skeleton(self, tmp_path):
        data = _read_registry_unlocked(tmp_path)
        assert data == {"forks": {}, "by_task": {}}

    def test_malformed_json_returns_empty_skeleton(self, tmp_path):
        path = _registry_path_for_project(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert _read_registry_unlocked(tmp_path) == {
            "forks": {},
            "by_task": {},
        }

    def test_non_dict_json_returns_empty_skeleton(self, tmp_path):
        path = _registry_path_for_project(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("[1, 2]", encoding="utf-8")
        assert _read_registry_unlocked(tmp_path) == {
            "forks": {},
            "by_task": {},
        }

    def test_bad_sections_normalized(self, tmp_path):
        path = _registry_path_for_project(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"forks": "nope", "by_task": [1]}),
            encoding="utf-8",
        )
        data = _read_registry_unlocked(tmp_path)
        assert data["forks"] == {}
        assert data["by_task"] == {}

    def test_valid_registry_round_trip(self, tmp_path):
        payload = {
            "forks": {
                "branch-1": {"status": "pending", "scope_id": "s1"},
            },
            "by_task": {"task-1": {"branch": "branch-1"}},
        }
        _write_registry_unlocked(tmp_path, payload)
        data = _read_registry_unlocked(tmp_path)
        assert data == payload

    def test_write_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "project"
        _write_registry_unlocked(nested, {"forks": {}, "by_task": {}})
        assert _registry_path_for_project(nested).is_file()


# ---------------------------------------------------------------------------
# has_registered_forks
# ---------------------------------------------------------------------------


def _seed_registry(project: Path, forks: dict, by_task: dict | None = None):
    _write_registry_unlocked(
        project,
        {"forks": forks, "by_task": by_task or {}},
    )


class TestHasRegisteredForks:
    def test_none_project_returns_false(self):
        assert has_registered_forks(None) is False

    def test_no_registry_returns_false(self, tmp_path):
        assert has_registered_forks(tmp_path) is False

    def test_pending_fork_counts_as_active(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "pending"}})
        assert has_registered_forks(tmp_path) is True

    def test_finalizing_fork_counts_as_active(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "finalizing"}})
        assert has_registered_forks(tmp_path) is True

    def test_finalized_fork_counts_as_active(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "finalized"}})
        assert has_registered_forks(tmp_path) is True

    def test_failed_fork_not_active(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "failed"}})
        assert has_registered_forks(tmp_path) is False

    def test_merged_fork_not_active(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "merged"}})
        assert has_registered_forks(tmp_path) is False

    def test_missing_status_defaults_to_pending(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {}})
        assert has_registered_forks(tmp_path) is True

    def test_non_dict_entry_skipped(self, tmp_path):
        _seed_registry(tmp_path, {"b1": "garbage"})
        assert has_registered_forks(tmp_path) is False

    def test_scope_filter_matches(self, tmp_path):
        _seed_registry(
            tmp_path,
            {
                "b1": {"status": "pending", "scope_id": "scope-a"},
                "b2": {"status": "pending", "scope_id": "scope-b"},
            },
        )
        assert has_registered_forks(tmp_path, scope_id="scope-a") is True
        assert has_registered_forks(tmp_path, scope_id="scope-c") is False

    def test_scope_filter_without_meta_scope(self, tmp_path):
        _seed_registry(tmp_path, {"b1": {"status": "pending"}})
        assert has_registered_forks(tmp_path, scope_id="s1") is False


# ---------------------------------------------------------------------------
# resolve_integration_project_dir
# ---------------------------------------------------------------------------


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


class TestResolveIntegrationProjectDir:
    def test_none_workspace_returns_none(self):
        assert resolve_integration_project_dir(None) is None

    def test_no_pointer_returns_none(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert resolve_integration_project_dir(ws) is None

    def test_pointer_to_git_repo_resolved(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        repo = _make_git_repo(tmp_path / "repo")
        pointer = ws / INTEGRATION_PROJECT_REL
        pointer.parent.mkdir(parents=True)
        pointer.write_text(str(repo), encoding="utf-8")
        assert resolve_integration_project_dir(ws) == repo

    def test_pointer_to_missing_path_ignored(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        pointer = ws / INTEGRATION_PROJECT_REL
        pointer.parent.mkdir(parents=True)
        pointer.write_text(str(tmp_path / "gone"), encoding="utf-8")
        assert resolve_integration_project_dir(ws) is None

    def test_pointer_to_non_repo_ignored(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        plain = tmp_path / "plain"
        plain.mkdir()  # no .git
        pointer = ws / INTEGRATION_PROJECT_REL
        pointer.parent.mkdir(parents=True)
        pointer.write_text(str(plain), encoding="utf-8")
        assert resolve_integration_project_dir(ws) is None

    def test_blank_pointer_falls_through(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        pointer = ws / INTEGRATION_PROJECT_REL
        pointer.parent.mkdir(parents=True)
        pointer.write_text("   \n", encoding="utf-8")
        assert resolve_integration_project_dir(ws) is None


# ---------------------------------------------------------------------------
# resolve_git_project_dir
# ---------------------------------------------------------------------------


class TestResolveGitProjectDir:
    def test_explicit_git_workspace_resolved(self, tmp_path):
        ws = _make_git_repo(tmp_path / "proj")
        result = resolve_git_project_dir(ws)
        assert result == ws

    def test_plain_dir_without_git_returns_none(self, tmp_path):
        ws = tmp_path / "plain"
        ws.mkdir()
        assert resolve_git_project_dir(ws) is None

    def test_git_file_worktree_not_treated_as_root(self, tmp_path):
        """Linked worktrees use a .git *file*; only a .git dir is a root."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: ../main/.git", encoding="utf-8")
        assert resolve_git_project_dir(wt) is None

    def test_none_inputs_no_agent_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_agent_id",
            lambda: None,
        )
        assert resolve_git_project_dir(None) is None

    def test_agent_config_priority_project_first(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        project = _make_git_repo(tmp_path / "proj")
        workspace = _make_git_repo(tmp_path / "ws")
        config = SimpleNamespace(
            project_dir=str(project),
            workspace_dir=str(workspace),
        )
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda aid: config,
        )
        result = resolve_git_project_dir(None, agent_id="agent-1")
        assert result == project

    def test_agent_workspace_used_when_no_project(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        workspace = _make_git_repo(tmp_path / "ws")
        config = SimpleNamespace(project_dir=None, workspace_dir=str(workspace))
        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda aid: config,
        )
        result = resolve_git_project_dir(None, agent_id="agent-1")
        assert result == workspace

    def test_explicit_workspace_not_rebound_by_agent(self, tmp_path, monkeypatch):
        """An explicit workspace_dir wins and no agent lookup happens."""
        from types import SimpleNamespace

        ws = _make_git_repo(tmp_path / "ws")
        other = _make_git_repo(tmp_path / "other")
        config = SimpleNamespace(project_dir=str(other), workspace_dir=None)
        called = []

        def load(aid):
            called.append(aid)
            return config

        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            load,
        )
        result = resolve_git_project_dir(ws, agent_id=None)
        assert result == ws
        assert called == []


# ---------------------------------------------------------------------------
# _lock_file_acquire (unix fcntl branch)
# ---------------------------------------------------------------------------


class TestLockFileAcquire:
    def test_blocking_acquire_and_release(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        fh = open(lock_path, "w+")
        try:
            assert _lock_file_acquire(fh, blocking=True) is True
            _lock_file_release(fh)
        finally:
            fh.close()

    def test_non_blocking_fails_when_held(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        fh_first = open(lock_path, "w+")
        fh_second = open(lock_path, "w+")
        try:
            assert _lock_file_acquire(fh_first, blocking=True) is True
            assert _lock_file_acquire(fh_second, blocking=False) is False
            _lock_file_release(fh_first)
            # released -> second handle can now take it
            assert _lock_file_acquire(fh_second, blocking=False) is True
            _lock_file_release(fh_second)
        finally:
            fh_first.close()
            fh_second.close()
