# -*- coding: utf-8 -*-
"""Property-based tests for /stop command recognition."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from copaw.app.runner.daemon_commands import is_stop_command


# Feature: stop-magic-command, Property 1: /stop 命令识别的完备性
# Validates: Requirements 1.1, 1.2, 1.3
class TestIsStopCommandProperty:
    """Property test: is_stop_command matches iff stripped text starts with /stop."""

    @given(s=st.text())
    @settings(max_examples=200)
    def test_stop_command_completeness(self, s: str) -> None:
        """For any string s, is_stop_command(s) == s.strip().lower().startswith('/stop')."""
        expected = s.strip().lower().startswith("/stop")
        assert is_stop_command(s) is expected

from copaw.app.runner.daemon_commands import parse_daemon_query


# Feature: stop-magic-command, Property 3: parse_daemon_query 正确解析 /stop
# Validates: Requirements 5.3, 1.4
class TestParseDaemonQueryStopProperty:
    """Property test: parse_daemon_query correctly parses /stop variants."""

    @given(args=st.lists(st.from_regex(r"[A-Za-z0-9_-]+", fullmatch=True), min_size=0, max_size=5))
    @settings(max_examples=100)
    def test_slash_stop_with_args(self, args: list[str]) -> None:
        """For /stop followed by arbitrary args, parse_daemon_query returns ("stop", args)."""
        query = "/stop" + ("" if not args else " " + " ".join(args))
        result = parse_daemon_query(query)
        assert result is not None
        sub, parsed_args = result
        assert sub == "stop"
        assert parsed_args == args

    @given(args=st.lists(st.from_regex(r"[A-Za-z0-9_-]+", fullmatch=True), min_size=0, max_size=5))
    @settings(max_examples=100)
    def test_daemon_stop_with_args(self, args: list[str]) -> None:
        """For /daemon stop followed by arbitrary args, parse_daemon_query returns ("stop", args)."""
        query = "/daemon stop" + ("" if not args else " " + " ".join(args))
        result = parse_daemon_query(query)
        assert result is not None
        sub, parsed_args = result
        assert sub == "stop"
        assert parsed_args == args

    @given(padding=st.from_regex(r"[ \t]*", fullmatch=True))
    @settings(max_examples=100)
    def test_slash_stop_with_whitespace_padding(self, padding: str) -> None:
        """For /stop with leading/trailing whitespace, parse_daemon_query still returns ("stop", [])."""
        query = padding + "/stop" + padding
        result = parse_daemon_query(query)
        assert result is not None
        sub, parsed_args = result
        assert sub == "stop"
        assert parsed_args == []


# Feature: stop-magic-command, Unit tests for is_stop_command
# Validates: Requirements 1.1, 1.2, 1.3
class TestIsStopCommandUnit:
    """Unit tests for is_stop_command with specific examples."""

    def test_exact_stop(self):
        assert is_stop_command("/stop") is True

    def test_stop_with_whitespace(self):
        assert is_stop_command("  /stop  ") is True

    def test_stop_with_args(self):
        assert is_stop_command("/stop now") is True

    def test_stop_uppercase(self):
        assert is_stop_command("/STOP") is True

    def test_status_not_stop(self):
        assert is_stop_command("/status") is False

    def test_empty_string(self):
        assert is_stop_command("") is False

    def test_none(self):
        assert is_stop_command(None) is False

    def test_stop_without_slash(self):
        assert is_stop_command("stop") is False


# Feature: stop-magic-command, Unit tests for parse_daemon_query with /stop
# Validates: Requirements 5.3, 1.4
class TestParseDaemonQueryStopUnit:
    """Unit tests for parse_daemon_query with /stop."""

    def test_slash_stop(self):
        result = parse_daemon_query("/stop")
        assert result == ("stop", [])

    def test_daemon_stop(self):
        result = parse_daemon_query("/daemon stop")
        assert result == ("stop", [])

    def test_stop_with_arg(self):
        result = parse_daemon_query("/stop arg1")
        assert result == ("stop", ["arg1"])


import asyncio
import pytest
from copaw.app.runner.daemon_commands import (
    run_daemon_stop,
    DaemonContext,
    DaemonCommandHandlerMixin,
)
from agentscope.message import Msg, TextBlock


# Feature: stop-magic-command, Unit tests for run_daemon_stop
# Validates: Requirements 5.1, 5.2
class TestRunDaemonStopUnit:
    """Unit tests for run_daemon_stop."""

    def test_returns_string_with_no_running_task_message(self):
        ctx = DaemonContext()
        result = run_daemon_stop(ctx)
        assert isinstance(result, str)
        assert "没有运行中的任务" in result

    def test_return_type_is_str(self):
        ctx = DaemonContext()
        result = run_daemon_stop(ctx)
        assert type(result) is str


# Feature: stop-magic-command, Unit tests for handle_daemon_command with /stop
# Validates: Requirements 5.1, 5.2
class TestHandleDaemonCommandStopUnit:
    """Unit tests for handle_daemon_command with /stop."""

    @pytest.mark.asyncio
    async def test_stop_returns_msg(self):
        handler = DaemonCommandHandlerMixin()
        ctx = DaemonContext()
        result = await handler.handle_daemon_command("/stop", ctx)
        assert isinstance(result, Msg)

    @pytest.mark.asyncio
    async def test_stop_msg_role_is_assistant(self):
        handler = DaemonCommandHandlerMixin()
        ctx = DaemonContext()
        result = await handler.handle_daemon_command("/stop", ctx)
        assert result.role == "assistant"

    @pytest.mark.asyncio
    async def test_stop_msg_contains_no_running_task(self):
        handler = DaemonCommandHandlerMixin()
        ctx = DaemonContext()
        result = await handler.handle_daemon_command("/stop", ctx)
        # content is a list of TextBlock (TypedDict), access via ["text"]
        text_parts = [
            block["text"] for block in result.content
            if block.get("type") == "text"
        ]
        full_text = " ".join(text_parts)
        assert "没有运行中的任务" in full_text

    @pytest.mark.asyncio
    async def test_daemon_stop_variant_returns_msg(self):
        handler = DaemonCommandHandlerMixin()
        ctx = DaemonContext()
        result = await handler.handle_daemon_command("/daemon stop", ctx)
        assert isinstance(result, Msg)
        text_parts = [
            block["text"] for block in result.content
            if block.get("type") == "text"
        ]
        full_text = " ".join(text_parts)
        assert "没有运行中的任务" in full_text


from copaw.app.runner.task_tracker import TaskTracker, _RunState


# Feature: stop-magic-command, Property 2: 停止活跃任务返回成功
# Validates: Requirements 2.3, 3.3, 4.2, 6.1
class TestRequestStopActiveTaskProperty:
    """Property test: request_stop on an active task returns True and cancels it."""

    @given(key=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_request_stop_active_task_returns_true_and_cancels(self, key: str) -> None:
        """For any active run (task not done), request_stop(key) returns True and task is cancelled.

        **Validates: Requirements 2.3, 3.3, 4.2, 6.1**
        """
        tracker = TaskTracker()
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        # Inject an active run state with a non-done future
        tracker._runs[key] = _RunState(task=future)

        result = await tracker.request_stop(key)

        assert result is True
        assert future.cancelled() is True


# Feature: stop-magic-command, Property 4: 重复停止的幂等性
# Validates: Requirements 7.2
class TestRequestStopIdempotencyProperty:
    """Property test: calling request_stop twice returns True then False."""

    @given(key=st.text(min_size=1, max_size=50))
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_repeated_stop_returns_true_then_false(self, key: str) -> None:
        """For any active run, request_stop(key) twice returns True then False.

        **Validates: Requirements 7.2**
        """
        tracker = TaskTracker()
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        # Inject an active run state with a non-done future
        tracker._runs[key] = _RunState(task=future)

        first = await tracker.request_stop(key)
        second = await tracker.request_stop(key)

        assert first is True
        assert second is False
