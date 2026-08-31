# -*- coding: utf-8 -*-
"""Tests for fork router session and project-dir helpers.

Covers _enforce_localhost, _get_project_dir (git-repo detection and
fallback), _get_sessions_dir, _session_path filename conventions,
_read_session_state tolerance, and _write_fork_session round-trip,
which previously had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import fork as fork_module


# ---------------------------------------------------------------------------
# _enforce_localhost
# ---------------------------------------------------------------------------


class TestEnforceLocalhost:
    def test_localhost_allowed(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        fork_module._enforce_localhost(request)  # must not raise

    def test_ipv6_loopback_allowed(self):
        request = SimpleNamespace(client=SimpleNamespace(host="::1"))
        fork_module._enforce_localhost(request)  # must not raise

    def test_no_client_allowed(self):
        request = SimpleNamespace(client=None)
        fork_module._enforce_localhost(request)  # must not raise

    def test_remote_rejected(self):
        request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.5"))
        with pytest.raises(HTTPException) as exc_info:
            fork_module._enforce_localhost(request)
        assert exc_info.value.status_code == 403
        assert "localhost-only" in exc_info.value.detail


# ---------------------------------------------------------------------------
# _get_project_dir
# ---------------------------------------------------------------------------


class TestGetProjectDir:
    def test_missing_agent_raises_404(self, monkeypatch):
        def boom(agent_id):
            raise KeyError(agent_id)

        monkeypatch.setattr(fork_module, "load_agent_config", boom)
        with pytest.raises(HTTPException) as exc_info:
            fork_module._get_project_dir("ghost")
        assert exc_info.value.status_code == 404

    def test_git_project_dir_returned(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        (project / ".git").mkdir()
        config = SimpleNamespace(project_dir=str(project), workspace_dir="")
        monkeypatch.setattr(
            fork_module,
            "load_agent_config",
            lambda aid: config,
        )
        assert fork_module._get_project_dir("a1") == project.resolve()

    def test_workspace_fallback_when_no_project_dir(self, tmp_path, monkeypatch):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        config = SimpleNamespace(project_dir="", workspace_dir=str(workspace))
        monkeypatch.setattr(
            fork_module,
            "load_agent_config",
            lambda aid: config,
        )
        assert fork_module._get_project_dir("a1") == workspace.resolve()

    def test_non_git_dir_returns_none(self, tmp_path, monkeypatch):
        project = tmp_path / "plain"
        project.mkdir()
        config = SimpleNamespace(project_dir=str(project), workspace_dir="")
        monkeypatch.setattr(
            fork_module,
            "load_agent_config",
            lambda aid: config,
        )
        assert fork_module._get_project_dir("a1") is None

    def test_missing_dir_returns_none(self, tmp_path, monkeypatch):
        config = SimpleNamespace(
            project_dir=str(tmp_path / "gone"),
            workspace_dir="",
        )
        monkeypatch.setattr(
            fork_module,
            "load_agent_config",
            lambda aid: config,
        )
        assert fork_module._get_project_dir("a1") is None


# ---------------------------------------------------------------------------
# _get_sessions_dir
# ---------------------------------------------------------------------------


class TestGetSessionsDir:
    def test_resolves_workspace_sessions(self, tmp_path, monkeypatch):
        config = SimpleNamespace(workspace_dir=str(tmp_path))
        monkeypatch.setattr(
            fork_module,
            "load_agent_config",
            lambda aid: config,
        )
        result = fork_module._get_sessions_dir("a1")
        assert result == (tmp_path / "sessions").resolve()

    def test_config_failure_raises_404(self, monkeypatch):
        def boom(agent_id):
            raise RuntimeError("no config")

        monkeypatch.setattr(fork_module, "load_agent_config", boom)
        with pytest.raises(HTTPException) as exc_info:
            fork_module._get_sessions_dir("ghost")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _session_path
# ---------------------------------------------------------------------------


class TestSessionPath:
    def test_session_only(self, tmp_path):
        result = fork_module._session_path(tmp_path, "s1", None, None)
        assert result == tmp_path / "s1.json"

    def test_user_id_prefixed(self, tmp_path):
        result = fork_module._session_path(tmp_path, "s1", "user1", None)
        assert result == tmp_path / "user1_s1.json"

    def test_channel_subdirectory(self, tmp_path):
        result = fork_module._session_path(tmp_path, "s1", "user1", "console")
        assert result == tmp_path / "console" / "user1_s1.json"

    def test_special_chars_sanitized(self, tmp_path):
        result = fork_module._session_path(
            tmp_path,
            "console:s1",
            "console:user",
            None,
        )
        # colon must be sanitized out of the filename
        assert ":" not in result.name


# ---------------------------------------------------------------------------
# _read_session_state
# ---------------------------------------------------------------------------


class TestReadSessionState:
    def test_missing_file_returns_empty(self, tmp_path):
        assert fork_module._read_session_state(tmp_path / "gone.json") == {}

    def test_valid_state_read(self, tmp_path):
        session_file = tmp_path / "s.json"
        session_file.write_text(
            json.dumps({"agent": {"context": []}}),
            encoding="utf-8",
        )
        result = fork_module._read_session_state(session_file)
        assert result == {"agent": {"context": []}}

    def test_non_dict_returns_empty(self, tmp_path):
        session_file = tmp_path / "s.json"
        session_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert fork_module._read_session_state(session_file) == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        session_file = tmp_path / "s.json"
        session_file.write_text("{broken", encoding="utf-8")
        assert fork_module._read_session_state(session_file) == {}


# ---------------------------------------------------------------------------
# _write_fork_session
# ---------------------------------------------------------------------------


class TestWriteForkSession:
    def test_write_and_read_back(self, tmp_path):
        state = {"agent": {"state": {"summary": "forked"}}}
        fork_module._write_fork_session(
            tmp_path,
            "fork-s1",
            state,
            user_id="user1",
        )
        expected = tmp_path / "user1_fork-s1.json"
        assert expected.exists()
        data = json.loads(expected.read_text(encoding="utf-8"))
        assert data == state

    def test_channel_creates_subdirectory(self, tmp_path):
        state = {"agent": {}}
        fork_module._write_fork_session(
            tmp_path,
            "fork-s1",
            state,
            user_id="u",
            channel="dingtalk",
        )
        expected = tmp_path / "dingtalk" / "u_fork-s1.json"
        assert expected.exists()

    def test_no_user_no_channel(self, tmp_path):
        state = {"agent": {}}
        fork_module._write_fork_session(tmp_path, "fork-s1", state)
        assert (tmp_path / "fork-s1.json").exists()

    def test_unicode_state_preserved(self, tmp_path):
        state = {"agent": {"summary": "中文摘要"}}
        fork_module._write_fork_session(tmp_path, "fork-s1", state)
        data = json.loads(
            (tmp_path / "fork-s1.json").read_text(encoding="utf-8"),
        )
        assert data["agent"]["summary"] == "中文摘要"
