# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.tool_calls`` session scoping."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.tool_calls import router as tool_calls_router
from qwenpaw.tool_calls._context import ToolCallContext
from qwenpaw.tool_calls._entry import ToolCallEntry, ToolCallStatus
from qwenpaw.tool_calls._stream import ToolStream


@pytest.fixture
def coordinator() -> MagicMock:
    return MagicMock(name="ToolCoordinator")


@pytest.fixture
def client(coordinator: MagicMock) -> TestClient:
    application = FastAPI()
    application.state.app_services = SimpleNamespace(
        tool_coordinator=coordinator,
    )
    application.include_router(tool_calls_router, prefix="/api")
    return TestClient(application)


def _running_entry(
    *,
    tool_call_id: str = "tc-1",
    session_id: str = "session-a",
) -> ToolCallEntry:
    return ToolCallEntry(
        ctx=ToolCallContext(
            tool_call_id=tool_call_id,
            tool_name="shell",
            session_id=session_id,
            agent_id="agent-1",
            root_session_id="root-1",
            started_at=0.0,
            offload_deadline=None,
            cancel_event=asyncio.Event(),
        ),
        stream=ToolStream(tool_call_id=tool_call_id, session_id=session_id),
        final_response=None,
        status=ToolCallStatus.RUNNING,
    )


def test_get_call_rejects_session_mismatch(
    client: TestClient,
    coordinator: MagicMock,
) -> None:
    coordinator.get.return_value = _running_entry(session_id="session-a")
    resp = client.get("/api/tool-calls/session-b/tc-1")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Tool call not found"


def test_cancel_rejects_session_mismatch(
    client: TestClient,
    coordinator: MagicMock,
) -> None:
    coordinator.get.return_value = _running_entry(session_id="session-a")
    resp = client.post("/api/tool-calls/wrong-session/tc-1/cancel")
    assert resp.status_code == 404
    coordinator.cancel.assert_not_called()


def test_get_call_allows_matching_session(
    client: TestClient,
    coordinator: MagicMock,
) -> None:
    coordinator.get.return_value = _running_entry(session_id="session-a")
    resp = client.get("/api/tool-calls/session-a/tc-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_call_id"] == "tc-1"
    assert body["session_id"] == "session-a"
