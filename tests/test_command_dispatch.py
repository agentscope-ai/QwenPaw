# -*- coding: utf-8 -*-
"""Tests for command dispatch and daemon commands (sync helpers)."""
import asyncio

from copaw.agents.command_handler import (
    CommandHandler,
    ConversationCommandHandlerMixin,
)
from copaw.app.runner.command_dispatch import (
    _get_last_user_text,
    _is_command,
    _is_conversation_command,
)
from copaw.app.runner.daemon_commands import (
    DaemonContext,
    parse_daemon_query,
    run_daemon_logs,
    run_daemon_restart,
    run_daemon_status,
    run_daemon_version,
)


def test_conversation_commands_set() -> None:
    """Conversation command set is unchanged."""
    assert ConversationCommandHandlerMixin.SYSTEM_COMMANDS == (
        CommandHandler.SYSTEM_COMMANDS
    )
    assert CommandHandler.SYSTEM_COMMANDS == frozenset(
        {
            "compact",
            "new",
            "clear",
            "history",
            "compact_str",
            "await_summary",
        },
    )


def test_is_conversation_command() -> None:
    """Conversation commands are detected."""
    assert _is_conversation_command("/compact") is True
    assert _is_conversation_command("/new") is True
    assert _is_conversation_command("/unknown") is False
    assert _is_conversation_command("hello") is False
    assert _is_conversation_command(None) is False


def test_is_command_daemon_and_short() -> None:
    """Daemon and short names are commands."""
    assert _is_command("/daemon status") is True
    assert _is_command("/restart") is True
    assert _is_command("/status") is True
    assert _is_command("/daemon logs") is True
    assert _is_command("/compact") is True
    assert _is_command("hello") is False


def test_get_last_user_text() -> None:
    """Last user text is extracted from msgs."""

    class MsgWithText:
        def get_text_content(self) -> str:
            return "/daemon status"

    assert _get_last_user_text([MsgWithText()]) == "/daemon status"
    assert _get_last_user_text([]) is None
    assert _get_last_user_text(None) is None


def test_parse_daemon_query() -> None:
    """Daemon query parsing."""
    assert parse_daemon_query("/daemon status") == ("status", [])
    assert parse_daemon_query("/daemon restart") == ("restart", [])
    assert parse_daemon_query("/restart") == ("restart", [])
    assert parse_daemon_query("/status") == ("status", [])
    assert parse_daemon_query("/daemon logs 50") == ("logs", ["50"])
    assert parse_daemon_query("/daemon version") == ("version", [])
    assert parse_daemon_query("/compact") is None
    assert parse_daemon_query("hello") is None


def test_run_daemon_status() -> None:
    """run_daemon_status returns string with working dir."""
    ctx = DaemonContext()
    out = run_daemon_status(ctx)
    assert "Working dir" in out
    assert "Config" in out or "Memory" in out


def test_run_daemon_version() -> None:
    """run_daemon_version returns string with version."""
    ctx = DaemonContext()
    out = run_daemon_version(ctx)
    assert "version" in out.lower() or "Version" in out
    assert "copaw.log" in out


def test_run_daemon_restart_no_callback() -> None:
    """run_daemon_restart without callback returns instructions."""
    ctx = DaemonContext(restart_callback=None)
    out = asyncio.run(run_daemon_restart(ctx))
    assert "restart" in out.lower() or "systemd" in out.lower()


def test_run_daemon_logs_missing_file() -> None:
    """run_daemon_logs handles missing file."""
    ctx = DaemonContext()
    out = run_daemon_logs(ctx, lines=5)
    assert "last" in out.lower() or "log" in out.lower()
    assert "not found" in out or "empty" in out or "(" in out


async def test_daemon_restart_with_callback_returns_completed() -> None:
    """run_daemon_restart with a no-op callback returns completion text.

    When _do_restart_services excludes the restart-requester task (via
    restart_requester_task), the callback runs to completion and
    run_daemon_restart returns \"Restart completed\". This test verifies
    the daemon layer; full flow (run_command_path hint then completion)
    is covered by integration when the requester task is not cancelled.
    """

    async def noop_restart() -> None:
        await asyncio.sleep(0)

    ctx = DaemonContext(restart_callback=noop_restart)
    out = await run_daemon_restart(ctx)
    assert (
        "completed" in out.lower() or "完成" in out
    ), f"Expected completion message, got: {out[:200]}"
