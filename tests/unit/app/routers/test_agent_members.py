# -*- coding: utf-8 -*-
"""Agent 分享与管理员公用发布 API 契约。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_governance import AgentGovernanceDeniedError
from qwenpaw.access.agent_repository import (
    AgentGovernanceRecord,
    AgentMemberRecord,
    AgentResourceRole,
    AgentVisibility,
)
from qwenpaw.app.routers import agent_members
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.identity.models import PlatformRole
from qwenpaw.providers import ProviderManager


def _actor(role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-agent-members-router",
    )


class RecordingService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.denied = False

    async def list_members(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("list", kwargs))
        return [
            AgentMemberRecord(
                user_id=uuid4(),
                username="collaborator",
                role=AgentResourceRole.COLLABORATOR,
            )
        ]

    async def grant_member(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("grant", kwargs))

    async def revoke_member(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("revoke", kwargs))

    async def transfer_owner(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("transfer", kwargs))

    async def set_publication(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("publication", kwargs))

    async def list_all(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("all", kwargs))
        return [
            AgentGovernanceRecord(
                agent_key="member-agent",
                owner_user_id=uuid4(),
                visibility=AgentVisibility.PUBLIC,
                status="active",
            )
        ]

    async def require_admin_agent(self, **kwargs):
        if self.denied:
            raise AgentGovernanceDeniedError()
        self.calls.append(("admin", kwargs))


@pytest.mark.asyncio
async def test_owner_member_endpoints_forward_authenticated_actor(monkeypatch) -> None:
    actor = _actor(PlatformRole.MEMBER)
    service = RecordingService()
    monkeypatch.setattr(agent_members, "get_governance_service", lambda: service)

    response = await agent_members.grant_agent_member(
        "member-agent",
        uuid4(),
        agent_members.MemberRoleRequest(role=AgentResourceRole.USER),
        actor,
        service,
    )

    assert response.success is True
    assert service.calls[0][0] == "grant"
    assert service.calls[0][1]["actor"] is actor


@pytest.mark.asyncio
async def test_denied_governance_is_mapped_to_non_leaking_403() -> None:
    actor = _actor(PlatformRole.MEMBER)
    service = RecordingService()
    service.denied = True

    with pytest.raises(agent_members.HTTPException) as exc_info:
        await agent_members.list_agent_members(
            "hidden-agent",
            actor,
            service,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


@pytest.mark.asyncio
async def test_admin_publication_and_all_agents_use_explicit_admin_routes() -> None:
    actor = _actor(PlatformRole.ADMIN)
    service = RecordingService()
    request = SimpleNamespace(state=SimpleNamespace(actor=actor))

    publication = await agent_members.set_agent_publication(
        "member-agent",
        agent_members.PublicationRequest(published=True),
        actor,
        service,
    )
    all_agents = await agent_members.list_admin_agents(
        request,
        actor,
        service,
    )

    assert publication.visibility is AgentVisibility.PUBLIC
    assert all_agents.agents[0].id == "member-agent"
    assert all_agents.agents[0].governed_by_admin is True


@pytest.mark.asyncio
async def test_admin_cannot_save_inherited_agent_without_platform_default(
    monkeypatch,
) -> None:
    actor = _actor(PlatformRole.ADMIN)
    service = RecordingService()
    persisted = False

    async def record_persist(**_kwargs):
        nonlocal persisted
        persisted = True

    monkeypatch.setattr(agent_members, "_persist_agent_update", record_persist)
    monkeypatch.setattr(
        ProviderManager,
        "_instance",
        SimpleNamespace(get_active_model=lambda: None),
    )

    with pytest.raises(agent_members.HTTPException) as exc_info:
        await agent_members.update_admin_agent_config(
            SimpleNamespace(),
            "QwenPaw_QA_Agent_0.2",
            AgentProfileConfig(
                id="QwenPaw_QA_Agent_0.2",
                name="QA Agent",
                active_model=None,
            ),
            actor,
            service,
        )

    assert exc_info.value.status_code == 400
    assert persisted is False
