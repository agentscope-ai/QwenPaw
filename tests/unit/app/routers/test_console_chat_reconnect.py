# -*- coding: utf-8 -*-
"""Unit tests for the ``POST /console/chat`` reconnect branch.

When a client reconnects to a chat whose run already finished (the
tracker cleaned it up between the status poll and the reconnect), the
endpoint must answer with an immediately-terminated SSE stream so the
client's stream reader completes normally and falls back to loading the
persisted history. Returning ``None`` produced a JSON ``null`` body,
which left the chat UI blank until a manual refresh.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app.routers.console import _extract_session_and_payload
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent


@pytest.fixture
def console_workspace(workspace_mock):
    """Workspace with a console channel, chat manager, and empty tracker."""
    console_channel = MagicMock(name="ConsoleChannel")
    console_channel.resolve_session_id = MagicMock(
        return_value="console:default",
    )
    # stream_one must never run for a reconnect: sentinel async generator
    # that records invocation.
    stream_calls: list = []

    async def _stream_one(payload):
        stream_calls.append(payload)
        yield "data: should-not-happen\n\n"

    console_channel.stream_one = _stream_one
    console_channel.stream_calls = stream_calls
    workspace_mock.channel_manager.get_channel = AsyncMock(
        return_value=console_channel,
    )
    workspace_mock.console_channel = console_channel

    chat = MagicMock(name="ChatSpec")
    chat.id = "chat-1"
    chat.name = "New Chat"
    workspace_mock.chat_manager = MagicMock(name="ChatManager")
    workspace_mock.chat_manager.get_or_create_chat = AsyncMock(
        return_value=chat,
    )

    # Real tracker with no active run: attach() returns None.
    workspace_mock.task_tracker = TaskTracker()
    return workspace_mock


@pytest.fixture
def app(manager_mock, console_workspace) -> FastAPI:
    """A fresh FastAPI app mounting only the console router under /api."""
    from qwenpaw.app.routers.console import router as console_router

    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(console_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_reconnect_without_active_run_returns_empty_sse(
    client,
    console_workspace,
):
    response = client.post(
        "/api/console/chat",
        json={
            "reconnect": True,
            "session_id": "console:default",
            "user_id": "default",
            "channel": "console",
        },
    )

    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("text/event-stream")
    assert response.text == ""
    # A reconnect must attach only — never start a fresh run with the
    # (empty) reconnect payload.
    assert console_workspace.console_channel.stream_calls == []


def test_extract_payload_preserves_user_message_metadata():
    payload = _extract_session_and_payload(
        AgentRequest(
            input=[
                Message(
                    role=Role.USER,
                    content=[TextContent(text="continue")],
                    metadata={
                        "qwenpaw_client_message_id": "client-new",
                    },
                ),
            ],
        ),
    )

    assert payload["message_metadata"] == {
        "qwenpaw_client_message_id": "client-new",
    }


@pytest.mark.asyncio
async def test_reconnect_with_active_run_replays_buffer_and_marker(
    app,
    console_workspace,
):
    from starlette.requests import Request
    from qwenpaw.app.routers.console import post_console_chat

    tracker = console_workspace.task_tracker
    release = asyncio.Event()

    async def slow_stream(_payload):
        yield "data: first\n\n"
        await release.wait()

    await tracker.attach_or_start("chat-1", None, slow_stream)
    # Let the producer buffer the first event before reconnecting.
    for _ in range(10):
        await asyncio.sleep(0)

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/console/chat",
            "headers": [],
            "app": app,
        },
    )
    response = await post_console_chat(
        request_data={
            "reconnect": True,
            "session_id": "console:default",
            "user_id": "default",
            "channel": "console",
        },
        request=request,
    )

    received: list[str] = []

    async def _consume() -> None:
        async for chunk in response.body_iterator:
            received.append(chunk)
            # End the producer once the replay part is over.
            if "replay_end" in chunk:
                release.set()

    try:
        # Bounded wait: without the marker the stream never ends —
        # fail fast instead of hanging the test session.
        await asyncio.wait_for(_consume(), timeout=5)
    finally:
        release.set()

    assert received[0] == "data: first\n\n"
    payload = json.loads(received[1][len("data: ") :])
    assert payload == {"type": "replay_end"}
    # No fresh run was started by the reconnect.
    assert console_workspace.console_channel.stream_calls == []


@pytest.mark.asyncio
async def test_new_message_rejects_active_run(
    app,
    console_workspace,
    monkeypatch,
):
    """A non-reconnect payload must not silently attach to an active run."""
    from starlette.requests import Request
    from qwenpaw.app.routers import console

    tracker = console_workspace.task_tracker
    release = asyncio.Event()

    async def slow_stream(_payload):
        await release.wait()
        yield "data: existing\n\n"

    await tracker.attach_or_start("chat-1", None, slow_stream)
    monkeypatch.setattr(
        console,
        "_persist_pending_project_dirs",
        AsyncMock(side_effect=lambda _ws, chat, _payload: chat),
    )

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/console/chat",
            "headers": [],
            "app": app,
        },
    )

    try:
        with pytest.raises(HTTPException) as exc_info:
            await console.post_console_chat(
                request_data={
                    "session_id": "console:default",
                    "user_id": "default",
                    "channel": "console",
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "new message"},
                            ],
                        },
                    ],
                },
                request=request,
            )
    finally:
        release.set()

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "A task is already running for this chat. Wait for it to finish or "
        "use a different session_id."
    )
    assert console_workspace.console_channel.stream_calls == []
