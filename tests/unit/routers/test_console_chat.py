# -*- coding: utf-8 -*-
"""Unit tests for console chat router edge cases."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import console as console_router


@pytest.mark.asyncio
async def test_console_chat_reconnect_without_active_stream_returns_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnect must fail loudly when the original stream is gone."""

    fake_console_channel = MagicMock()
    fake_console_channel.resolve_session_id.return_value = "session-1"
    fake_console_channel.stream_one = MagicMock()

    fake_tracker = SimpleNamespace(
        attach=AsyncMock(return_value=None),
        attach_or_start=AsyncMock(),
    )
    fake_chat = SimpleNamespace(id="chat-1", name="New Chat")
    fake_chat_manager = SimpleNamespace(
        get_or_create_chat=AsyncMock(return_value=fake_chat),
    )
    fake_workspace = SimpleNamespace(
        channel_manager=SimpleNamespace(
            get_channel=AsyncMock(return_value=fake_console_channel),
        ),
        chat_manager=fake_chat_manager,
        task_tracker=fake_tracker,
    )

    async def fake_get_agent_for_request(_request):
        return fake_workspace

    monkeypatch.setattr(
        console_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await console_router.post_console_chat(
            {
                "reconnect": True,
                "channel": "console",
                "user_id": "user-1",
                "session_id": "session-1",
                "input": [],
            },
            object(),
        )

    assert exc_info.value.status_code == 409
    assert "No active console chat stream found to reconnect" in str(
        exc_info.value.detail,
    )
    fake_tracker.attach.assert_awaited_once_with("chat-1")
    fake_tracker.attach_or_start.assert_not_awaited()
