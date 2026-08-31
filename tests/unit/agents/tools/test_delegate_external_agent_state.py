# -*- coding: utf-8 -*-
"""Tests for external-agent delegation state helpers and formatting.

Covers the runner-state store (get/set/append/status transitions),
content-text assembly and truncation, timestamp formatting, execution
cwd resolution, and the task-state / runner-list formatters, which
previously had no direct coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import time
from pathlib import Path

import pytest

from qwenpaw.agents.tools.delegate_external_agent import (
    _RunnerState,
    _copy_content_text,
    _format_task_state_text,
    _format_timestamp,
    _resolve_execution_cwd,
)

# The parent package shadows the module name with a tool function, so
# resolve the real module object through importlib.
from importlib import import_module

dea = import_module("qwenpaw.agents.tools.delegate_external_agent")


# ---------------------------------------------------------------------------
# _copy_content_text
# ---------------------------------------------------------------------------


class TestCopyContentText:
    def test_joins_text_blocks(self):
        blocks = [{"text": "first"}, {"text": "second"}]
        assert _copy_content_text(blocks) == "first\n\nsecond"

    def test_skips_empty_blocks(self):
        blocks = [{"text": "a"}, {"text": ""}, {"text": "   "}, {"text": "b"}]
        assert _copy_content_text(blocks) == "a\n\nb"

    def test_handles_object_blocks(self):
        class Block:
            text = "obj text"

        assert _copy_content_text([Block()]) == "obj text"

    def test_truncates_to_limit(self):
        blocks = [{"text": "x" * 100}]
        result = _copy_content_text(blocks, limit=10)
        assert len(result) == 10
        assert result == "x" * 10

    def test_truncation_keeps_tail(self):
        blocks = [{"text": "abcdefghij"}]
        result = _copy_content_text(blocks, limit=3)
        assert result == "hij"

    def test_empty_blocks_returns_empty(self):
        assert _copy_content_text([]) == ""


# ---------------------------------------------------------------------------
# _format_timestamp
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    def test_formats_epoch(self):
        result = _format_timestamp(0)
        assert result.startswith("1970-01-0")  # tz dependent

    def test_deterministic_for_same_value(self):
        assert _format_timestamp(1700000000) == _format_timestamp(1700000000)


# ---------------------------------------------------------------------------
# _resolve_execution_cwd
# ---------------------------------------------------------------------------


class TestResolveExecutionCwd:
    def test_empty_returns_workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = _resolve_execution_cwd("", ws)
        assert result == ws.resolve()

    def test_absolute_path_passthrough(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = _resolve_execution_cwd(str(tmp_path), ws)
        assert result == tmp_path.resolve()

    def test_relative_resolves_under_workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = _resolve_execution_cwd("sub/dir", ws)
        assert result == (ws / "sub" / "dir").resolve()

    def test_whitespace_treated_as_empty(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        result = _resolve_execution_cwd("   ", ws)
        assert result == ws.resolve()


# ---------------------------------------------------------------------------
# _RunnerState store
# ---------------------------------------------------------------------------


def _make_state(
    *,
    agent_id="agent-1",
    chat_id="chat-1",
    runner="runner-a",
    status="running",
) -> _RunnerState:
    return _RunnerState(
        agent_id=agent_id,
        chat_id=chat_id,
        runner=runner,
        action="run",
        status=status,
        created_at=100.0,
        updated_at=100.0,
    )


class TestRunnerStateStore:
    @pytest.fixture(autouse=True)
    def _clear_states(self):
        dea._runner_states.clear()
        yield
        dea._runner_states.clear()

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        state = _make_state()
        await dea._set_runner_state(state)
        fetched = await dea._get_runner_state(
            agent_id="agent-1",
            chat_id="chat-1",
            runner_name="runner-a",
        )
        assert fetched is state

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        result = await dea._get_runner_state(
            agent_id="ghost",
            chat_id="c",
            runner_name="r",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_append_content_updates_timestamp(self):
        state = _make_state()
        await dea._set_runner_state(state)
        before = state.updated_at
        await dea._append_runner_state_content(
            state,
            [{"text": "output"}],
        )
        assert state.content == [{"text": "output"}]
        assert state.updated_at >= before

    @pytest.mark.asyncio
    async def test_append_empty_blocks_is_noop(self):
        state = _make_state()
        await dea._set_runner_state(state)
        await dea._append_runner_state_content(state, [])
        assert state.content == []

    @pytest.mark.asyncio
    async def test_set_status_with_error(self):
        state = _make_state()
        await dea._set_runner_state(state)
        await dea._set_runner_state_status(
            state,
            "failed",
            error="boom",
        )
        assert state.status == "failed"
        assert state.error == "boom"
        assert state.pending_permission is None

    @pytest.mark.asyncio
    async def test_set_status_with_permission(self):
        state = _make_state()
        await dea._set_runner_state(state)
        await dea._set_runner_state_status(
            state,
            "awaiting_permission",
            pending_permission={"id": "perm-1"},
        )
        assert state.status == "awaiting_permission"
        assert state.pending_permission == {"id": "perm-1"}


# ---------------------------------------------------------------------------
# _format_task_state_text
# ---------------------------------------------------------------------------


class TestFormatTaskStateText:
    def test_no_state_reports_none_task(self):
        text = _format_task_state_text(
            runner_name="r1",
            session_state="connected",
            state=None,
        )
        assert "runner: r1" in text
        assert "session: connected" in text
        assert "task: none" in text

    def test_running_state_rendered(self):
        state = _make_state(status="running")
        text = _format_task_state_text(
            runner_name="runner-a",
            session_state="connected",
            state=state,
        )
        assert "task: running" in text
        assert "last action: run" in text
        assert "started at:" in text
        assert "updated at:" in text

    def test_pending_permission_overrides_status(self):
        state = _make_state(status="running")
        text = _format_task_state_text(
            runner_name="runner-a",
            session_state="connected",
            state=state,
            pending_permission={"id": "p"},
        )
        assert "task: permission_required" in text

    def test_error_rendered(self):
        state = _make_state(status="failed")
        state.error = "crashed"
        text = _format_task_state_text(
            runner_name="runner-a",
            session_state="connected",
            state=state,
        )
        assert "error: crashed" in text

    def test_content_appended_as_last_response(self):
        state = _make_state(status="completed")
        state.content = [{"text": "final answer"}]
        text = _format_task_state_text(
            runner_name="runner-a",
            session_state="connected",
            state=state,
        )
        assert "Last response:" in text
        assert "final answer" in text
