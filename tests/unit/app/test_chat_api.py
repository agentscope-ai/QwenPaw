# -*- coding: utf-8 -*-
"""Tests for chat API resilience with malformed session memory."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from copaw.app.runner.api import get_chat
from copaw.app.runner.models import ChatSpec


def test_get_chat_returns_empty_messages_when_memory_missing():
    """Missing memory state should not crash chat history loading."""
    mgr = SimpleNamespace(
        get_chat=AsyncMock(
            return_value=ChatSpec(
                id="chat-1",
                name="Test Chat",
                session_id="session-1",
                user_id="default",
                channel="console",
            ),
        ),
    )
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"name": "Friday"}},
        ),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="idle")),
    )

    history = asyncio.run(
        get_chat(
            "chat-1",
            mgr=mgr,
            session=session,
            workspace=workspace,
        ),
    )

    assert history.status == "idle"
    assert history.messages == []


def test_get_chat_returns_empty_messages_when_memory_is_malformed():
    """Malformed memory payloads should degrade to empty history."""
    mgr = SimpleNamespace(
        get_chat=AsyncMock(
            return_value=ChatSpec(
                id="chat-2",
                name="Test Chat",
                session_id="session-2",
                user_id="default",
                channel="console",
            ),
        ),
    )
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(
            return_value={"agent": {"memory": []}},
        ),
    )
    workspace = SimpleNamespace(
        task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="idle")),
    )

    history = asyncio.run(
        get_chat(
            "chat-2",
            mgr=mgr,
            session=session,
            workspace=workspace,
        ),
    )

    assert history.status == "idle"
    assert history.messages == []
