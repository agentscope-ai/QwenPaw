"""推送消费必须绑定当前接收人，不能按已知会话 ID 抢读。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app import console_push_store as store
from qwenpaw.app.routers import console
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.schemas import TextContent


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "admin"])
async def test_push_reads_and_consumption_are_scoped_to_authenticated_recipient(
    monkeypatch, role
):
    owner, other = uuid4(), uuid4()
    monkeypatch.setattr(store, "_list", [])
    await store.append("owner-session", "owner-private")
    store._list[-1]["recipient_user_id"] = str(owner)
    await store.append("other-session", "other-private")
    store._list[-1]["recipient_user_id"] = str(other)
    await store.append("legacy-unbound", "must-not-be-public")
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        console,
        "get_actor",
        lambda _: SimpleNamespace(user_id=owner, platform_role=role),
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: SimpleNamespace(list_pending_for_user=AsyncMock(return_value=[])),
    )
    app = FastAPI()
    app.include_router(console.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        leaked = await client.get("/api/console/push-messages?session_id=other-session")
        assert leaked.json()["messages"] == []
        response = await client.get("/api/console/push-messages")
        assert [item["text"] for item in response.json()["messages"]] == [
            "owner-private"
        ]
    assert any(item["text"] == "other-private" for item in store._list)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_parts", [False, True])
async def test_console_producer_binds_recipient_from_server_target(
    monkeypatch, tmp_path, content_parts
):
    recipient, impostor = uuid4(), uuid4()
    monkeypatch.setattr(store, "_list", [])
    monkeypatch.setattr("qwenpaw.identity.runtime.is_multi_user_enabled", lambda: True)
    channel = ConsoleChannel(
        process=lambda _: None, enabled=True, bot_prefix="", media_dir=str(tmp_path)
    )
    metadata = {"session_id": "shared-name", "recipient_user_id": str(impostor)}
    if content_parts:
        await channel.send_content_parts(
            str(recipient), [TextContent(text="私人产物")], metadata
        )
    else:
        await channel.send(str(recipient), "私人产物", metadata)
    assert store._list[0]["recipient_user_id"] == str(recipient)
    assert await store.get_recent(recipient_user_id=str(impostor)) == []
    assert (await store.get_recent(recipient_user_id=str(recipient)))[0][
        "text"
    ] == "私人产物"
