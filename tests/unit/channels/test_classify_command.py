# -*- coding: utf-8 -*-
"""Unit tests for ChannelManager._classify_command."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from copaw.app.channels.manager import (
    ChannelManager,
    _extract_text_from_payload,
)
from copaw.app.runner.command_router import CommandRouter


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeContent:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeInput:
    content: list[Any] | None = None


@dataclass
class _FakeRequest:
    input: list[Any] | None = None


class _FakeChannel:
    """Minimal BaseChannel stub for classify_command tests."""

    channel = "test"

    def _payload_to_request(self, payload: Any) -> _FakeRequest:
        # payload is just the text string in our tests
        if isinstance(payload, str):
            return _FakeRequest(
                input=[
                    _FakeInput(
                        content=[_FakeContent(type="text", text=payload)]
                    )
                ],
            )
        if isinstance(payload, dict) and "text" in payload:
            return _FakeRequest(
                input=[
                    _FakeInput(
                        content=[
                            _FakeContent(type="text", text=payload["text"])
                        ]
                    )
                ],
            )
        # Simulate extraction failure for non-string/dict payloads
        raise ValueError("bad payload")

    def get_debounce_key(self, payload: Any) -> str:
        return "key"


def _make_manager_with_router() -> tuple[ChannelManager, _FakeChannel]:
    """Create a ChannelManager with a CommandRouter attached."""
    ch = _FakeChannel()
    mgr = ChannelManager(channels=[])
    router = CommandRouter(task_tracker=None, runner=None)
    mgr.set_command_router(router)
    return mgr, ch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClassifyCommandDaemon:
    """Daemon commands recognized via parse_daemon_query."""

    @pytest.mark.parametrize(
        "text, expected_cmd",
        [
            ("/stop", "stop"),
            ("/status", "status"),
            ("/restart", "restart"),
            ("/reload-config", "reload-config"),
            ("/version", "version"),
            ("/logs", "logs"),
            ("/approve", "approve"),
        ],
    )
    def test_short_daemon_commands(self, text: str, expected_cmd: str) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, text)
        assert result is not None
        cmd_name, _args = result
        assert cmd_name == expected_cmd

    def test_daemon_long_form(self) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, "/daemon status")
        assert result is not None
        # parse_daemon_query resolves /daemon status -> ("status", [])
        # "status" is registered, so it should match
        assert result[0] == "status"

    def test_daemon_long_form_with_args(self) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, "/logs 200")
        assert result is not None
        assert result[0] == "logs"
        assert result[1] == ["200"]


class TestClassifyCommandConversation:
    """Conversation commands recognized via SYSTEM_COMMANDS."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "compact",
            "new",
            "clear",
            "history",
            "compact_str",
            "await_summary",
            "message",
            "dump_history",
            "load_history",
        ],
    )
    def test_conversation_commands(self, cmd: str) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, f"/{cmd}")
        assert result is not None
        assert result[0] == cmd

    def test_conversation_command_with_args(self) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, "/message hello world")
        assert result is not None
        assert result[0] == "message"
        assert result[1] == ["hello", "world"]


class TestClassifyCommandNormal:
    """Normal messages should return None."""

    def test_plain_text(self) -> None:
        mgr, ch = _make_manager_with_router()
        assert mgr._classify_command(ch, "hello world") is None

    def test_empty_string(self) -> None:
        mgr, ch = _make_manager_with_router()
        assert mgr._classify_command(ch, "") is None

    def test_unregistered_slash_command(self) -> None:
        mgr, ch = _make_manager_with_router()
        assert mgr._classify_command(ch, "/nonexistent") is None

    def test_no_command_router(self) -> None:
        ch = _FakeChannel()
        mgr = ChannelManager(channels=[])
        # No router set
        assert mgr._classify_command(ch, "/stop") is None


class TestClassifyCommandEdgeCases:
    """Edge cases: payload extraction failure, whitespace, etc."""

    def test_payload_extraction_failure_returns_none(self) -> None:
        mgr, ch = _make_manager_with_router()
        # Pass a payload type that causes extraction to fail
        assert mgr._classify_command(ch, 12345) is None

    def test_whitespace_around_command(self) -> None:
        mgr, ch = _make_manager_with_router()
        result = mgr._classify_command(ch, "  /stop  ")
        assert result is not None
        assert result[0] == "stop"

    def test_dynamic_registration(self) -> None:
        """Newly registered commands are immediately recognized."""
        mgr, ch = _make_manager_with_router()
        # /pause is not registered yet
        assert mgr._classify_command(ch, "/pause") is None

        # Register it dynamically
        async def _noop(ctx):
            pass

        mgr._command_router.register_command("pause", _noop)
        # Now it should be recognized via the generic fallback
        result = mgr._classify_command(ch, "/pause")
        assert result is not None
        assert result[0] == "pause"
        assert result[1] == []
