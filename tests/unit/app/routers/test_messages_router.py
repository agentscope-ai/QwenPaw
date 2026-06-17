# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.messages``.

These tests use FastAPI's ``TestClient`` against a synthetic app whose
``app.state.multi_agent_manager`` is a MagicMock — the shared mocks
come from ``conftest.py``; the messages-only ``app`` fixture lives
here so other ``test_xxx_router.py`` files are not tempted to inherit
it.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope_runtime.engine.schemas.exception import AppBaseException


@pytest.fixture
def app(manager_mock) -> FastAPI:
    """A fresh FastAPI app mounting only the messages router under /api."""
    from qwenpaw.app.routers.messages import router as messages_router

    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(messages_router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


_DEFAULT_PAYLOAD = {
    "channel": "console",
    "target_user": "alice",
    "target_session": "sess-1",
    "text": "hello",
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_send_message_success_uses_default_agent_id(
    client,
    manager_mock,
    workspace_mock,
):
    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "success": True,
        "message": "Message sent successfully to console",
    }
    # No X-Agent-Id header → fallback to ``default``.
    manager_mock.get_agent.assert_awaited_once_with("default")
    workspace_mock.channel_manager.send_text.assert_awaited_once()
    call_kwargs = workspace_mock.channel_manager.send_text.await_args.kwargs
    assert call_kwargs["channel"] == "console"
    assert call_kwargs["user_id"] == "alice"
    assert call_kwargs["session_id"] == "sess-1"
    assert call_kwargs["text"] == "hello"
    assert call_kwargs["meta"] == {"_api_send": True}


def test_send_message_passes_x_agent_id_into_meta(
    client,
    manager_mock,
    workspace_mock,
):
    response = client.post(
        "/api/messages/send",
        json=_DEFAULT_PAYLOAD,
        headers={"X-Agent-Id": "my_bot"},
    )

    assert response.status_code == 200
    manager_mock.get_agent.assert_awaited_once_with("my_bot")
    meta = workspace_mock.channel_manager.send_text.await_args.kwargs["meta"]
    assert meta == {"_api_send": True, "agent_id": "my_bot"}


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_send_message_returns_404_when_agent_missing(client, manager_mock):
    manager_mock.get_agent.side_effect = ValueError("no such agent")

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 404
    assert "Agent not found" in response.json()["detail"]


def test_send_message_returns_404_when_app_base_exception_for_agent(
    client,
    manager_mock,
):
    manager_mock.get_agent.side_effect = AppBaseException(
        status=404,
        code="agent_not_found",
        message="nope",
    )

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 404


def test_send_message_returns_500_when_workspace_lookup_raises(
    client,
    manager_mock,
):
    manager_mock.get_agent.side_effect = RuntimeError("boom")

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 500
    assert "Failed to get agent workspace" in response.json()["detail"]


def test_send_message_returns_500_when_channel_manager_missing(
    client,
    workspace_mock,
):
    workspace_mock.channel_manager = None

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 500
    assert "Channel manager not initialized" in response.json()["detail"]


def test_send_message_returns_404_when_channel_unknown(
    client,
    workspace_mock,
):
    workspace_mock.channel_manager.send_text = AsyncMock(
        side_effect=KeyError("console"),
    )

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 404
    assert "Channel not found" in response.json()["detail"]


def test_send_message_returns_500_when_send_text_raises_unexpected(
    client,
    workspace_mock,
):
    workspace_mock.channel_manager.send_text = AsyncMock(
        side_effect=RuntimeError("network down"),
    )

    response = client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 500
    assert "Failed to send message" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Validation: pydantic catches missing fields with 422 (FastAPI default).
# ---------------------------------------------------------------------------


def test_send_message_validation_error_on_missing_field(client):
    bad = {"channel": "console", "target_user": "u", "text": "hi"}
    # No ``target_session`` → 422.

    response = client.post("/api/messages/send", json=bad)

    assert response.status_code == 422


def test_send_message_returns_500_when_manager_not_in_state():
    # Build an app WITHOUT setting app.state.multi_agent_manager so the
    # ``_get_multi_agent_manager`` guard raises 500.
    from qwenpaw.app.routers.messages import router

    bare_app = FastAPI()
    bare_app.include_router(router, prefix="/api")
    local_client = TestClient(bare_app)

    response = local_client.post("/api/messages/send", json=_DEFAULT_PAYLOAD)

    assert response.status_code == 500
    assert "MultiAgentManager not initialized" in response.json()["detail"]
