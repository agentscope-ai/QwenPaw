# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unnecessary-lambda,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for agents/acp/service.py process & registry helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the ACP service registry
and process-tree helpers, which previously had zero unit-test coverage.
"""

from __future__ import annotations

import os
import sys

import pytest

import qwenpaw.agents.acp.service as acp_service
from qwenpaw.agents.acp.core import ACPConfigurationError
from qwenpaw.config.config import ACPConfig


@pytest.fixture(autouse=True)
def _clean_registry():
    acp_service._acp_services.clear()
    yield
    acp_service._acp_services.clear()


# ---------------------------------------------------------------------------
# _kill_process_tree
# ---------------------------------------------------------------------------


class TestKillProcessTree:
    def test_no_such_process_is_noop(self, monkeypatch):
        import psutil

        def missing(pid):
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(psutil, "Process", missing)
        acp_service._kill_process_tree(12345)  # must not raise

    def test_kills_children_then_parent(self, monkeypatch):
        import psutil

        killed = []

        class _FakeProc:
            def __init__(self, pid):
                self.pid = pid

            def children(self, recursive=False):
                return [_FakeProc(2), _FakeProc(3)]

            def kill(self):
                killed.append(self.pid)

        monkeypatch.setattr(psutil, "Process", lambda pid: _FakeProc(pid))
        acp_service._kill_process_tree(1)
        assert killed == [2, 3, 1]

    def test_child_kill_errors_swallowed(self, monkeypatch):
        import psutil

        class _Child:
            def kill(self):
                raise psutil.NoSuchProcess(2)

        class _Parent:
            def __init__(self, pid):
                self.pid = pid

            def children(self, recursive=False):
                return [_Child()]

            def kill(self):
                pass

        monkeypatch.setattr(psutil, "Process", lambda pid: _Parent(pid))
        acp_service._kill_process_tree(1)  # must not raise

    def test_parent_kill_errors_swallowed(self, monkeypatch):
        import psutil

        class _Parent:
            def __init__(self, pid):
                self.pid = pid

            def children(self, recursive=False):
                return []

            def kill(self):
                raise psutil.NoSuchProcess(self.pid)

        monkeypatch.setattr(psutil, "Process", lambda pid: _Parent(pid))
        acp_service._kill_process_tree(1)  # must not raise


# ---------------------------------------------------------------------------
# _resolve_process_command
# ---------------------------------------------------------------------------


class TestResolveProcessCommand:
    @staticmethod
    def _host_exe(name: str) -> str:
        # shutil.which on Windows only matches PATHEXT extensions.
        return f"{name}.exe" if sys.platform == "win32" else name

    def test_found_on_path(self, tmp_path):
        exe = tmp_path / self._host_exe("mytool")
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        result = acp_service._resolve_process_command(
            "mytool",
            {"PATH": str(tmp_path)},
        )
        assert os.path.normcase(result) == os.path.normcase(str(exe))

    def test_case_insensitive_path_key(self, tmp_path):
        exe = tmp_path / self._host_exe("mytool")
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        result = acp_service._resolve_process_command(
            "mytool",
            {"Path": str(tmp_path)},
        )
        assert os.path.normcase(result) == os.path.normcase(str(exe))

    def test_not_found_returns_original(self, tmp_path):
        result = acp_service._resolve_process_command(
            "definitely-not-a-real-tool",
            {"PATH": str(tmp_path)},
        )
        assert result == "definitely-not-a-real-tool"

    def test_no_path_key(self, monkeypatch):
        monkeypatch.setattr(
            acp_service.shutil,
            "which",
            lambda c, path=None: None,
        )
        assert acp_service._resolve_process_command("x", {}) == "x"


# ---------------------------------------------------------------------------
# service registry
# ---------------------------------------------------------------------------


class TestServiceRegistry:
    def test_get_none_when_missing(self):
        assert acp_service.get_acp_service("ghost") is None

    def test_get_none_for_none_id(self):
        assert acp_service.get_acp_service(None) is None

    def test_init_and_get(self):
        service = acp_service.init_acp_service("a1", ACPConfig())
        assert acp_service.get_acp_service("a1") is service

    def test_init_replaces_previous(self):
        first = acp_service.init_acp_service("a1", ACPConfig())
        second = acp_service.init_acp_service("a1", ACPConfig())
        assert second is not first
        assert acp_service.get_acp_service("a1") is second

    def test_close_removes(self):
        acp_service.init_acp_service("a1", ACPConfig())
        acp_service.close_acp_service("a1")
        assert acp_service.get_acp_service("a1") is None

    def test_close_unknown_is_noop(self):
        acp_service.close_acp_service("ghost")  # must not raise

    def test_shutdown_clears_registry(self):
        acp_service.init_acp_service("a1", ACPConfig())
        acp_service.init_acp_service("a2", ACPConfig())
        acp_service._shutdown_acp_services()
        assert acp_service._acp_services == {}

    def test_shutdown_empty_registry_ok(self):
        acp_service._shutdown_acp_services()  # must not raise


# ---------------------------------------------------------------------------
# _prompt_blocks_to_models
# ---------------------------------------------------------------------------


class TestPromptBlocksToModels:
    def test_text_blocks_converted(self):
        from qwenpaw.agents.acp.service import ACPService

        models = ACPService._prompt_blocks_to_models(
            [{"type": "text", "text": "hello"}],
        )
        assert len(models) == 1

    def test_non_text_block_rejected(self):
        from qwenpaw.agents.acp.service import ACPService

        with pytest.raises(ACPConfigurationError):
            ACPService._prompt_blocks_to_models([{"type": "image"}])

    def test_empty_list(self):
        from qwenpaw.agents.acp.service import ACPService

        assert ACPService._prompt_blocks_to_models([]) == []


class TestConversationDataclass:
    def test_fields(self):
        import asyncio

        conv = acp_service._Conversation(
            chat_id="c1",
            agent="a1",
            acp_session_id="s1",
            cwd="/tmp",
            conn=None,
            process=None,
            client=None,
            exit_stack=None,
            turn_lock=asyncio.Lock(),
        )
        assert conv.chat_id == "c1"
        assert conv.prompt_task is None
