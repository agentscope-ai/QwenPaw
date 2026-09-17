# -*- coding: utf-8 -*-
"""Agent 成员分享、所有权和平台公用发布的领域服务。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..identity.models import PlatformRole
from .actor import ActorContext
from .agent_repository import (
    AgentGovernanceRecord,
    AgentMemberRecord,
    AgentResourceRole,
    AgentVisibility,
)


class AgentGovernanceDeniedError(RuntimeError):
    """调用者没有执行治理操作的资源权限。"""

    def __init__(self) -> None:
        super().__init__("forbidden")


class AgentGovernanceRepository(Protocol):
    async def get_governance(
        self,
        agent_key: str,
    ) -> AgentGovernanceRecord | None: ...

    async def list_all_governance(
        self,
        agent_keys: list[str],
    ) -> list[AgentGovernanceRecord]: ...

    async def list_members(self, agent_key: str) -> list[AgentMemberRecord]: ...

    async def grant_member(
        self,
        *,
        agent_key: str,
        user_id: UUID,
        role: AgentResourceRole,
        actor: ActorContext,
    ) -> None: ...

    async def revoke_member(
        self,
        *,
        agent_key: str,
        user_id: UUID,
        actor: ActorContext,
    ) -> None: ...

    async def transfer_owner(
        self,
        *,
        agent_key: str,
        new_owner_user_id: UUID,
        actor: ActorContext,
    ) -> None: ...

    async def set_publication(
        self,
        *,
        agent_key: str,
        published: bool,
        actor: ActorContext,
    ) -> None: ...

    async def record_admin_action(
        self,
        *,
        agent_key: str,
        action: str,
        actor: ActorContext,
    ) -> None: ...


class AgentGovernanceService:
    """在写入前集中执行 owner 与管理员权限边界。"""

    def __init__(self, repository: AgentGovernanceRepository) -> None:
        self._repository = repository

    async def list_members(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        admin_governance: bool = False,
    ) -> list[AgentMemberRecord]:
        governance = await self._require_governance(agent_key)
        if not self._is_owner(actor, governance) and not (
            admin_governance and self._is_admin(actor)
        ):
            raise AgentGovernanceDeniedError()
        return await self._repository.list_members(agent_key)

    async def grant_member(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        user_id: UUID,
        role: AgentResourceRole,
    ) -> None:
        governance = await self._require_owner(actor, agent_key)
        if role not in {
            AgentResourceRole.COLLABORATOR,
            AgentResourceRole.USER,
        }:
            raise ValueError("invalid_member_role")
        if user_id == governance.owner_user_id:
            raise ValueError("owner_cannot_be_member")
        await self._repository.grant_member(
            agent_key=agent_key,
            user_id=user_id,
            role=role,
            actor=actor,
        )

    async def revoke_member(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        user_id: UUID,
    ) -> None:
        governance = await self._require_owner(actor, agent_key)
        if user_id == governance.owner_user_id:
            raise ValueError("owner_cannot_be_member")
        await self._repository.revoke_member(
            agent_key=agent_key,
            user_id=user_id,
            actor=actor,
        )

    async def transfer_owner(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        new_owner_user_id: UUID,
    ) -> None:
        governance = await self._require_owner(actor, agent_key)
        if new_owner_user_id == governance.owner_user_id:
            raise ValueError("already_owner")
        await self._repository.transfer_owner(
            agent_key=agent_key,
            new_owner_user_id=new_owner_user_id,
            actor=actor,
        )

    async def set_publication(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        published: bool,
    ) -> None:
        if not self._is_admin(actor):
            raise AgentGovernanceDeniedError()
        await self._require_governance(agent_key)
        await self._repository.set_publication(
            agent_key=agent_key,
            published=published,
            actor=actor,
        )

    async def list_all(
        self,
        *,
        actor: ActorContext,
        agent_keys: list[str],
    ) -> list[AgentGovernanceRecord]:
        if not self._is_admin(actor):
            raise AgentGovernanceDeniedError()
        return await self._repository.list_all_governance(agent_keys)

    async def require_admin_agent(
        self,
        *,
        actor: ActorContext,
        agent_key: str,
        action: str,
    ) -> AgentGovernanceRecord:
        if not self._is_admin(actor):
            raise AgentGovernanceDeniedError()
        governance = await self._require_governance(agent_key)
        await self._repository.record_admin_action(
            agent_key=agent_key,
            action=action,
            actor=actor,
        )
        return governance

    async def _require_owner(
        self,
        actor: ActorContext,
        agent_key: str,
    ) -> AgentGovernanceRecord:
        governance = await self._require_governance(agent_key)
        if not self._is_owner(actor, governance):
            raise AgentGovernanceDeniedError()
        return governance

    async def _require_governance(
        self,
        agent_key: str,
    ) -> AgentGovernanceRecord:
        governance = await self._repository.get_governance(agent_key)
        if governance is None or governance.status == "deleted":
            raise AgentGovernanceDeniedError()
        return governance

    @staticmethod
    def _is_owner(
        actor: ActorContext,
        governance: AgentGovernanceRecord,
    ) -> bool:
        return actor.user_id is not None and actor.user_id == governance.owner_user_id

    @staticmethod
    def _is_admin(actor: ActorContext) -> bool:
        return actor.user_id is not None and actor.platform_role is PlatformRole.ADMIN
