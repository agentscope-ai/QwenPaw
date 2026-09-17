from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.app.routers import artifacts


@pytest.mark.asyncio
async def test_retry_collects_only_owned_current_agent_conversations(monkeypatch):
    owner, own_chat, other_chat = uuid4(), uuid4(), uuid4()
    old, new = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    service = SimpleNamespace(
        collect_session=AsyncMock(return_value=SimpleNamespace(artifacts=(old, new), failures=())),
        list_active=AsyncMock(return_value=[old]),
    )
    monkeypatch.setattr(artifacts, "_scope", AsyncMock(return_value=(service, owner, "qa")))
    repository = SimpleNamespace(list_conversations=AsyncMock(return_value=[
        SimpleNamespace(id=own_chat, owner_user_id=owner, agent_id=agent_database_id("qa")),
        SimpleNamespace(id=other_chat, owner_user_id=owner, agent_id=agent_database_id("other")),
    ]))
    monkeypatch.setattr(artifacts, "_conversation_repository", lambda user: repository, raising=False)
    result = await artifacts.collect_artifacts(SimpleNamespace(), None)
    assert result["collected"] == 1
    service.collect_session.assert_awaited_once_with(owner_user_id=owner, agent_key="qa", conversation_id=own_chat)
    with pytest.raises(HTTPException) as exc:
        await artifacts.collect_artifacts(SimpleNamespace(), artifacts.CollectArtifactsRequest(conversation_id=other_chat))
    assert exc.value.status_code == 404
