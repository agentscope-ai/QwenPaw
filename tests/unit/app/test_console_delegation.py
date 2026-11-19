from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from qwenpaw.app import auth
from qwenpaw.app.console_delegation import ConsoleDelegation
from qwenpaw.identity.models import PlatformRole, UserRecord


@pytest.mark.asyncio
async def test_child_uses_live_member_session_and_stops_on_revocation(monkeypatch):
    user = UserRecord(id=uuid4(), username="member", platform_role=PlatformRole.MEMBER, status="active")
    session_id = uuid4()
    session = SimpleNamespace(user=user, session=SimpleNamespace(id=session_id))
    sessions = SimpleNamespace(active_parent_session=AsyncMock(return_value=session))
    monkeypatch.setattr(auth, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(auth, "get_identity_runtime", lambda: SimpleNamespace(sessions=sessions))
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)

    @app.post("/api/console/chat/task")
    async def submit(request: Request):
        assert request.state.actor.user_id == user.id
        return (await request.json())["request_context"]

    parent = ConsoleDelegation(
        app, session_id, user.id, "default", str(uuid4()), tools=("read_file",), skills=(),
    )
    payload = {"request_context": {"subagent_allowed_tools": ["read_file", "write_file"], "subagent_skills": ["extra"]}}
    path = "/api/console/chat/task"
    response = await parent.call("POST", path, payload=payload)
    assert response.json() == {"subagent_allowed_tools": ["read_file"], "subagent_skills": []}
    sessions.active_parent_session.assert_awaited_once_with(session_id, user.id)
    sessions.active_parent_session.return_value = None
    with pytest.raises(httpx.HTTPStatusError) as error:
        await parent.call("POST", path, payload=payload)
    assert error.value.response.status_code == 401
    with pytest.raises(PermissionError):
        await parent.call("POST", path, payload=payload)
    assert sessions.active_parent_session.await_count == 2
