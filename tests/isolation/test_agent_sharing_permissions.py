# -*- coding: utf-8 -*-
"""Agent 分享、公用发布和管理员治理的领域权限契约。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_governance import (
    AgentGovernanceDeniedError,
    AgentGovernanceRecord,
    AgentGovernanceService,
    AgentMemberRecord,
    AgentVisibility,
)
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.identity.models import PlatformRole


def _actor(user_id: UUID, role: PlatformRole) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-agent-sharing",
    )


class RecordingGovernanceRepository:
    def __init__(self, owner_id: UUID) -> None:
        self.owner_id = owner_id
        self.visibility = AgentVisibility.PRIVATE
        self.members: dict[UUID, AgentResourceRole] = {}
        self.actions: list[tuple[object, ...]] = []

    async def get_governance(self, agent_key: str):
        return AgentGovernanceRecord(
            agent_key=agent_key,
            owner_user_id=self.owner_id,
            visibility=self.visibility,
            status="active",
        )

    async def list_all_governance(self, agent_keys):
        return [
            await self.get_governance(agent_key)
            for agent_key in agent_keys
            if agent_key == "shared-agent"
        ]

    async def list_members(self, agent_key: str):
        return [
            AgentMemberRecord(
                user_id=user_id,
                username=f"user-{index}",
                role=role,
            )
            for index, (user_id, role) in enumerate(self.members.items(), start=1)
        ]

    async def grant_member(self, *, agent_key, user_id, role, actor):
        self.members[user_id] = role
        self.visibility = AgentVisibility.SHARED
        self.actions.append(("grant", agent_key, user_id, role, actor.user_id))

    async def revoke_member(self, *, agent_key, user_id, actor):
        self.members.pop(user_id, None)
        if not self.members:
            self.visibility = AgentVisibility.PRIVATE
        self.actions.append(("revoke", agent_key, user_id, actor.user_id))

    async def transfer_owner(self, *, agent_key, new_owner_user_id, actor):
        previous_owner = self.owner_id
        self.owner_id = new_owner_user_id
        self.members.pop(new_owner_user_id, None)
        self.members[previous_owner] = AgentResourceRole.COLLABORATOR
        self.actions.append(
            ("transfer", agent_key, new_owner_user_id, actor.user_id),
        )

    async def set_publication(self, *, agent_key, published, actor):
        self.visibility = (
            AgentVisibility.PUBLIC if published else AgentVisibility.PRIVATE
        )
        self.actions.append(("publish", agent_key, published, actor.user_id))


@pytest.mark.asyncio
async def test_owner_can_grant_revoke_and_transfer_but_collaborator_cannot() -> None:
    owner_id = uuid4()
    collaborator_id = uuid4()
    target_id = uuid4()
    repository = RecordingGovernanceRepository(owner_id)
    service = AgentGovernanceService(repository)

    await service.grant_member(
        actor=_actor(owner_id, PlatformRole.MEMBER),
        agent_key="shared-agent",
        user_id=collaborator_id,
        role=AgentResourceRole.COLLABORATOR,
    )
    assert repository.visibility is AgentVisibility.SHARED

    with pytest.raises(AgentGovernanceDeniedError):
        await service.grant_member(
            actor=_actor(collaborator_id, PlatformRole.MEMBER),
            agent_key="shared-agent",
            user_id=target_id,
            role=AgentResourceRole.USER,
        )

    await service.transfer_owner(
        actor=_actor(owner_id, PlatformRole.MEMBER),
        agent_key="shared-agent",
        new_owner_user_id=target_id,
    )
    assert repository.owner_id == target_id
    assert repository.members[owner_id] is AgentResourceRole.COLLABORATOR


@pytest.mark.asyncio
async def test_only_admin_can_publish_and_list_all_agents() -> None:
    owner_id = uuid4()
    admin_id = uuid4()
    repository = RecordingGovernanceRepository(owner_id)
    service = AgentGovernanceService(repository)

    with pytest.raises(AgentGovernanceDeniedError):
        await service.set_publication(
            actor=_actor(owner_id, PlatformRole.MEMBER),
            agent_key="shared-agent",
            published=True,
        )

    await service.set_publication(
        actor=_actor(admin_id, PlatformRole.ADMIN),
        agent_key="shared-agent",
        published=True,
    )
    assert repository.visibility is AgentVisibility.PUBLIC
    assert [
        item.agent_key
        for item in await service.list_all(
            actor=_actor(admin_id, PlatformRole.ADMIN),
            agent_keys=["shared-agent"],
        )
    ] == ["shared-agent"]

    with pytest.raises(AgentGovernanceDeniedError):
        await service.list_all(
            actor=_actor(owner_id, PlatformRole.MEMBER),
            agent_keys=["shared-agent"],
        )


@pytest.mark.asyncio
async def test_owner_cannot_add_self_or_use_owner_as_member_role() -> None:
    owner_id = uuid4()
    repository = RecordingGovernanceRepository(owner_id)
    service = AgentGovernanceService(repository)

    with pytest.raises(ValueError, match="owner_cannot_be_member"):
        await service.grant_member(
            actor=_actor(owner_id, PlatformRole.MEMBER),
            agent_key="shared-agent",
            user_id=owner_id,
            role=AgentResourceRole.USER,
        )

    with pytest.raises(ValueError, match="invalid_member_role"):
        await service.grant_member(
            actor=_actor(owner_id, PlatformRole.MEMBER),
            agent_key="shared-agent",
            user_id=uuid4(),
            role=AgentResourceRole.OWNER,
        )
