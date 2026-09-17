# -*- coding: utf-8 -*-
"""Agent-scoped 路由必须统一授权且不破坏 Legacy 行为。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentAccessDeniedError
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.access.capabilities import Capability
from qwenpaw.access.service import AuthorizationService
from qwenpaw.app import agent_context
from qwenpaw.app.agent_context import (
    get_agent_for_request,
    get_current_agent_id,
    reset_current_agent_id,
    set_current_agent_id,
)
from qwenpaw.app.routers import agent_scoped
from qwenpaw.app.routers.agent_scoped import (
    AgentContextMiddleware,
    require_agent_scoped_access,
)
from qwenpaw.identity.models import PlatformRole


def _actor(role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-agent-scope",
    )


def _request(
    agent_id: str,
    *,
    header_agent_id: str | None = None,
    method: str = "GET",
    resource_path: str = "/tools",
) -> Request:
    headers = []
    if header_agent_id is not None:
        headers.append((b"x-agent-id", header_agent_id.encode("utf-8")))
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": f"/api/agents/{agent_id}{resource_path}",
            "path_params": {"agentId": agent_id},
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
            "scheme": "http",
            "app": FastAPI(),
        }
    )
    request.state.agent_id = agent_id
    return request


def _config(*, enabled: bool = True):
    return SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"allowed-agent": SimpleNamespace(enabled=enabled)},
        ),
    )


class _AllowMembership:
    async def require_role(self, **_kwargs):
        return object()


class _RoleMembership:
    def __init__(self, role: AgentResourceRole) -> None:
        self.role = role
        self.allowed_roles: set[AgentResourceRole] | None = None
        self.allow_historical_read_only = False

    async def require_role(self, **kwargs):
        self.allowed_roles = kwargs["allowed_roles"]
        self.allow_historical_read_only = kwargs.get(
            "allow_historical_read_only",
            False,
        )
        if self.role not in self.allowed_roles:
            raise AgentAccessDeniedError()
        return object()


class _WorkspaceManager:
    def __init__(self) -> None:
        self.requested_agent_ids: list[str] = []

    async def get_agent(self, agent_id: str):
        self.requested_agent_ids.append(agent_id)
        return SimpleNamespace(agent_id=agent_id)


@pytest.fixture(autouse=True)
def _allow_registered_agent_access(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: _AllowMembership(),
        raising=False,
    )


def test_admin_and_member_both_have_agent_use_capability() -> None:
    service = AuthorizationService()

    assert service.is_allowed(_actor(PlatformRole.ADMIN), Capability.AGENT_USE)
    assert service.is_allowed(_actor(PlatformRole.MEMBER), Capability.AGENT_USE)


@pytest.mark.asyncio
async def test_multi_user_rejects_path_header_conflict(monkeypatch) -> None:
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())

    with pytest.raises(agent_scoped.HTTPException) as exc_info:
        await require_agent_scoped_access(
            _request("allowed-agent", header_agent_id="forged-agent"),
            "allowed-agent",
            _actor(PlatformRole.MEMBER),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id", ["missing-agent", "allowed-agent"])
async def test_multi_user_rejects_unavailable_agent(
    monkeypatch,
    agent_id: str,
) -> None:
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        agent_scoped,
        "load_config",
        lambda: _config(enabled=agent_id != "allowed-agent"),
    )

    with pytest.raises(agent_scoped.HTTPException) as exc_info:
        await require_agent_scoped_access(
            _request(agent_id),
            agent_id,
            _actor(PlatformRole.MEMBER),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


@pytest.mark.asyncio
async def test_multi_user_rejects_agent_without_membership(monkeypatch) -> None:
    class DenyMembership:
        async def require_role(self, **_kwargs):
            raise AgentAccessDeniedError()

    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: DenyMembership(),
        raising=False,
    )

    with pytest.raises(agent_scoped.HTTPException) as exc_info:
        await require_agent_scoped_access(
            _request("allowed-agent"),
            "allowed-agent",
            _actor(PlatformRole.ADMIN),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_path",
    [
        "/config/channels/telegram",
        "/mcp/clients/example",
        "/skills/example",
        "/tools/example",
        "/workspace/files/example",
        "/plugins/example",
        "/checkpoints/example/restore",
    ],
)
async def test_user_role_cannot_mutate_agent_configuration(
    monkeypatch,
    resource_path: str,
) -> None:
    membership = _RoleMembership(AgentResourceRole.USER)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: membership,
        raising=False,
    )

    with pytest.raises(agent_scoped.HTTPException) as exc_info:
        await require_agent_scoped_access(
            _request(
                "allowed-agent",
                method="PUT",
                resource_path=resource_path,
            ),
            "allowed-agent",
            _actor(PlatformRole.MEMBER),
        )

    assert exc_info.value.status_code == 403
    assert membership.allowed_roles == {
        AgentResourceRole.OWNER,
        AgentResourceRole.COLLABORATOR,
    }


@pytest.mark.asyncio
async def test_user_role_reaches_automation_object_policy(monkeypatch) -> None:
    """仅使用成员可管理自己的自动化，具体对象归属由 Cron 路由判定。"""
    membership = _RoleMembership(AgentResourceRole.USER)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: membership,
        raising=False,
    )

    await require_agent_scoped_access(
        _request(
            "allowed-agent",
            method="PUT",
            resource_path="/cron/jobs/example",
        ),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )

    assert membership.allowed_roles == set(AgentResourceRole)


@pytest.mark.asyncio
async def test_user_role_can_read_configuration_and_run_chat(monkeypatch) -> None:
    membership = _RoleMembership(AgentResourceRole.USER)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: membership,
        raising=False,
    )

    await require_agent_scoped_access(
        _request("allowed-agent", resource_path="/config/channels"),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )
    assert membership.allowed_roles == set(AgentResourceRole)


@pytest.mark.asyncio
async def test_only_read_only_chat_routes_accept_historical_access(monkeypatch) -> None:
    membership = _RoleMembership(AgentResourceRole.USER)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_scoped, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_scoped,
        "_get_agent_membership_service",
        lambda: membership,
        raising=False,
    )

    await require_agent_scoped_access(
        _request("allowed-agent", resource_path="/chats/chat-id"),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )
    assert membership.allow_historical_read_only is True

    await require_agent_scoped_access(
        _request("allowed-agent", resource_path="/config/channels"),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )
    assert membership.allow_historical_read_only is False

    await require_agent_scoped_access(
        _request(
            "allowed-agent",
            method="POST",
            resource_path="/chats",
        ),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )
    assert membership.allow_historical_read_only is False

    await require_agent_scoped_access(
        _request(
            "allowed-agent",
            method="POST",
            resource_path="/console/chat",
        ),
        "allowed-agent",
        _actor(PlatformRole.MEMBER),
    )
    assert membership.allowed_roles == set(AgentResourceRole)


@pytest.mark.asyncio
async def test_legacy_keeps_existing_path_priority(monkeypatch) -> None:
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: False)
    monkeypatch.setattr(
        agent_scoped,
        "load_config",
        lambda: pytest.fail("Legacy 授权门不应提前改变原资源解析"),
    )

    actor = await require_agent_scoped_access(
        _request("path-agent", header_agent_id="legacy-header-agent"),
        "path-agent",
        ActorContext(
            user_id=None,
            actor_type=ActorType.USER,
            platform_role=PlatformRole.ADMIN,
            admin_mode=False,
            request_id="req-legacy",
        ),
    )

    assert actor.platform_role is PlatformRole.ADMIN


def test_every_agent_scoped_route_has_the_unified_access_dependency() -> None:
    router = agent_scoped.create_agent_scoped_router()
    assert any(
        dependency.dependency is require_agent_scoped_access
        for dependency in router.dependencies
    )


@pytest.mark.asyncio
async def test_unscoped_header_rejects_agent_without_membership(monkeypatch) -> None:
    class DenyMembership:
        async def require_role(self, **_kwargs):
            raise AgentAccessDeniedError()

    manager = _WorkspaceManager()
    request = _request("allowed-agent", header_agent_id="allowed-agent")
    request.scope["path"] = "/api/chats"
    request.scope["path_params"] = {}
    request.app.state.multi_agent_manager = manager
    request.state.actor = _actor(PlatformRole.MEMBER)

    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True, raising=False)
    monkeypatch.setattr(agent_context, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_context,
        "_get_agent_membership_service",
        lambda: DenyMembership(),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_agent_for_request(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"
    assert manager.requested_agent_ids == []


@pytest.mark.asyncio
async def test_unscoped_header_stores_authorized_agent_access(monkeypatch) -> None:
    access = SimpleNamespace(role=AgentResourceRole.USER)

    class AllowMembership:
        async def require_role(self, **_kwargs):
            return access

    manager = _WorkspaceManager()
    request = _request("allowed-agent", header_agent_id="allowed-agent")
    request.scope["path"] = "/api/chats"
    request.scope["path_params"] = {}
    request.app.state.multi_agent_manager = manager
    request.state.actor = _actor(PlatformRole.MEMBER)

    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True, raising=False)
    monkeypatch.setattr(agent_context, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_context,
        "_get_agent_membership_service",
        lambda: AllowMembership(),
        raising=False,
    )

    workspace = await get_agent_for_request(request)

    assert workspace.agent_id == "allowed-agent"
    assert request.state.agent_access is access


@pytest.mark.asyncio
async def test_unscoped_chat_get_allows_historical_read_only(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class HistoricalMembership:
        async def require_role(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                role=AgentResourceRole.USER,
                historical_read_only=True,
            )

    manager = _WorkspaceManager()
    request = _request("allowed-agent", header_agent_id="allowed-agent")
    request.scope["path"] = "/api/chats/history-id"
    request.scope["path_params"] = {}
    request.app.state.multi_agent_manager = manager
    request.state.actor = _actor(PlatformRole.MEMBER)

    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_context, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_context,
        "_get_agent_membership_service",
        lambda: HistoricalMembership(),
    )

    workspace = await get_agent_for_request(request)

    assert workspace.agent_id == "allowed-agent"
    assert captured["allow_historical_read_only"] is True
    assert manager.requested_agent_ids == ["allowed-agent"]


@pytest.mark.asyncio
async def test_unscoped_header_user_cannot_mutate_agent_configuration(
    monkeypatch,
) -> None:
    membership = _RoleMembership(AgentResourceRole.USER)
    manager = _WorkspaceManager()
    request = _request(
        "allowed-agent",
        header_agent_id="allowed-agent",
        method="PUT",
    )
    request.scope["path"] = "/api/config/channels/telegram"
    request.scope["path_params"] = {}
    request.app.state.multi_agent_manager = manager
    request.state.actor = _actor(PlatformRole.MEMBER)

    monkeypatch.setattr(agent_context, "is_multi_user_enabled", lambda: True, raising=False)
    monkeypatch.setattr(agent_context, "load_config", lambda: _config())
    monkeypatch.setattr(
        agent_context,
        "_get_agent_membership_service",
        lambda: membership,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_agent_for_request(request)

    assert exc_info.value.status_code == 403
    assert membership.allowed_roles == {
        AgentResourceRole.OWNER,
        AgentResourceRole.COLLABORATOR,
    }
    assert manager.requested_agent_ids == []


def test_agent_context_is_isolated_and_restored_after_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_active_agent_id",
        lambda: "default-agent",
    )
    app = FastAPI()
    app.add_middleware(AgentContextMiddleware)

    @app.get("/api/agents/{agentId}/probe")
    async def probe() -> dict[str, str]:
        return {"agent_id": get_current_agent_id()}

    @app.get("/api/probe")
    async def global_probe() -> dict[str, str]:
        return {"agent_id": get_current_agent_id()}

    outer_token = set_current_agent_id("outer-agent")
    try:
        response = TestClient(app).get("/api/agents/inner-agent/probe")

        assert response.status_code == 200
        assert response.json() == {"agent_id": "inner-agent"}
        assert get_current_agent_id() == "outer-agent"

        global_response = TestClient(app).get("/api/probe")

        assert global_response.status_code == 200
        assert global_response.json() == {"agent_id": "default-agent"}
        assert get_current_agent_id() == "outer-agent"
    finally:
        reset_current_agent_id(outer_token)
