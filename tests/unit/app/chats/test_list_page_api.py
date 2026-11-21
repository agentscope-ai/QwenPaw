"""分页接口的边界、授权失败与元数据查询。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.chats import api
from qwenpaw.app.chats.list_paging import ChatPageResult
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.identity.models import PlatformRole


@pytest.mark.asyncio
async def test_page_contract_and_invalid_requests(monkeypatch):
    owner = uuid4()
    spec = ChatSpec(id=str(uuid4()), session_id="old-session", user_id=str(owner))
    access = SimpleNamespace(access_role="viewer", read_only=True, shared_by_username="owner")
    manager = SimpleNamespace(list_chat_page=AsyncMock(return_value=ChatPageResult(
        [SimpleNamespace(chat=spec, access=access)], True, "next")))
    tracker = SimpleNamespace(get_status=AsyncMock(return_value="idle"))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_chat_manager] = lambda: manager
    app.dependency_overrides[api.get_workspace] = lambda: SimpleNamespace(task_tracker=tracker, agent_id="default")
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(api, "get_actor", lambda request: ActorContext(owner, ActorType.USER, PlatformRole.MEMBER, False, "test"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/chats/page?session_id=old-session")
        assert response.status_code == 200
        assert response.json()["items"][0]["read_only"] is True
        assert response.json()["items"][0]["agent_id"] == "default"
        assert response.json()["next_cursor"] == "next"
        assert manager.list_chat_page.call_args.kwargs["page_size"] == 20
        assert manager.list_chat_page.call_args.kwargs["session_id"] == "old-session"
        assert manager.list_chat_page.call_args.kwargs["user_id"] == owner
        tracker.get_status.assert_awaited_once()
        assert (await client.get("/chats/page?page_size=1000")).status_code == 422
        manager.list_chat_page.side_effect = ValueError("invalid_chat_cursor")
        assert (await client.get("/chats/page?cursor=bad")).status_code == 400
        manager.list_chat_page.side_effect = RuntimeError("authority unavailable")
        assert (await client.get("/chats/page")).status_code == 503


@pytest.mark.asyncio
async def test_deep_link_spec_checks_access_without_loading_history(monkeypatch):
    spec = ChatSpec(id=str(uuid4()), session_id="deep", user_id=str(uuid4()))
    access = SimpleNamespace(access_role="viewer", read_only=True, shared_by_username=None)
    authorize = AsyncMock(return_value=(spec, access))
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(api, "_require_readable_chat", authorize)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_chat_manager] = lambda: SimpleNamespace()
    app.dependency_overrides[api.get_workspace] = lambda: SimpleNamespace(agent_id="history-agent", task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="idle")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/chats/{spec.id}/spec")
    assert response.status_code == 200
    assert response.json()["id"] == spec.id
    assert response.json()["agent_id"] == "history-agent"
    authorize.assert_awaited_once()
