# -*- coding: utf-8 -*-
"""工具后台默认策略的权限、热更新与运行行为。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import settings, tool_calls
from qwenpaw.identity.models import PlatformRole
from qwenpaw.tool_calls import ToolCoordinator


ADMIN = ActorContext(
    user_id=uuid4(),
    actor_type=ActorType.USER,
    platform_role=PlatformRole.ADMIN,
    admin_mode=False,
    request_id="req-admin-offload",
)
MEMBER = replace(
    ADMIN,
    user_id=uuid4(),
    platform_role=PlatformRole.MEMBER,
    request_id="req-member-offload",
)


@dataclass
class _ToolCall:
    id: str
    name: str = "slow_tool"
    input: dict[str, Any] = field(default_factory=dict)


def _app(actor: ActorContext, coordinator: ToolCoordinator) -> FastAPI:
    app = FastAPI()
    app.include_router(settings.router, prefix="/api")
    app.dependency_overrides[settings.get_actor] = lambda: actor
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    return app


async def _set_policy(
    app: FastAPI,
    action: str,
) -> tuple[int, dict[str, str]]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.put(
            "/api/settings/offload-policy",
            json={"default_action": action},
        )
    return response.status_code, response.json()


async def _collect(iterator: AsyncGenerator[Any, None]) -> list[Any]:
    return [item async for item in iterator]


async def test_member_can_read_but_cannot_change_global_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"offload_policy": "offload"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "_SETTINGS_FILE", settings_file)
    coordinator = ToolCoordinator(offload_on_deadline=True)
    app = _app(MEMBER, coordinator)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        readable = await client.get("/api/settings/offload-policy")
        forbidden = await client.put(
            "/api/settings/offload-policy",
            json={"default_action": "keep_foreground"},
        )

    assert readable.status_code == 200
    assert readable.json() == {"default_action": "offload"}
    assert forbidden.status_code == 403
    assert coordinator.offload_on_deadline is True
    assert json.loads(settings_file.read_text("utf-8"))["offload_policy"] == "offload"


@pytest.mark.asyncio
async def test_admin_update_hot_applies_to_real_tool_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "_SETTINGS_FILE", tmp_path / "settings.json")
    coordinator = ToolCoordinator(
        default_timeout_secs=0.4,
        offload_on_deadline=False,
    )
    app = _app(ADMIN, coordinator)
    release = asyncio.Event()

    async def next_handler(tool_call: _ToolCall) -> AsyncGenerator[Any, None]:
        await release.wait()
        yield ToolResponse(
            id=tool_call.id,
            content=[TextBlock(type="text", text="done")],
        )

    execution = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=_ToolCall(id="call-hot-update"),
                next_handler=next_handler,
                session_id="session-member",
                agent_id="agent-shared",
                root_session_id="root-member",
                execution_context={
                    "user_id": str(MEMBER.user_id),
                    "approval_user_id": str(MEMBER.user_id),
                    "conversation_id": "conversation-member",
                    "run_id": "run-member",
                },
            ),
        ),
    )
    await asyncio.sleep(0)

    status, body = await _set_policy(app, "offload")
    events = await asyncio.wait_for(execution, timeout=1)

    assert status == 200
    assert body == {"default_action": "offload"}
    assert coordinator.offload_on_deadline is True
    assert events[-1].metadata["offloaded"] is True
    entry = coordinator.get("call-hot-update")
    assert entry is not None
    assert entry.ctx.extra["execution_context"] == {
        "user_id": str(MEMBER.user_id),
        "approval_user_id": str(MEMBER.user_id),
        "conversation_id": "conversation-member",
        "run_id": "run-member",
    }

    release.set()
    for _ in range(100):
        if entry.stream.is_closed:
            break
        await asyncio.sleep(0.01)
    assert entry.stream.is_closed


@pytest.mark.asyncio
async def test_user_manual_offload_still_overrides_keep_foreground(
    monkeypatch,
) -> None:
    coordinator = ToolCoordinator(
        default_timeout_secs=1.0,
        offload_on_deadline=False,
    )
    release = asyncio.Event()
    started = asyncio.Event()

    async def next_handler(tool_call: _ToolCall) -> AsyncGenerator[Any, None]:
        started.set()
        await release.wait()
        yield ToolResponse(
            id=tool_call.id,
            content=[TextBlock(type="text", text="done")],
        )

    execution = asyncio.create_task(
        _collect(
            coordinator.execute(
                tool_call=_ToolCall(id="call-user-offload"),
                next_handler=next_handler,
                session_id="session-member",
                agent_id="agent-shared",
                root_session_id="root-member",
                execution_context={"user_id": str(MEMBER.user_id)},
            ),
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    app = FastAPI()
    app.include_router(tool_calls.router, prefix="/api")
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    monkeypatch.setattr(tool_calls, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(tool_calls, "get_actor", lambda _request: MEMBER)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/tool-calls/session-member/call-user-offload/offload",
        )

    assert response.status_code == 202
    events = await asyncio.wait_for(execution, timeout=1)
    assert events[-1].metadata["offloaded"] is True
    assert events[-1].metadata["offload_reason"] == "user"

    release.set()
    entry = coordinator.get("call-user-offload")
    assert entry is not None
    for _ in range(100):
        if entry.stream.is_closed:
            break
        await asyncio.sleep(0.01)
    assert entry.stream.is_closed
