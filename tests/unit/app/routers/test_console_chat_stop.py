# -*- coding: utf-8 -*-
"""Regression tests for Console chat Stop propagation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import console as console_mod
from qwenpaw.tool_calls import CancelReason


@pytest.fixture
def stop_workspace(workspace_mock):
    workspace_mock.task_tracker = MagicMock()
    workspace_mock.task_tracker.request_stop = AsyncMock(return_value=True)
    workspace_mock.chat_manager = MagicMock()
    return workspace_mock


@pytest.fixture
def coordinator() -> MagicMock:
    value = MagicMock()
    value.cancel_running_for_session = AsyncMock(return_value=1)
    return value


@pytest.fixture
def app(manager_mock, stop_workspace, coordinator) -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.state.app_services = SimpleNamespace(
        tool_coordinator=coordinator,
    )
    application.include_router(console_mod.router, prefix="/api")
    return application


@pytest.mark.asyncio
async def test_stop_uuid_cancels_tools_before_chat_run(
    app,
    stop_workspace,
    coordinator,
) -> None:
    chat = SimpleNamespace(id="chat-uuid", session_id="runtime-session")
    stop_workspace.chat_manager.get_chat = AsyncMock(return_value=chat)
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock()
    call_order: list[str] = []

    async def cancel_tools(*_args, **_kwargs) -> int:
        call_order.append("tools")
        return 1

    async def stop_run(*_args, **_kwargs) -> bool:
        call_order.append("run")
        return True

    coordinator.cancel_running_for_session.side_effect = cancel_tools
    stop_workspace.task_tracker.request_stop.side_effect = stop_run

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/console/chat/stop",
            params={"chat_id": "chat-uuid"},
        )

    assert response.status_code == 200
    assert response.json() == {"stopped": True}
    assert call_order == ["tools", "run"]
    coordinator.cancel_running_for_session.assert_awaited_once_with(
        "runtime-session",
        reason=CancelReason.USER,
    )
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "chat-uuid",
    )


@pytest.mark.asyncio
async def test_stop_runtime_session_resolves_uuid_and_reports_tool_stop(
    app,
    stop_workspace,
    coordinator,
) -> None:
    chat = SimpleNamespace(id="chat-uuid", session_id="runtime-session")
    stop_workspace.chat_manager.get_chat = AsyncMock(
        side_effect=[None, chat],
    )
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock(
        return_value="chat-uuid",
    )
    stop_workspace.task_tracker.request_stop = AsyncMock(return_value=False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/console/chat/stop",
            params={"chat_id": "runtime-session"},
        )

    assert response.status_code == 200
    assert response.json() == {"stopped": True}
    stop_workspace.chat_manager.get_chat_id_by_session.assert_awaited_once_with(
        session_id="runtime-session",
        channel="console",
    )
    coordinator.cancel_running_for_session.assert_awaited_once_with(
        "runtime-session",
        reason=CancelReason.USER,
    )
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "chat-uuid",
    )


@pytest.mark.asyncio
async def test_stop_keeps_backward_compatibility_without_app_services(
    manager_mock,
    stop_workspace,
) -> None:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(console_mod.router, prefix="/api")
    stop_workspace.chat_manager.get_chat = AsyncMock(return_value=None)
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock(
        return_value=None,
    )

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/console/chat/stop",
            params={"chat_id": "unknown-chat"},
        )

    assert response.status_code == 200
    assert response.json() == {"stopped": True}
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "unknown-chat",
    )
