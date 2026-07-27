# -*- coding: utf-8 -*-
"""Tests for the lightweight ``GET /chats/{chat_id}/status`` endpoint.

The endpoint must report idle/running via the task tracker without
loading any session state, and 404 for unknown chats.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.chats.api import (
    get_chat_manager,
    get_session,
    get_workspace,
    router,
)


@pytest.fixture
def chat_manager() -> SimpleNamespace:
    return SimpleNamespace(
        get_chat=AsyncMock(return_value=SimpleNamespace(id="chat-1")),
    )


@pytest.fixture
def workspace() -> SimpleNamespace:
    return SimpleNamespace(
        task_tracker=SimpleNamespace(
            get_status=AsyncMock(return_value="idle"),
        ),
        session=SimpleNamespace(
            get_session_state_dict=AsyncMock(return_value={}),
        ),
    )


@pytest.fixture
def client(
    chat_manager: SimpleNamespace,
    workspace: SimpleNamespace,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_manager] = lambda: chat_manager
    app.dependency_overrides[get_workspace] = lambda: workspace
    app.dependency_overrides[get_session] = lambda: workspace.session
    return TestClient(app)


def test_status_returns_idle(client: TestClient) -> None:
    res = client.get("/chats/chat-1/status")

    assert res.status_code == 200
    assert res.json() == {"id": "chat-1", "status": "idle"}


def test_status_returns_running(
    client: TestClient,
    workspace: SimpleNamespace,
) -> None:
    workspace.task_tracker.get_status = AsyncMock(return_value="running")

    res = client.get("/chats/chat-1/status")

    assert res.status_code == 200
    assert res.json() == {"id": "chat-1", "status": "running"}


def test_status_404_for_unknown_chat(
    client: TestClient,
    chat_manager: SimpleNamespace,
) -> None:
    chat_manager.get_chat = AsyncMock(return_value=None)

    res = client.get("/chats/missing/status")

    assert res.status_code == 404


def test_status_does_not_touch_session_state(
    client: TestClient,
    workspace: SimpleNamespace,
) -> None:
    """The whole point of the endpoint: no session state deserialization."""
    res = client.get("/chats/chat-1/status")

    assert res.status_code == 200
    workspace.session.get_session_state_dict.assert_not_called()
