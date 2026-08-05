# -*- coding: utf-8 -*-
"""API-layer tests for POST /chats/{chat_id}/fork."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from qwenpaw.app.agent_context import get_current_session_id
from qwenpaw.app.chats.api import router
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec, SessionSource
from qwenpaw.app.chats.session import SafeJSONSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_workspace(
    *,
    mgr: ChatManager,
    session: SafeJSONSession,
    status: str = "idle",
):
    """Build a workspace mock wired with the given manager/session/tracker."""
    tracker = MagicMock()
    tracker.get_status = AsyncMock(return_value=status)

    ws = MagicMock()
    ws.chat_manager = mgr
    ws.session = session
    ws.task_tracker = tracker
    return ws


def _make_chat_spec(
    *,
    chat_id: str = "abc-123",
    session_id: str = "console:u1",
    user_id: str = "u1",
    name: str = "Test Chat",
) -> ChatSpec:
    return ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel="console",
        name=name,
        source=SessionSource.chat,
        meta={"existing": "data"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager_mock():
    return AsyncMock(spec=ChatManager)


@pytest.fixture
def session_mock():
    s = AsyncMock(spec=SafeJSONSession)
    s.clone_session_state = AsyncMock()
    s.delete_session_state = AsyncMock(return_value=True)
    return s


@pytest.fixture
def app(manager_mock, session_mock):
    """FastAPI app with overridden dependencies for the fork endpoint."""
    app = FastAPI()
    app.include_router(router)

    ws = _mock_workspace(mgr=manager_mock, session=session_mock)

    async def override_workspace():
        return ws

    app.dependency_overrides[get_current_session_id] = lambda: None
    # Wire the Depends(get_workspace) / Depends(get_chat_manager) /
    # Depends(get_session) used inside the endpoint
    from qwenpaw.app.chats.api import get_workspace
    from qwenpaw.app.chats.api import get_chat_manager as _gcm
    from qwenpaw.app.chats.api import get_session as _gs

    app.dependency_overrides[get_workspace] = override_workspace
    app.dependency_overrides[_gcm] = lambda: manager_mock
    app.dependency_overrides[_gs] = lambda: session_mock

    return app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


# ---------------------------------------------------------------------------
# 201 — happy path
# ---------------------------------------------------------------------------


def test_fork_returns_201_and_new_chat(
    client,
    manager_mock,
    session_mock,
):
    """Happy path: fork returns 201 with lineage in meta."""
    source = _make_chat_spec()
    manager_mock.get_chat = AsyncMock(return_value=source)
    manager_mock.fork_chat = AsyncMock(
        return_value=ChatSpec(
            id="fork-999",
            session_id="console:u1:fork-abcdef01",
            user_id=source.user_id,
            channel=source.channel,
            name="Fork of Test Chat",
            source=SessionSource.chat,
            meta={
                "forked_from_chat_id": source.id,
                "forked_from_session_id": source.session_id,
                "forked_at": "2026-08-05T00:00:00Z",
            },
        ),
    )

    resp = client.post("/chats/abc-123/fork")

    assert resp.status_code == 201
    data = resp.json()
    assert data["chat_id"] == "fork-999"
    assert data["session_id"] == "console:u1:fork-abcdef01"
    assert data["name"] == "Fork of Test Chat"

    # verify clone was called with allow_missing_source=True
    session_mock.clone_session_state.assert_awaited_once()
    _, kwargs = session_mock.clone_session_state.call_args
    assert kwargs["src_session_id"] == "console:u1"
    assert kwargs["allow_missing_source"] is True

    # verify manager fork was called
    manager_mock.fork_chat.assert_awaited_once()
    _, kwargs = manager_mock.fork_chat.call_args
    assert kwargs["source_chat_id"] == "abc-123"
    assert kwargs["name"] == "Fork of Test Chat"


def test_fork_custom_name(client, manager_mock):
    """Custom name from request body is forwarded."""
    source = _make_chat_spec(name="Debug")
    manager_mock.get_chat = AsyncMock(return_value=source)
    manager_mock.fork_chat = AsyncMock(
        return_value=ChatSpec(
            id="f-1",
            session_id="console:u1:fork-xx",
            user_id="u1",
            channel="console",
            name="My Custom Fork",
            source=SessionSource.chat,
        ),
    )

    resp = client.post(
        "/chats/abc-123/fork",
        json={"name": "My Custom Fork"},
    )

    assert resp.status_code == 201
    manager_mock.fork_chat.assert_awaited_once()
    _, kwargs = manager_mock.fork_chat.call_args
    assert kwargs["name"] == "My Custom Fork"


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------


def test_fork_404_when_chat_not_found(client, manager_mock):
    """404 when source chat does not exist."""
    manager_mock.get_chat = AsyncMock(return_value=None)

    resp = client.post("/chats/nonexistent/fork")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 409
# ---------------------------------------------------------------------------


def test_fork_409_when_running(manager_mock):
    """409 when source chat is still generating."""
    source = _make_chat_spec()
    manager_mock.get_chat = AsyncMock(return_value=source)

    # Build a fresh app with running status
    session_mock_409 = AsyncMock(spec=SafeJSONSession)
    session_mock_409.clone_session_state = AsyncMock()

    app_409 = FastAPI()
    app_409.include_router(router)
    ws = _mock_workspace(
        mgr=manager_mock,
        session=session_mock_409,
        status="running",
    )

    async def override_ws():
        return ws

    from qwenpaw.app.chats.api import get_workspace
    from qwenpaw.app.chats.api import get_chat_manager as _gcm
    from qwenpaw.app.chats.api import get_session as _gs

    app_409.dependency_overrides[get_workspace] = override_ws
    app_409.dependency_overrides[_gcm] = lambda: manager_mock
    app_409.dependency_overrides[_gs] = lambda: session_mock_409

    from fastapi.testclient import TestClient

    client_409 = TestClient(app_409)

    resp = client_409.post("/chats/abc-123/fork")

    assert resp.status_code == 409
    assert "generating" in resp.json()["detail"].lower()
    # clone must NOT have been called
    session_mock_409.clone_session_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# 500 — clone failure (no orphan to clean up)
# ---------------------------------------------------------------------------


def test_fork_500_when_clone_fails(client, manager_mock, session_mock):
    """500 when clone_session_state raises; ChatSpec not created."""
    source = _make_chat_spec()
    manager_mock.get_chat = AsyncMock(return_value=source)
    session_mock.clone_session_state = AsyncMock(
        side_effect=OSError("disk full"),
    )

    resp = client.post("/chats/abc-123/fork")

    assert resp.status_code == 500
    assert "copy" in resp.json()["detail"].lower()
    # fork_chat must NOT have been called — no orphan to clean up
    manager_mock.fork_chat.assert_not_awaited()


# ---------------------------------------------------------------------------
# 500 — ChatSpec write failure (orphan cleanup invoked)
# ---------------------------------------------------------------------------


def test_fork_500_when_chat_spec_fails_with_cleanup(
    client,
    manager_mock,
    session_mock,
):
    """500 when fork_chat raises; delete_session_state called to clean up."""
    source = _make_chat_spec()
    manager_mock.get_chat = AsyncMock(return_value=source)
    manager_mock.fork_chat = AsyncMock(
        side_effect=ValueError("repo write failed"),
    )

    resp = client.post("/chats/abc-123/fork")

    assert resp.status_code == 500
    assert "create" in resp.json()["detail"].lower()
    # cleanup should have been called
    session_mock.delete_session_state.assert_awaited_once()


def test_fork_500_cleanup_failure_still_returns_500(
    client,
    manager_mock,
    session_mock,
):
    """500 when both fork_chat and cleanup fail."""
    source = _make_chat_spec()
    manager_mock.get_chat = AsyncMock(return_value=source)
    manager_mock.fork_chat = AsyncMock(
        side_effect=ValueError("repo write failed"),
    )
    session_mock.delete_session_state = AsyncMock(return_value=False)

    resp = client.post("/chats/abc-123/fork")

    assert resp.status_code == 500
    session_mock.delete_session_state.assert_awaited_once()
