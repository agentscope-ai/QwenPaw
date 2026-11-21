"""外层 Agent 路由不得拦住已独立校验所有者的只读内容入口。"""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import agent_scoped
from qwenpaw.identity.models import PlatformRole


def request_for(path, *, method="GET", query=b"", header=None):
    actor = ActorContext(user_id=uuid4(), actor_type=ActorType.USER,
                         platform_role=PlatformRole.MEMBER, admin_mode=False, request_id="owned-read")
    request = Request({"type": "http", "method": method,
        "path": "/api/agents/retired-agent" + path,
        "path_params": {"agentId": "retired-agent"}, "query_string": query,
        "headers": [] if header is None else [(b"x-agent-id", header.encode())], "app": FastAPI()})
    request.state.actor = actor
    return request, actor


@pytest.mark.asyncio
@pytest.mark.parametrize("path,query", [
    ("/console/personal-library/documents", b""),
    ("/console/personal-library/documents/page", b""),
    ("/console/personal-library/index", b""),
    (f"/console/personal-library/documents/{uuid4()}/download", b""),
    (f"/console/personal-library/documents/{uuid4()}/text", b""),
    ("/console/attachments", b""),
    (f"/console/attachments/{uuid4()}", b""),
    ("/workspace/memory", b"scope=private"),
    ("/workspace/memory/2026-11-21/note.md", b"scope=private"),
    ("/console/chat/task/task-owned-result", b""),
    ("/cron/jobs/owned-job/history", b""),
    ("/cron/jobs/owned-job", b""),
    ("/cron/jobs", b"scope=mine"),
    ("/cron/jobs", b""),
])
async def test_owned_read_reaches_object_authorization_without_agent_runtime(monkeypatch, path, query):
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    config_lookup = Mock(return_value=SimpleNamespace(agents=SimpleNamespace(profiles={})))
    monkeypatch.setattr(agent_scoped, "load_config", config_lookup)
    request, actor = request_for(path, query=query)
    assert await agent_scoped.require_agent_scoped_access(request, "retired-agent", actor) is actor
    config_lookup.assert_not_called()
    # A navigation exemption must not cache a runtime role or an editable workspace.
    assert not hasattr(request.state, "agent_access")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,query", [
    ("GET", "/workspace/memory", b""),
    ("GET", "/workspace/memory", b"scope=public"),
    ("GET", "/workspace/memory/note.md", b"scope=private&scope=public"),
    ("GET", "/workspace/memory/note.md", b"scope=private&scope=private"),
    ("PUT", "/workspace/memory/note.md", b"scope=private"),
    ("POST", "/console/personal-library/index/rebuild", b""),
    ("POST", "/console/chat/task/task-owned-result/cancel", b""),
    ("POST", "/cron/jobs/owned-job/run", b""),
    ("GET", "/workspace/tree", b"root=workspace"),
    ("GET", "/cron/jobs", b"scope=agent"),
    ("GET", "/cron/jobs/owned-job/state", b""),
    ("GET", "/cron/jobs/owned-job/authorization", b""),
])
async def test_ownership_read_rules_do_not_grant_runtime_or_shared_config(monkeypatch, method, path, query):
    from fastapi import HTTPException
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})))
    request, actor = request_for(path, method=method, query=query)
    with pytest.raises(HTTPException) as error:
        await agent_scoped.require_agent_scoped_access(request, "retired-agent", actor)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_owned_read_still_rejects_conflicting_explicit_agent(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    request, actor = request_for("/console/attachments", header="other-agent")
    with pytest.raises(HTTPException) as error:
        await agent_scoped.require_agent_scoped_access(request, "retired-agent", actor)
    assert error.value.status_code == 403
