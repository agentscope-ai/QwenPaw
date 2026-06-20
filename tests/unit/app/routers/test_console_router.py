# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.console import router as console_router


@pytest.fixture
def app(manager_mock, workspace_mock) -> FastAPI:
    """A fresh FastAPI app mounting only the console router under /api."""
    # Setup workspace dependencies
    workspace_mock.task_tracker = MagicMock(name="TaskTracker")
    workspace_mock.chat_manager = MagicMock(name="ChatManager")
    workspace_mock.channel_manager = MagicMock(name="ChannelManager")

    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(console_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def setup_console_chat(workspace_mock):
    # Mock chat
    mock_chat = MagicMock(name="ChatSpec")
    mock_chat.id = "chat-123"
    mock_chat.name = "My Chat"
    workspace_mock.chat_manager.get_or_create_chat = AsyncMock(
        return_value=mock_chat,
    )

    # Mock console channel
    mock_channel = MagicMock(name="ConsoleChannel")
    mock_channel.resolve_session_id = MagicMock(return_value="sess-123")
    mock_channel.stream_one = AsyncMock()
    workspace_mock.channel_manager.get_channel = AsyncMock(
        return_value=mock_channel,
    )

    return mock_channel, mock_chat


_CHAT_PAYLOAD = {
    "input": [
        {
            "content": [
                {"type": "text", "text": "hello"},
            ],
        },
    ],
    "user_id": "test-user",
    "session_id": "test-session",
}


def test_console_chat_when_idle(client, workspace_mock, setup_console_chat):
    """If agent is not busy, console/chat starts a new stream (status 200)."""
    # Mock task tracker behavior
    tracker = workspace_mock.task_tracker
    tracker.has_active_tasks = AsyncMock(return_value=False)

    # Mock attach_or_start
    queue = asyncio.Queue()
    tracker.attach_or_start = AsyncMock(return_value=(queue, True))

    async def mock_stream_from_queue(*args, **kwargs):
        yield "data: {}\n\n"

    tracker.stream_from_queue = mock_stream_from_queue

    response = client.post("/api/console/chat", json=_CHAT_PAYLOAD)

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    tracker.has_active_tasks.assert_awaited_once()
    tracker.attach_or_start.assert_awaited_once()


def test_console_chat_when_busy_returns_503(
    client,
    workspace_mock,
    setup_console_chat,
):
    """If agent is busy, console/chat immediately returns HTTP 503."""
    tracker = workspace_mock.task_tracker
    tracker.has_active_tasks = AsyncMock(return_value=True)

    response = client.post("/api/console/chat", json=_CHAT_PAYLOAD)

    assert response.status_code == 503
    assert (
        response.json()["detail"] == "Agent is busy processing another request"
    )
    tracker.has_active_tasks.assert_awaited_once()
    tracker.attach_or_start.assert_not_called()
