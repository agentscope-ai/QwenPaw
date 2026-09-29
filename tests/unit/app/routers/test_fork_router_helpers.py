# -*- coding: utf-8 -*-
"""Tests for fork router request and workspace helpers."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

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

    def test_workspace_fallback_when_no_project_dir(
        self,
        tmp_path,
        monkeypatch,
    ):
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


class TestGetWorkspace:
    @pytest.mark.asyncio
    async def test_returns_available_workspace(self):
        workspace = SimpleNamespace(
            session=object(),
            transcript_store=object(),
        )

        class Manager:
            async def get_agent(self, _agent_id):
                return workspace

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(multi_agent_manager=Manager()),
            ),
        )

        assert await fork_module._get_workspace(request, "a1") is workspace

    @pytest.mark.asyncio
    async def test_rejects_unavailable_storage(self):
        workspace = SimpleNamespace(session=None, transcript_store=None)

        class Manager:
            async def get_agent(self, _agent_id):
                return workspace

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(multi_agent_manager=Manager()),
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            await fork_module._get_workspace(request, "a1")
        assert exc_info.value.status_code == 503
