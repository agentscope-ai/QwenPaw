# -*- coding: utf-8 -*-
"""Unit tests verifying Console channel dual-queue integration.

Tests that:
- Command messages (e.g. /stop, /compact) are detected by _classify_command
  and routed through enqueue → CommandQueue path.
- Normal messages bypass _classify_command and go through attach_or_start
  (DataQueue path).
- The SSE response for commands returns {"command": true}.

Validates: Requirements 6.1, 6.2
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


class _FakeConsoleChannel:
    """Minimal ConsoleChannel stub."""

    channel = "console"

    async def stream_one(self, payload):
        yield "data: {}\n\n"

    def _payload_to_request(self, payload: Any) -> _FakeRequest:
        if isinstance(payload, dict) and "content_parts" in payload:
            parts = payload["content_parts"]
            contents = []
            for p in parts:
                if hasattr(p, "text"):
                    contents.append(p)
                elif isinstance(p, dict):
                    contents.append(_FakeContent(text=p.get("text", "")))
                else:
                    contents.append(_FakeContent(text=str(p)))
            return _FakeRequest(input=[_FakeInput(content=contents)])
        if isinstance(payload, str):
            return _FakeRequest(
                input=[_FakeInput(content=[_FakeContent(text=payload)])],
            )
        raise ValueError("bad payload")

    def resolve_session_id(self, sender_id: str, channel_meta: dict) -> str:
        return "test-session"

    def get_debounce_key(self, payload: Any) -> str:
        return "test-key"


def _make_stop_payload() -> dict:
    """Build a native_payload dict whose text is /stop."""
    return {
        "channel_id": "console",
        "sender_id": "user1",
        "content_parts": [_FakeContent(type="text", text="/stop")],
        "meta": {"session_id": "s1", "user_id": "user1"},
    }


def _make_compact_payload() -> dict:
    """Build a native_payload dict whose text is /compact."""
    return {
        "channel_id": "console",
        "sender_id": "user1",
        "content_parts": [_FakeContent(type="text", text="/compact")],
        "meta": {"session_id": "s1", "user_id": "user1"},
    }


def _make_normal_payload(text: str = "hello world") -> dict:
    """Build a native_payload dict with normal text."""
    return {
        "channel_id": "console",
        "sender_id": "user1",
        "content_parts": [_FakeContent(type="text", text=text)],
        "meta": {"session_id": "s1", "user_id": "user1"},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_workspace():
    """Create a mock workspace with channel_manager,
    chat_manager, task_tracker."""
    workspace = MagicMock()

    # Console channel
    console_channel = _FakeConsoleChannel()
    workspace.channel_manager.get_channel = AsyncMock(
        return_value=console_channel
    )

    # _classify_command: default returns None (normal message)
    workspace.channel_manager._classify_command = MagicMock(return_value=None)

    # enqueue
    workspace.channel_manager.enqueue = MagicMock()

    # chat_manager
    fake_chat = MagicMock()
    fake_chat.id = "chat-123"
    workspace.chat_manager.get_or_create_chat = AsyncMock(
        return_value=fake_chat
    )

    # task_tracker
    tracker = MagicMock()
    fake_queue = asyncio.Queue()
    tracker.attach_or_start = AsyncMock(return_value=(fake_queue, None))
    tracker.attach = AsyncMock(return_value=fake_queue)

    async def _fake_stream(q, chat_id):
        yield f"data: {json.dumps({'text': 'hi'})}\n\n"

    tracker.stream_from_queue = MagicMock(side_effect=_fake_stream)
    workspace.task_tracker = tracker

    return workspace


# ---------------------------------------------------------------------------
# Tests: Command messages go through CommandQueue
# ---------------------------------------------------------------------------


class TestCommandRoutedToCommandQueue:
    """Verify command messages are detected and routed via enqueue."""

    async def test_stop_command_classified_and_enqueued(self, mock_workspace):
        """When /stop is sent, _classify_command returns non-None
        and enqueue is called (CommandQueue path)."""
        from copaw.app.routers.console import post_console_chat

        # Make _classify_command return a command classification
        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=("stop", []),
        )

        payload = _make_stop_payload()
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [{"content": [{"type": "text", "text": "/stop"}]}],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                await post_console_chat(request_data, fake_request)

        # enqueue should have been called (command goes to CommandQueue)
        mock_workspace.channel_manager.enqueue.assert_called_once_with(
            "console",
            payload,
        )
        # attach_or_start should NOT have been called
        mock_workspace.task_tracker.attach_or_start.assert_not_called()

    async def test_compact_command_classified_and_enqueued(
        self, mock_workspace
    ):
        """When /compact is sent, _classify_command returns non-None and
        enqueue is called (CommandQueue path)."""
        from copaw.app.routers.console import post_console_chat

        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=("compact", []),
        )

        payload = _make_compact_payload()
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [{"content": [{"type": "text", "text": "/compact"}]}],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                await post_console_chat(request_data, fake_request)

        mock_workspace.channel_manager.enqueue.assert_called_once_with(
            "console",
            payload,
        )
        mock_workspace.task_tracker.attach_or_start.assert_not_called()

    async def test_command_sse_response_contains_command_true(
        self, mock_workspace
    ):
        """SSE response for a command should yield {"command": true}."""
        from copaw.app.routers.console import post_console_chat

        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=("stop", []),
        )

        payload = _make_stop_payload()
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [{"content": [{"type": "text", "text": "/stop"}]}],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                response = await post_console_chat(request_data, fake_request)

        # Collect SSE body
        body_parts = []
        async for chunk in response.body_iterator:
            body_parts.append(chunk)
        body = "".join(body_parts)

        assert "command" in body
        # Parse the SSE data line
        for line in body.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                assert data == {"command": True}


# ---------------------------------------------------------------------------
# Tests: Normal messages go through DataQueue (attach_or_start)
# ---------------------------------------------------------------------------


class TestNormalMessageRoutedToDataQueue:
    """Verify normal messages bypass CommandQueue and use attach_or_start."""

    async def test_normal_message_uses_attach_or_start(self, mock_workspace):
        """When a normal message is sent, _classify_command returns None
        and attach_or_start is called (DataQueue path)."""
        from copaw.app.routers.console import post_console_chat

        # _classify_command returns None for normal messages (default)
        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=None,
        )

        payload = _make_normal_payload("hello world")
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [{"content": [{"type": "text", "text": "hello world"}]}],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                await post_console_chat(request_data, fake_request)

        # attach_or_start should have been called
        mock_workspace.task_tracker.attach_or_start.assert_called_once()
        # enqueue should NOT have been called
        mock_workspace.channel_manager.enqueue.assert_not_called()

    async def test_normal_message_sse_streams_from_queue(self, mock_workspace):
        """Normal message SSE response streams from task_tracker queue."""
        from copaw.app.routers.console import post_console_chat

        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=None,
        )

        payload = _make_normal_payload("tell me a joke")
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [
                {"content": [{"type": "text", "text": "tell me a joke"}]}
            ],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                response = await post_console_chat(request_data, fake_request)

        # Collect SSE body
        body_parts = []
        async for chunk in response.body_iterator:
            body_parts.append(chunk)
        body = "".join(body_parts)

        # Should contain the streamed data, NOT {"command": true}
        assert "command" not in body or '"command": true' not in body


# ---------------------------------------------------------------------------
# Tests: Various command types all go through CommandQueue
# ---------------------------------------------------------------------------


class TestVariousCommandsRouteToCommandQueue:
    """Verify multiple command types are all routed through CommandQueue."""

    @pytest.mark.parametrize(
        "cmd_text, cmd_name",
        [
            ("/stop", "stop"),
            ("/compact", "compact"),
            ("/new", "new"),
            ("/clear", "clear"),
            ("/status", "status"),
            ("/restart", "restart"),
            ("/history", "history"),
            ("/version", "version"),
        ],
    )
    async def test_various_commands_enqueued(
        self,
        mock_workspace,
        cmd_text,
        cmd_name,
    ):
        """All registered commands should be classified and enqueued."""
        from copaw.app.routers.console import post_console_chat

        mock_workspace.channel_manager._classify_command = MagicMock(
            return_value=(cmd_name, []),
        )

        payload = {
            "channel_id": "console",
            "sender_id": "user1",
            "content_parts": [_FakeContent(type="text", text=cmd_text)],
            "meta": {"session_id": "s1", "user_id": "user1"},
        }
        request_data = {
            "channel": "console",
            "user_id": "user1",
            "session_id": "s1",
            "input": [{"content": [{"type": "text", "text": cmd_text}]}],
        }

        with patch(
            "copaw.app.routers.console.get_agent_for_request",
            return_value=mock_workspace,
        ):
            with patch(
                "copaw.app.routers.console._extract_session_and_payload",
                return_value=payload,
            ):
                fake_request = MagicMock()
                response = await post_console_chat(request_data, fake_request)

        mock_workspace.channel_manager.enqueue.assert_called_once()
        mock_workspace.task_tracker.attach_or_start.assert_not_called()

        # SSE should return {"command": true}
        body_parts = []
        async for chunk in response.body_iterator:
            body_parts.append(chunk)
        body = "".join(body_parts)
        for line in body.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
                assert data == {"command": True}
