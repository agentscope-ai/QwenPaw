# -*- coding: utf-8 -*-
"""聊天运行状态轻量接口回归测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.chats.api import get_chat_status


@pytest.mark.parametrize("status", ["idle", "running"])
async def test_get_chat_status_uses_agent_scoped_task_tracker(status: str) -> None:
    requested: list[str] = []

    class _TaskTracker:
        async def get_status(self, chat_id: str) -> str:
            requested.append(chat_id)
            return status

    response = await get_chat_status(
        "chat-status-id",
        request=Request({"type": "http", "headers": []}),
        workspace=SimpleNamespace(task_tracker=_TaskTracker()),
    )

    assert response.status == status
    assert requested == ["chat-status-id"]


@pytest.mark.parametrize("role", ["owner", "viewer", "revoked", "other-agent"])
async def test_status_rechecks_conversation_before_reading_tracker(monkeypatch, role):
    from qwenpaw.app.chats import api

    member, chat_id = uuid4(), uuid4()
    monkeypatch.setattr(api, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(api, "get_actor", lambda _: SimpleNamespace(user_id=member))
    record = SimpleNamespace(
        id=chat_id, owner_user_id=member if role == "owner" else uuid4(),
        agent_id=agent_database_id("other" if role == "other-agent" else "office"),
    )
    access = None if role == "revoked" else SimpleNamespace(conversation=record)
    bound = SimpleNamespace(get_conversation_for_user=AsyncMock(return_value=access))
    workspace = SimpleNamespace(
        agent_id="office",
        chat_manager=SimpleNamespace(conversation_repository=SimpleNamespace(with_user=lambda _: bound)),
        task_tracker=SimpleNamespace(get_status=AsyncMock(return_value="running")),
    )
    request = Request({"type": "http", "headers": []})
    if role in {"owner", "viewer"}:
        assert (await get_chat_status(str(chat_id), request, workspace)).status == "running"
    else:
        with pytest.raises(HTTPException) as denied:
            await get_chat_status(str(chat_id), request, workspace)
        assert denied.value.status_code == 404
        workspace.task_tracker.get_status.assert_not_awaited()
    bound.get_conversation_for_user.assert_awaited_once_with(conversation_id=chat_id, user_id=member)
