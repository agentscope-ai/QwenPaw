"""本人已结束的任务结果不依赖 Agent 当前运行资格。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from qwenpaw.app.routers import console, tool_calls
from qwenpaw.tool_calls._entry import ToolCallStatus
from tests.unit.app.routers.test_tool_calls_router import _running_entry


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["owner", "other", "admin"])
async def test_finished_console_result_remains_owned_after_agent_revocation(
    monkeypatch, actor
):
    owner = uuid4()
    actor_id = owner if actor == "owner" else uuid4()
    task = console._BackgroundTask(
        status="finished",
        owner_user_id=str(owner),
        agent_id="old-agent",
        parent_agent_id="old-agent",
        conversation_id=str(uuid4()),
        parent_conversation_id=str(uuid4()),
        result={"text": "私人执行结果"},
    )
    monkeypatch.setitem(console._bg_tasks, "durable-owner-test", task)
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        console,
        "get_actor",
        lambda _: SimpleNamespace(user_id=actor_id, platform_role=actor),
    )
    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        AsyncMock(side_effect=HTTPException(403, "revoked")),
    )
    app = FastAPI()
    app.include_router(console.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/console/chat/task/durable-owner-test",
            headers={"X-Agent-Id": "another-agent"},
        )
    assert response.status_code == (200 if actor == "owner" else 404)
    if actor == "owner":
        assert response.json()["result"] == {"text": "私人执行结果"}


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [False, True])
async def test_completed_tool_result_is_owned_but_live_control_stays_authorized(
    monkeypatch, terminal
):
    owner = uuid4()
    entry = _running_entry()
    entry.ctx.extra["execution_context"] = {"user_id": str(owner)}
    if terminal:
        entry.status = ToolCallStatus.COMPLETED
        entry.end_state = "success"
        await entry.stream.close()
    coordinator = MagicMock()
    coordinator.get.return_value = entry
    monkeypatch.setattr(tool_calls, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        tool_calls, "get_actor", lambda _: SimpleNamespace(user_id=owner)
    )
    runtime = AsyncMock(side_effect=HTTPException(403, "revoked"))
    monkeypatch.setattr(tool_calls, "get_agent_for_request", runtime)
    app = FastAPI()
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    app.include_router(tool_calls.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/tool-calls/session-a/tc-1/output")
        control = await client.post("/api/tool-calls/session-a/tc-1/cancel")
    assert response.status_code == (200 if terminal else 403)
    assert control.status_code == 403
    coordinator.cancel.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_kind", ["owner", "other", "admin"])
async def test_completed_tool_reads_never_expand_to_other_accounts(
    monkeypatch, actor_kind
):
    owner = uuid4()
    entry = _running_entry()
    entry.ctx.extra["execution_context"] = {"user_id": str(owner)}
    entry.status = ToolCallStatus.COMPLETED
    await entry.stream.close()
    coordinator = MagicMock()
    coordinator.get.return_value = entry
    monkeypatch.setattr(tool_calls, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        tool_calls,
        "get_actor",
        lambda _: SimpleNamespace(
            user_id=owner if actor_kind == "owner" else uuid4(),
            platform_role=actor_kind,
        ),
    )
    denied_runtime = AsyncMock(side_effect=HTTPException(403, "revoked"))
    monkeypatch.setattr(tool_calls, "get_agent_for_request", denied_runtime)
    app = FastAPI()
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    app.include_router(tool_calls.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for suffix in ("", "/output"):
            response = await client.get(
                f"/api/tool-calls/session-a/tc-1{suffix}",
                headers={"X-Agent-Id": "different-agent"},
            )
            assert response.status_code == (200 if actor_kind == "owner" else 404)
        mismatch = await client.get("/api/tool-calls/wrong-session/tc-1/output")
        assert mismatch.status_code == 404
    denied_runtime.assert_not_awaited()
