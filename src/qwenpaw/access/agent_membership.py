# -*- coding: utf-8 -*-
"""组合文件 Agent 目录与 PostgreSQL owner/成员关系。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .actor import ActorContext
from .agent_repository import (
    AgentAccessRecord,
    AgentMetadataRepository,
    AgentResourceRole,
    AgentVisibility,
    LegacyAgentRecord,
)

RegistrationState = Literal["registered", "legacy_preview"]


@dataclass(frozen=True, slots=True)
class AccessibleAgent:
    """文件事实和当前用户资源角色的合并结果。"""

    agent: LegacyAgentRecord
    owner_user_id: UUID
    role: AgentResourceRole
    registration_state: RegistrationState
    visibility: AgentVisibility = AgentVisibility.PRIVATE
    historical_read_only: bool = False


class AgentAccessDeniedError(RuntimeError):
    """统一拒绝不可见或角色不足的 Agent。"""

    def __init__(self) -> None:
        super().__init__("forbidden")


class AgentMembershipService:
    """Agent 列表过滤和资源角色判定。"""

    def __init__(self, repository: AgentMetadataRepository) -> None:
        self._repository = repository

    async def list_accessible(
        self,
        *,
        actor: ActorContext,
        legacy_agents: list[LegacyAgentRecord],
    ) -> list[AccessibleAgent]:
        if actor.user_id is None:
            raise AgentAccessDeniedError()
        keys = [agent.key for agent in legacy_agents]
        accessible = await self._repository.list_accessible(
            agent_keys=keys,
            user_id=actor.user_id,
        )
        history_loader = getattr(
            self._repository,
            "list_historical_accessible",
            None,
        )
        historical = (
            await history_loader(agent_keys=keys, user_id=actor.user_id)
            if history_loader is not None
            else {}
        )
        registered = await self._repository.list_registered_keys(keys)
        first_admin_id = await self._repository.get_first_admin_id()

        result: list[AccessibleAgent] = []
        for agent in legacy_agents:
            access = accessible.get(agent.key)
            if access is not None:
                result.append(self._registered(agent, access))
                continue
            history_access = historical.get(agent.key)
            if history_access is not None:
                result.append(self._registered(agent, history_access))
                continue
            if agent.key not in registered and actor.user_id == first_admin_id:
                result.append(
                    AccessibleAgent(
                        agent=agent,
                        owner_user_id=first_admin_id,
                        role=AgentResourceRole.OWNER,
                        registration_state="legacy_preview",
                        visibility=AgentVisibility.PRIVATE,
                    )
                )
        return result

    async def require_role(
        self,
        *,
        actor: ActorContext,
        agent: LegacyAgentRecord,
        allowed_roles: set[AgentResourceRole],
        allow_historical_read_only: bool = False,
    ) -> AccessibleAgent:
        matches = await self.list_accessible(actor=actor, legacy_agents=[agent])
        if (
            not matches
            or matches[0].role not in allowed_roles
            or (
                matches[0].historical_read_only
                and not allow_historical_read_only
            )
        ):
            raise AgentAccessDeniedError()
        return matches[0]

    @staticmethod
    def _registered(
        agent: LegacyAgentRecord,
        access: AgentAccessRecord,
    ) -> AccessibleAgent:
        return AccessibleAgent(
            agent=agent,
            owner_user_id=access.owner_user_id,
            role=access.role,
            registration_state="registered",
            visibility=access.visibility,
            historical_read_only=access.historical_read_only,
        )
