# -*- coding: utf-8 -*-
"""Unit tests for console background chat-task timeout handling."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import console as console_mod
from qwenpaw.app.routers.console import (
    _background_task_cancel_error,
    _resolve_effective_stream_task_timeout,
)
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.constant import DEFAULT_STREAM_TASK_TIMEOUT_SECONDS
from qwenpaw.utils.timeout import parse_positive_timeout_seconds


def test_resolve_timeout_omitted_uses_default() -> None:
    assert (
        _resolve_effective_stream_task_timeout(None)
        == DEFAULT_STREAM_TASK_TIMEOUT_SECONDS
    )


def test_resolve_timeout_accepts_positive_number_and_string() -> None:
    assert _resolve_effective_stream_task_timeout(30) == 30
    assert _resolve_effective_stream_task_timeout(30.9) == 30
    assert _resolve_effective_stream_task_timeout("1800") == 1800
    assert _resolve_effective_stream_task_timeout(10**15) == 10**15
    assert _resolve_effective_stream_task_timeout(2**53 + 1) == 2**53 + 1
    assert _resolve_effective_stream_task_timeout("1e20") == int(1e20)


@pytest.mark.parametrize(
    "bad",
    [
        "abc",
        "",
        "null",
        True,
        False,
        0,
        -1,
        0.5,
        "0",
        "-3",
        float("nan"),
        float("inf"),
        "1e400",
        10**1000,
    ],
)
def test_resolve_timeout_rejects_invalid(bad) -> None:
    with pytest.raises(ValueError) as exc_info:
        _resolve_effective_stream_task_timeout(bad)
    message = str(exc_info.value)
    assert "timeout" in message
    assert "got" in message


def test_shared_parse_used_by_tool_and_console() -> None:
    """Tool and console wrappers must share the same parse rules."""
    assert parse_positive_timeout_seconds("30") == 30
    assert _resolve_effective_stream_task_timeout("30") == 30
    assert parse_positive_timeout_seconds(10**15) == 10**15
    assert parse_positive_timeout_seconds(2**53 + 1) == 2**53 + 1


def test_background_cancel_error_distinguishes_timeout() -> None:
    timed_out = _background_task_cancel_error(
        timed_out=True,
        timeout_seconds=30,
    )
    assert timed_out["code"] == "timeout"
    assert timed_out["message"] == "Task timed out after 30s"

    cancelled = _background_task_cancel_error(
        timed_out=False,
        timeout_seconds=30,
    )
    assert cancelled == {"message": "Task cancelled"}


@pytest.fixture(autouse=True)
def _clear_bg_tasks():
    console_mod._bg_tasks.clear()
    yield
    console_mod._bg_tasks.clear()


@pytest.fixture
def console_workspace(workspace_mock, monkeypatch):
    """Workspace with console channel + chat manager for /chat/task."""
    console_channel = MagicMock(name="ConsoleChannel")
    console_channel.resolve_session_id = MagicMock(
        return_value="console:default",
    )

    async def _stream_one(_payload):
        # Complete immediately so TestClient does not leave hung tasks.
        for _ in ():
            yield ""

    console_channel.stream_one = _stream_one
    workspace_mock.channel_manager.get_channel = AsyncMock(
        return_value=console_channel,
    )
    workspace_mock.console_channel = console_channel

    chat = MagicMock(name="ChatSpec")
    chat.id = "chat-1"
    chat.name = "New Chat"
    chat.meta = {}
    workspace_mock.chat_manager = MagicMock(name="ChatManager")
    workspace_mock.chat_manager.get_or_create_chat = AsyncMock(
        return_value=chat,
    )
    workspace_mock.task_tracker = TaskTracker()
    workspace_mock.agent_id = "default"
    workspace_mock.workspace_dir = "/tmp/qwenpaw-test-workspace"

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: MagicMock(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.resolve_effective_project_dir",
        lambda *args, **kwargs: ("/tmp/project", "test"),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.session_project_dir",
        lambda _meta: None,
    )
    monkeypatch.setattr(
        console_mod,
        "_apply_session_project_dir",
        AsyncMock(side_effect=lambda _ws, chat_obj, _payload: chat_obj),
    )
    return workspace_mock


@pytest.fixture
def app(manager_mock, console_workspace) -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(console_mod.router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _chat_task_body(**extra):
    body = {
        "channel": "console",
        "user_id": "default",
        "session_id": "console:default",
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }
    body.update(extra)
    return body


def test_chat_task_omitted_timeout_returns_default(
    client,
    console_workspace,
):
    response = client.post("/api/console/chat/task", json=_chat_task_body())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timeout"] == DEFAULT_STREAM_TASK_TIMEOUT_SECONDS
    assert body["task_id"].startswith("task-")


def test_chat_task_explicit_timeout_echoed(
    client,
    console_workspace,
):
    response = client.post(
        "/api/console/chat/task",
        json=_chat_task_body(timeout=30),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timeout"] == 30


def test_chat_task_large_int_timeout_echoed_exactly(
    client,
    console_workspace,
):
    """Ints must not be coerced through float (2**53+1 stays exact)."""
    huge = 2**53 + 1
    response = client.post(
        "/api/console/chat/task",
        json=_chat_task_body(timeout=huge),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timeout"] == huge


@pytest.mark.parametrize(
    "bad_timeout",
    [
        "abc",
        0,
        -1,
        True,
        False,
        {},
        [],
        {"seconds": 30},
        "1e400",
        10**1000,
    ],
)
def test_chat_task_invalid_timeout_returns_400(
    client,
    console_workspace,
    bad_timeout,
):
    """All illegal timeout values must be HTTP 400 (not FastAPI 422)."""
    response = client.post(
        "/api/console/chat/task",
        json=_chat_task_body(timeout=bad_timeout),
    )
    assert response.status_code == 400, response.text
    assert "timeout" in response.json()["detail"]


def test_agent_request_does_not_declare_task_timeout() -> None:
    """Shared AgentRequest must not own the background-task timeout field."""
    from qwenpaw.schemas import AgentRequest

    assert "timeout" not in AgentRequest.model_fields
    dumped = AgentRequest().model_dump()
    assert "timeout" not in dumped


async def test_chat_task_timeout_on_production_path(
    app,
    console_workspace,
    monkeypatch,
):
    """Exercise real post_console_chat_task guard + CancelledError wiring."""
    hang = asyncio.Event()

    async def _hanging_stream(_payload):
        await hang.wait()
        for _ in ():
            yield ""

    console_workspace.console_channel.stream_one = _hanging_stream

    real_sleep = asyncio.sleep

    async def _fast_sleep(delay, result=None):
        # Collapse the production timeout sleep; keep other sleeps real.
        if delay == 1:
            await real_sleep(0.01)
            return result
        return await real_sleep(delay, result=result)

    monkeypatch.setattr(console_mod.asyncio, "sleep", _fast_sleep)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        response = await ac.post(
            "/api/console/chat/task",
            json=_chat_task_body(timeout=1),
        )
        assert response.status_code == 200, response.text
        task_id = response.json()["task_id"]
        assert response.json()["timeout"] == 1

        deadline = time.time() + 3.0
        last = None
        while time.time() < deadline:
            status = await ac.get(f"/api/console/chat/task/{task_id}")
            assert status.status_code == 200, status.text
            last = status.json()
            if last.get("status") == "finished":
                break
            await asyncio.sleep(0.02)

    assert last is not None
    assert last["status"] == "finished", last
    result = last.get("result") or {}
    assert result.get("status") == "failed", result
    error = result.get("error") or {}
    assert error.get("code") == "timeout"
    assert error.get("message") == "Task timed out after 1s"


async def test_chat_task_manual_cancel_is_not_timeout(
    app,
    console_workspace,
):
    """Non-timeout cancel must stay Task cancelled without code=timeout."""
    entered = asyncio.Event()
    hang = asyncio.Event()

    async def _hanging_stream(_payload):
        entered.set()
        await hang.wait()
        for _ in ():
            yield ""

    console_workspace.console_channel.stream_one = _hanging_stream

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        response = await ac.post(
            "/api/console/chat/task",
            json=_chat_task_body(timeout=3600),
        )
        assert response.status_code == 200, response.text
        task_id = response.json()["task_id"]

        await asyncio.wait_for(entered.wait(), timeout=2.0)
        bg = console_mod._bg_tasks[task_id]
        assert bg.asyncio_task is not None

        # Cancel the production `_run` task (not the timeout guard).
        bg.asyncio_task.cancel()
        try:
            await bg.asyncio_task
        except asyncio.CancelledError:
            pass

        assert bg.status == "finished", (bg.status, bg.result)
        error = (bg.result or {}).get("error") or {}
        assert error.get("message") == "Task cancelled"
        assert "code" not in error

        status = await ac.get(f"/api/console/chat/task/{task_id}")
        assert status.status_code == 200, status.text
        last = status.json()

    assert last["status"] == "finished", last
    error = (last.get("result") or {}).get("error") or {}
    assert error.get("message") == "Task cancelled"
    assert "code" not in error
