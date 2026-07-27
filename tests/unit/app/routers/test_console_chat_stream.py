# -*- coding: utf-8 -*-
"""Router-level integration test for the console chat SSE stream.

Uses a real ``TaskTracker`` and a real ``StreamingResponse`` so the
heartbeat comment frames are verified end to end through the endpoint,
not just at the queue-consumer unit level.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app import task_tracker as task_tracker_mod
from qwenpaw.app.routers.console import router
from qwenpaw.app.task_tracker import TaskTracker

# Producer idle gap must comfortably exceed the heartbeat interval so
# at least one keep-alive frame is emitted between the two data events.
HEARTBEAT_INTERVAL = 0.05
PRODUCER_IDLE_GAP = 0.5


async def _gappy_stream(_payload):
    """Yield one event, stay idle past the heartbeat interval, yield again."""
    yield "data: first\n\n"
    await asyncio.sleep(PRODUCER_IDLE_GAP)
    yield "data: second\n\n"


@pytest.fixture
def workspace() -> SimpleNamespace:
    console_channel = SimpleNamespace(
        resolve_session_id=lambda sender_id, channel_meta: "console:default",
        stream_one=_gappy_stream,
    )
    return SimpleNamespace(
        task_tracker=TaskTracker(),
        chat_manager=SimpleNamespace(
            get_or_create_chat=AsyncMock(
                return_value=SimpleNamespace(id="chat-1", name="New Chat"),
            ),
        ),
        channel_manager=SimpleNamespace(
            get_channel=AsyncMock(return_value=console_channel),
        ),
    )


@pytest.fixture
def client(workspace: SimpleNamespace):
    app = FastAPI()
    app.include_router(router)
    with patch(
        "qwenpaw.app.routers.console.get_agent_for_request",
        new=AsyncMock(return_value=workspace),
    ):
        yield TestClient(app)


def test_stream_emits_heartbeat_during_idle_gap(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        task_tracker_mod,
        "HEARTBEAT_INTERVAL_SECONDS",
        HEARTBEAT_INTERVAL,
    )

    body = {
        "user_id": "default",
        "channel": "console",
        "session_id": "console:default",
        "input": [],
    }
    with client.stream("POST", "/console/chat", json=body) as response:
        assert response.status_code == 200
        content_type = response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        lines = [line for line in response.iter_lines() if line]

    assert "data: first" in lines
    assert "data: second" in lines

    first_idx = lines.index("data: first")
    second_idx = lines.index("data: second")
    gap_lines = lines[first_idx + 1 : second_idx]
    heartbeats = [ln for ln in gap_lines if ln == ": keep-alive"]
    assert heartbeats, "expected at least one heartbeat in the idle gap"
