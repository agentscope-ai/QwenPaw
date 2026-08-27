# -*- coding: utf-8 -*-
"""Route-level tests for ``GET /api/chats/{chat_id}`` pagination.

Exercises the real endpoint (dependency overrides for the workspace
only) with a session state built from genuine AgentScope messages, so
the full path — state → ``agentscope_msg_to_message`` →
``apply_history_window`` → ``ChatHistory`` — is covered.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.chats import api as chats_api
from qwenpaw.app.chats.models import ChatSpec

CHAT_ID = "pagination-chat-1"
SESSION_ID = "console:pagination-user"
USER_ID = "pagination-user"
CHANNEL = "console"


def build_messages(count: int) -> list[Msg]:
    """Alternating user/assistant messages with distinct ids and texts."""
    messages = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            Msg(
                name=USER_ID if role == "user" else "agent",
                content=[TextBlock(type="text", text=f"message-{index}")],
                role=role,
                id=f"scoped-msg-{index}",
            ),
        )
    return messages


@pytest.fixture
def chat_workspace():
    """Workspace mock backing the chats router dependencies."""
    chat = ChatSpec(
        id=CHAT_ID,
        name="Pagination chat",
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    workspace = MagicMock(name="workspace")
    workspace.chat_manager = MagicMock(name="ChatManager")
    workspace.chat_manager.get_chat = AsyncMock(return_value=chat)
    workspace.task_tracker.get_status = AsyncMock(return_value="idle")
    workspace.config.backend = "qwenpaw"

    session = MagicMock(name="SafeJSONSession")
    session.get_session_state_dict = AsyncMock(
        return_value={
            "agent": {
                "state": AgentState(context=build_messages(6)).model_dump()
            }
        },
    )
    workspace.session = session
    return workspace


@pytest.fixture
def client(chat_workspace) -> TestClient:
    """FastAPI app mounting only the chats router, deps overridden."""
    application = FastAPI()
    application.include_router(chats_api.router, prefix="/api")

    async def _override_workspace():
        return chat_workspace

    def _override_manager():
        return chat_workspace.chat_manager

    def _override_session():
        return chat_workspace.session

    # All three must be overridden: get_chat_manager / get_session call
    # the module-level get_workspace directly, so the FastAPI override
    # on get_workspace alone does not reach them.
    application.dependency_overrides[chats_api.get_workspace] = (
        _override_workspace
    )
    application.dependency_overrides[chats_api.get_chat_manager] = (
        _override_manager
    )
    application.dependency_overrides[chats_api.get_session] = _override_session
    return TestClient(application)


def text_of(message: dict) -> str:
    return "".join(
        block.get("text", "")
        for block in message.get("content", [])
        if isinstance(block, dict)
    )


def test_without_params_returns_full_history(client):
    resp = client.get(f"/api/chats/{CHAT_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["messages"]) == 6
    assert body["total"] == 6
    assert body["has_more"] is False
    assert body["status"] == "idle"


def test_limit_returns_most_recent_window(client):
    resp = client.get(f"/api/chats/{CHAT_ID}?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert [text_of(m) for m in body["messages"]] == [
        "message-4",
        "message-5",
    ]
    assert body["total"] == 6
    assert body["has_more"] is True


def test_limit_covering_everything_disables_has_more(client):
    resp = client.get(f"/api/chats/{CHAT_ID}?limit=6")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["messages"]) == 6
    assert body["has_more"] is False


def test_before_cursor_pages_older_history(client):
    full = client.get(f"/api/chats/{CHAT_ID}").json()
    # Cursor on the oldest message of the first window: message-4's
    # source Msg id is exposed via metadata.original_id.
    oldest_in_window = full["messages"][4]
    cursor = oldest_in_window["metadata"]["original_id"]
    assert cursor == "scoped-msg-4"

    resp = client.get(f"/api/chats/{CHAT_ID}?limit=2&before={cursor}")
    assert resp.status_code == 200
    body = resp.json()
    assert [text_of(m) for m in body["messages"]] == [
        "message-2",
        "message-3",
    ]
    assert body["total"] == 6
    assert body["has_more"] is True


def test_before_cursor_on_oldest_message_returns_empty(client):
    resp = client.get(f"/api/chats/{CHAT_ID}?limit=10&before=scoped-msg-0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["messages"] == []
    assert body["total"] == 6
    assert body["has_more"] is False


def test_stale_cursor_falls_back_to_limit_window(client):
    resp = client.get(f"/api/chats/{CHAT_ID}?limit=3&before=no-such-cursor")
    assert resp.status_code == 200
    body = resp.json()
    assert [text_of(m) for m in body["messages"]] == [
        "message-3",
        "message-4",
        "message-5",
    ]
    assert body["has_more"] is True


def test_invalid_limit_is_rejected(client):
    resp = client.get(f"/api/chats/{CHAT_ID}?limit=-1")
    assert resp.status_code == 422
