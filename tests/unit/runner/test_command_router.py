# -*- coding: utf-8 -*-
"""Unit tests for CommandRouter registry and dispatch logic."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from agentscope.message import Msg

from copaw.app.runner.command_router import (
    CommandContext,
    CommandPriority,
    CommandRouter,
)


def _make_context(command_name: str = "test", **overrides) -> CommandContext:
    """Build a minimal CommandContext for testing."""
    defaults = dict(
        channel=MagicMock(),
        channel_id="ch-1",
        session_id="sess-1",
        user_id="user-1",
        command_name=command_name,
        command_args=[],
        raw_query=f"/{command_name}",
        payload=None,
        task_tracker=None,
        runner=None,
    )
    defaults.update(overrides)
    return CommandContext(**defaults)


# ------------------------------------------------------------------
# __init__
# ------------------------------------------------------------------
class TestCommandRouterInit:
    """Validates: Requirement 3.1 — registry initialisation."""

    def test_builtins_registered_on_init(self):
        """Router registers daemon commands on init."""
        router = CommandRouter()
        cmds = router.get_registered_commands()
        # All daemon commands + /daemon meta-command
        for name in ("stop", "approve", "restart", "reload-config",
                      "status", "version", "logs", "daemon"):
            assert name in cmds, f"/{name} not registered"

    def test_accepts_dependencies(self):
        """Router stores task_tracker and runner references."""
        tt = MagicMock()
        rn = MagicMock()
        router = CommandRouter(task_tracker=tt, runner=rn)
        assert router._task_tracker is tt
        assert router._runner is rn


# ------------------------------------------------------------------
# register_command
# ------------------------------------------------------------------
class TestRegisterCommand:
    """Validates: Requirements 3.7, 5.5, 9.3."""

    def test_register_with_default_priority(self):
        router = CommandRouter()
        handler = MagicMock()
        router.register_command("ping", handler)
        assert "ping" in router.get_registered_commands()
        assert router.get_priority("ping") == CommandPriority.NORMAL

    def test_register_with_explicit_priority(self):
        router = CommandRouter()
        handler = MagicMock()
        router.register_command("halt", handler, CommandPriority.CRITICAL)
        assert router.get_priority("halt") == CommandPriority.CRITICAL

    def test_register_overwrites_existing(self):
        router = CommandRouter()
        h1 = MagicMock()
        h2 = MagicMock()
        router.register_command("x", h1, CommandPriority.LOW)
        router.register_command("x", h2, CommandPriority.HIGH)
        assert router.get_priority("x") == CommandPriority.HIGH


# ------------------------------------------------------------------
# get_priority
# ------------------------------------------------------------------
class TestGetPriority:
    """Validates: Requirement 3.8."""

    def test_returns_registered_priority(self):
        router = CommandRouter()
        router.register_command("stop", MagicMock(), CommandPriority.CRITICAL)
        assert router.get_priority("stop") == CommandPriority.CRITICAL

    def test_returns_normal_for_unknown(self):
        router = CommandRouter()
        assert router.get_priority("nonexistent") == CommandPriority.NORMAL


# ------------------------------------------------------------------
# get_registered_commands
# ------------------------------------------------------------------
class TestGetRegisteredCommands:
    """Validates: Requirement 3.1."""

    def test_returns_frozenset(self):
        router = CommandRouter()
        result = router.get_registered_commands()
        assert isinstance(result, frozenset)

    def test_reflects_registrations(self):
        router = CommandRouter()
        router.register_command("a", MagicMock())
        router.register_command("b", MagicMock())
        cmds = router.get_registered_commands()
        assert "a" in cmds
        assert "b" in cmds


# ------------------------------------------------------------------
# dispatch — known command
# ------------------------------------------------------------------
class TestDispatchKnownCommand:
    """Validates: Requirement 3.4."""

    @pytest.mark.asyncio
    async def test_calls_handler_and_returns_msg(self):
        router = CommandRouter()
        expected = Msg(name="Friday", role="assistant", content=[])

        async def handler(ctx):
            return expected

        router.register_command("ping", handler)
        ctx = _make_context("ping")
        result = await router.dispatch(ctx)
        assert result is expected

    @pytest.mark.asyncio
    async def test_passes_context_to_handler(self):
        router = CommandRouter()
        received = {}

        async def handler(ctx):
            received["ctx"] = ctx
            return Msg(name="Friday", role="assistant", content=[])

        router.register_command("info", handler)
        ctx = _make_context("info", session_id="s42")
        await router.dispatch(ctx)
        assert received["ctx"].session_id == "s42"


# ------------------------------------------------------------------
# dispatch — unknown command
# ------------------------------------------------------------------
class TestDispatchUnknownCommand:
    """Validates: Requirement 3.5."""

    @pytest.mark.asyncio
    async def test_returns_hint_msg(self):
        router = CommandRouter()
        ctx = _make_context("bogus")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        text = result.content[0]["text"]
        assert "Unknown command" in text
        assert "/bogus" in text

    @pytest.mark.asyncio
    async def test_does_not_raise(self):
        router = CommandRouter()
        ctx = _make_context("nope")
        # Should not raise
        result = await router.dispatch(ctx)
        assert result is not None


# ------------------------------------------------------------------
# dispatch — handler exception safety
# ------------------------------------------------------------------
class TestDispatchExceptionSafety:
    """Validates: Requirement 4.20 (error Msg, no propagation)."""

    @pytest.mark.asyncio
    async def test_catches_runtime_error(self):
        router = CommandRouter()

        async def bad_handler(ctx):
            raise RuntimeError("boom")

        router.register_command("fail", bad_handler)
        ctx = _make_context("fail")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        text = result.content[0]["text"]
        assert "Error executing /fail" in text

    @pytest.mark.asyncio
    async def test_catches_value_error(self):
        router = CommandRouter()

        async def bad_handler(ctx):
            raise ValueError("bad value")

        router.register_command("val", bad_handler)
        ctx = _make_context("val")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "Error executing /val" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_catches_generic_exception(self):
        router = CommandRouter()

        async def bad_handler(ctx):
            raise Exception("generic")

        router.register_command("gen", bad_handler)
        ctx = _make_context("gen")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert result.role == "assistant"


# ------------------------------------------------------------------
# _register_builtins — daemon commands (Task 2.1)
# ------------------------------------------------------------------
class TestRegisterBuiltinsDaemon:
    """Validates: Requirements 3.2, 4.1-4.9, 5.1 — daemon command registration."""

    EXPECTED_DAEMON_COMMANDS = {
        "stop": CommandPriority.CRITICAL,
        "approve": CommandPriority.HIGH,
        "restart": CommandPriority.NORMAL,
        "reload-config": CommandPriority.NORMAL,
        "status": CommandPriority.LOW,
        "version": CommandPriority.LOW,
        "logs": CommandPriority.LOW,
    }

    def test_all_daemon_commands_registered(self):
        router = CommandRouter()
        cmds = router.get_registered_commands()
        for name in self.EXPECTED_DAEMON_COMMANDS:
            assert name in cmds, f"/{name} should be registered"

    def test_daemon_command_priorities(self):
        router = CommandRouter()
        for name, expected_prio in self.EXPECTED_DAEMON_COMMANDS.items():
            assert router.get_priority(name) == expected_prio, (
                f"/{name} priority mismatch"
            )

    def test_daemon_meta_command_registered(self):
        router = CommandRouter()
        assert "daemon" in router.get_registered_commands()

    @pytest.mark.asyncio
    async def test_stop_with_task_tracker_calls_request_stop(self):
        """Validates: Req 4.1, 4.8 — /stop uses task_tracker.request_stop."""
        tt = MagicMock()
        tt.request_stop = MagicMock(return_value=True)
        # Make request_stop a coroutine
        import asyncio

        async def _mock_stop(run_key):
            return True

        tt.request_stop = _mock_stop

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="run-key-1")

        router = CommandRouter(task_tracker=tt)
        ctx = _make_context(
            "stop",
            task_tracker=tt,
            channel=channel,
            payload={"some": "payload"},
        )
        result = await router.dispatch(ctx)
        assert "Task stopped" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_stop_without_running_task(self):
        """Validates: Req 4.9 — /stop when no task running."""
        tt = MagicMock()

        async def _mock_stop(run_key):
            return False

        tt.request_stop = _mock_stop

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="run-key-1")

        router = CommandRouter(task_tracker=tt)
        ctx = _make_context(
            "stop",
            task_tracker=tt,
            channel=channel,
            payload=None,
        )
        result = await router.dispatch(ctx)
        assert "No running task" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_stop_without_task_tracker(self):
        """Validates: /stop fallback when no task_tracker."""
        router = CommandRouter()
        ctx = _make_context("stop")
        result = await router.dispatch(ctx)
        assert "No running task" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_status_returns_msg(self):
        """Validates: Req 4.2 — /status returns daemon status."""
        router = CommandRouter()
        ctx = _make_context("status")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "Daemon Status" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_version_returns_msg(self):
        """Validates: Req 4.5 — /version returns version info."""
        router = CommandRouter()
        ctx = _make_context("version")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "version" in result.content[0]["text"].lower()

    @pytest.mark.asyncio
    async def test_daemon_meta_dispatches_to_sub(self):
        """Validates: Req 3.9 — /daemon status dispatches to /status handler."""
        router = CommandRouter()
        ctx = _make_context(
            "daemon",
            command_args=["status"],
            raw_query="/daemon status",
        )
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "Daemon Status" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_daemon_meta_unknown_sub(self):
        """Validates: /daemon with unknown subcommand returns error."""
        router = CommandRouter()
        ctx = _make_context(
            "daemon",
            command_args=["nonexistent"],
            raw_query="/daemon nonexistent",
        )
        result = await router.dispatch(ctx)
        assert "Unknown daemon subcommand" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_daemon_meta_no_args_defaults_to_status(self):
        """Validates: /daemon with no args defaults to status."""
        router = CommandRouter()
        ctx = _make_context(
            "daemon",
            command_args=[],
            raw_query="/daemon",
        )
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "Daemon Status" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_logs_with_line_count_arg(self):
        """Validates: Req 4.6 — /logs passes line count argument."""
        router = CommandRouter()
        ctx = _make_context(
            "logs",
            command_args=["50"],
            raw_query="/logs 50",
        )
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "50" in result.content[0]["text"]


# ------------------------------------------------------------------
# _register_builtins — conversation commands (Task 2.2)
# ------------------------------------------------------------------
class TestRegisterBuiltinsConversation:
    """Validates: Requirements 3.3, 3.10, 4.10-4.19 — conversation command registration."""

    EXPECTED_CONVERSATION_COMMANDS = {
        "compact": CommandPriority.LOW,
        "new": CommandPriority.NORMAL,
        "clear": CommandPriority.NORMAL,
        "history": CommandPriority.LOW,
        "compact_str": CommandPriority.LOW,
        "await_summary": CommandPriority.LOW,
        "message": CommandPriority.LOW,
        "dump_history": CommandPriority.LOW,
        "load_history": CommandPriority.LOW,
    }

    def test_all_conversation_commands_registered(self):
        """All 9 conversation commands should be registered on init."""
        router = CommandRouter()
        cmds = router.get_registered_commands()
        for name in self.EXPECTED_CONVERSATION_COMMANDS:
            assert name in cmds, f"/{name} should be registered"

    def test_conversation_command_priorities(self):
        """Each conversation command has the correct priority."""
        router = CommandRouter()
        for name, expected_prio in self.EXPECTED_CONVERSATION_COMMANDS.items():
            assert router.get_priority(name) == expected_prio, (
                f"/{name} priority mismatch: expected {expected_prio}, "
                f"got {router.get_priority(name)}"
            )

    def test_total_builtin_count(self):
        """All 16 built-in commands + /daemon meta = 17 registered."""
        router = CommandRouter()
        cmds = router.get_registered_commands()
        # 7 daemon + 1 daemon-meta + 9 conversation = 17
        assert len(cmds) == 17, f"Expected 17 commands, got {len(cmds)}: {cmds}"

    @pytest.mark.asyncio
    async def test_conversation_command_without_runner_returns_error(self):
        """Validates: conversation commands require an active session."""
        router = CommandRouter()  # no runner
        ctx = _make_context("compact", raw_query="/compact")
        result = await router.dispatch(ctx)
        assert isinstance(result, Msg)
        assert "require an active session" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_conversation_command_with_runner_calls_handler(self):
        """Validates: Req 3.10, 4.10 — conversation command builds context and executes."""
        from unittest.mock import AsyncMock, patch

        # Mock runner with memory_manager and session
        runner = MagicMock()
        memory = MagicMock()
        memory.load_state_dict = MagicMock()
        memory.state_dict = MagicMock(return_value={"content": []})
        runner.memory_manager.get_in_memory_memory.return_value = memory

        session_state = {"agent": {"memory": {"content": []}}}
        runner.session.get_session_state_dict = AsyncMock(
            return_value=session_state,
        )
        runner.session.update_session_state = AsyncMock()

        expected_msg = Msg(
            name="Friday",
            role="assistant",
            content=[{"type": "text", "text": "History Cleared!"}],
        )

        router = CommandRouter(runner=runner)
        ctx = _make_context("clear", raw_query="/clear", runner=runner)

        with patch(
            "copaw.app.runner.command_router.ConvCommandHandler"
        ) as MockHandler:
            instance = MockHandler.return_value
            instance.handle_conversation_command = AsyncMock(
                return_value=expected_msg,
            )
            result = await router.dispatch(ctx)

        assert result is expected_msg
        runner.session.get_session_state_dict.assert_awaited_once()
        runner.session.update_session_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_conversation_command_persists_memory_state(self):
        """Validates: Req 4.19 — memory state persisted after command."""
        from unittest.mock import AsyncMock, patch

        runner = MagicMock()
        memory = MagicMock()
        memory.load_state_dict = MagicMock()
        memory.state_dict = MagicMock(return_value={"content": [], "summary": "x"})
        runner.memory_manager.get_in_memory_memory.return_value = memory

        runner.session.get_session_state_dict = AsyncMock(
            return_value={"agent": {"memory": {}}},
        )
        runner.session.update_session_state = AsyncMock()

        router = CommandRouter(runner=runner)
        ctx = _make_context(
            "new",
            raw_query="/new",
            runner=runner,
            session_id="s1",
            user_id="u1",
        )

        with patch(
            "copaw.app.runner.command_router.ConvCommandHandler"
        ) as MockHandler:
            instance = MockHandler.return_value
            instance.handle_conversation_command = AsyncMock(
                return_value=Msg(name="Friday", role="assistant", content=[]),
            )
            await router.dispatch(ctx)

        runner.session.update_session_state.assert_awaited_once_with(
            session_id="s1",
            key="agent.memory",
            value={"content": [], "summary": "x"},
            user_id="u1",
        )

    @pytest.mark.asyncio
    async def test_conversation_command_handler_exception_caught(self):
        """Validates: Req 4.20 — RuntimeError in handler returns error Msg."""
        from unittest.mock import AsyncMock, patch

        runner = MagicMock()
        memory = MagicMock()
        memory.load_state_dict = MagicMock()
        memory.state_dict = MagicMock(return_value={})
        runner.memory_manager.get_in_memory_memory.return_value = memory

        runner.session.get_session_state_dict = AsyncMock(
            return_value={"agent": {"memory": {}}},
        )
        runner.session.update_session_state = AsyncMock()

        router = CommandRouter(runner=runner)
        ctx = _make_context("compact", raw_query="/compact", runner=runner)

        with patch(
            "copaw.app.runner.command_router.ConvCommandHandler"
        ) as MockHandler:
            instance = MockHandler.return_value
            instance.handle_conversation_command = AsyncMock(
                side_effect=RuntimeError("memory load failed"),
            )
            result = await router.dispatch(ctx)

        assert isinstance(result, Msg)
        assert "memory load failed" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_conversation_command_skips_persist_without_ids(self):
        """Validates: skips session_state update when session_id or user_id missing."""
        from unittest.mock import AsyncMock, patch

        runner = MagicMock()
        memory = MagicMock()
        memory.load_state_dict = MagicMock()
        memory.state_dict = MagicMock(return_value={})
        runner.memory_manager.get_in_memory_memory.return_value = memory

        runner.session.get_session_state_dict = AsyncMock(
            return_value={"agent": {"memory": {}}},
        )
        runner.session.update_session_state = AsyncMock()

        router = CommandRouter(runner=runner)
        ctx = _make_context(
            "history",
            raw_query="/history",
            runner=runner,
            session_id="",
            user_id="",
        )

        with patch(
            "copaw.app.runner.command_router.ConvCommandHandler"
        ) as MockHandler:
            instance = MockHandler.return_value
            instance.handle_conversation_command = AsyncMock(
                return_value=Msg(name="Friday", role="assistant", content=[]),
            )
            await router.dispatch(ctx)

        runner.session.update_session_state.assert_not_awaited()


# ------------------------------------------------------------------
# /stop — ChannelManager cancel path (Task: P1 coverage gap)
# ------------------------------------------------------------------
class TestStopChannelManagerCancelPath:
    """Validates: /stop cancels active process task via ChannelManager."""

    @pytest.mark.asyncio
    async def test_stop_cancels_active_process_task(self):
        """When TaskTracker is absent, /stop cancels via _active_process_tasks."""
        import asyncio

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-1")

        # Simulate an active (not-done) task
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        active_tasks = {("ch-1", "key-1"): future}

        cm = MagicMock()
        cm._active_process_tasks = active_tasks

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload={"x": 1},
            task_tracker=None,
        )
        result = await router.dispatch(ctx)
        assert "Task stopped" in result.content[0]["text"]
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_stop_skips_done_task_in_active_tasks(self):
        """When the active task is already done, /stop reports no running task."""
        import asyncio

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-2")

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        future.set_result("already done")
        active_tasks = {("ch-1", "key-2"): future}

        cm = MagicMock()
        cm._active_process_tasks = active_tasks

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload=None,
            task_tracker=None,
        )
        result = await router.dispatch(ctx)
        assert "No running task" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_stop_no_matching_key_in_active_tasks(self):
        """When no active task matches the debounce key, reports no running task."""
        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-miss")

        cm = MagicMock()
        cm._active_process_tasks = {}

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload=None,
            task_tracker=None,
        )
        result = await router.dispatch(ctx)
        assert "No running task" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_stop_task_tracker_takes_precedence(self):
        """TaskTracker path is tried first; ChannelManager path is skipped."""
        import asyncio

        async def _mock_stop(run_key):
            return True

        tt = MagicMock()
        tt.request_stop = _mock_stop

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-1")

        # Active task exists but should NOT be cancelled
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        active_tasks = {("ch-1", "key-1"): future}

        cm = MagicMock()
        cm._active_process_tasks = active_tasks

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload=None,
            task_tracker=tt,
        )
        result = await router.dispatch(ctx)
        assert "Task stopped" in result.content[0]["text"]
        # The future should NOT have been cancelled (TaskTracker handled it)
        assert not future.cancelled()

    @pytest.mark.asyncio
    async def test_stop_falls_through_to_channel_manager(self):
        """When TaskTracker returns False, falls through to ChannelManager path."""
        import asyncio

        async def _mock_stop(run_key):
            return False

        tt = MagicMock()
        tt.request_stop = _mock_stop

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-1")

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        active_tasks = {("ch-1", "key-1"): future}

        cm = MagicMock()
        cm._active_process_tasks = active_tasks

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload=None,
            task_tracker=tt,
        )
        result = await router.dispatch(ctx)
        assert "Task stopped" in result.content[0]["text"]
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_stop_both_paths_fail(self):
        """When both TaskTracker and ChannelManager have nothing, reports no task."""
        async def _mock_stop(run_key):
            return False

        tt = MagicMock()
        tt.request_stop = _mock_stop

        channel = MagicMock()
        channel.get_debounce_key = MagicMock(return_value="key-1")

        cm = MagicMock()
        cm._active_process_tasks = {}

        router = CommandRouter(channel_manager=cm)
        ctx = _make_context(
            "stop",
            channel=channel,
            channel_id="ch-1",
            payload=None,
            task_tracker=tt,
        )
        result = await router.dispatch(ctx)
        assert "No running task" in result.content[0]["text"]
