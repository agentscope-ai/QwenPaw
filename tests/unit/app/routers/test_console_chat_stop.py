# -*- coding: utf-8 -*-
"""Regression tests for Console chat Stop propagation."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.routers import console as console_mod
from qwenpaw.tool_calls import CancelReason


@pytest.fixture(name="stop_workspace")
def fixture_stop_workspace(workspace_mock):
    workspace_mock.agent_id = "agent-a"
    workspace_mock.task_tracker = MagicMock()
    workspace_mock.task_tracker.request_stop = AsyncMock(return_value=True)
    workspace_mock.chat_manager = MagicMock()
    return workspace_mock


@pytest.fixture(name="coordinator")
def fixture_coordinator() -> MagicMock:
    value = MagicMock()
    value.cancel_running_for_session = AsyncMock(return_value=1)
    return value


@pytest.fixture(name="app")
def fixture_app(manager_mock, stop_workspace, coordinator) -> FastAPI:
    manager_mock.get_agent.return_value = stop_workspace
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
        agent_id="agent-a",
        reason=CancelReason.USER,
    )
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "chat-uuid",
        reason="user",
    )


@pytest.mark.asyncio
async def test_internal_timeout_stop_preserves_reason(
    app,
    stop_workspace,
    coordinator,
) -> None:
    chat = SimpleNamespace(id="chat-uuid", session_id="runtime-session")
    stop_workspace.chat_manager.get_chat = AsyncMock(return_value=chat)
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/console/chat/stop",
            params={
                "chat_id": "chat-uuid",
                "cancel_reason": "timeout",
            },
        )

    assert response.status_code == 200
    coordinator.cancel_running_for_session.assert_awaited_once_with(
        "runtime-session",
        agent_id="agent-a",
        reason=CancelReason.TIMEOUT,
    )
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "chat-uuid",
        reason="timeout",
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
    resolve_session = stop_workspace.chat_manager.get_chat_id_by_session
    resolve_session.assert_awaited_once_with(
        session_id="runtime-session",
        channel="console",
    )
    coordinator.cancel_running_for_session.assert_awaited_once_with(
        "runtime-session",
        agent_id="agent-a",
        reason=CancelReason.USER,
    )
    stop_workspace.task_tracker.request_stop.assert_awaited_once_with(
        "chat-uuid",
        reason="user",
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
        reason="user",
    )


class _Capture(logging.Handler):
    """Direct-attach capture; immune to propagate=False configurations."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.mark.asyncio
async def test_stop_audit_log_carries_reason_and_initiator(
    app,
    stop_workspace,
) -> None:
    """GH-8252: one INFO line must attribute WHO stopped the chat and WHY,
    with CR/LF neutralized so untrusted IDs cannot forge log lines."""
    chat = SimpleNamespace(id="chat-uuid", session_id="runtime-session")
    stop_workspace.chat_manager.get_chat = AsyncMock(return_value=chat)
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock()

    capture = _Capture()
    logger = logging.getLogger("qwenpaw.app.routers.console")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/console/chat/stop",
                params={
                    "chat_id": "chat-uuid",
                    "cancel_reason": "timeout",
                    "initiator": "caller:session\r\nfake forged line",
                },
            )
    finally:
        logger.removeHandler(capture)

    assert response.status_code == 200
    audit = [m for m in capture.messages if "[STOP API] chat stop" in m]
    assert len(audit) == 1, capture.messages
    line = audit[0]
    assert "chat_id=chat-uuid" in line
    assert "reason=timeout" in line
    assert "initiator=caller:session\\r\\nfake forged line" in line
    assert "stopped=True" in line
    # the raw CR/LF must never reach the formatted line
    assert "\n" not in line and "\r" not in line


@pytest.mark.asyncio
async def test_stop_audit_log_defaults_without_initiator(
    app,
    stop_workspace,
) -> None:
    """Backward compatibility: callers that do not send initiator still
    get an auditable line with reason=user and initiator placeholder."""
    chat = SimpleNamespace(id="chat-uuid", session_id="runtime-session")
    stop_workspace.chat_manager.get_chat = AsyncMock(return_value=chat)
    stop_workspace.chat_manager.get_chat_id_by_session = AsyncMock()

    capture = _Capture()
    logger = logging.getLogger("qwenpaw.app.routers.console")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/console/chat/stop",
                params={"chat_id": "chat-uuid"},
            )
    finally:
        logger.removeHandler(capture)

    assert response.status_code == 200
    audit = [m for m in capture.messages if "[STOP API] chat stop" in m]
    assert len(audit) == 1, capture.messages
    assert "reason=user" in audit[0]
    assert "initiator=-" in audit[0]
