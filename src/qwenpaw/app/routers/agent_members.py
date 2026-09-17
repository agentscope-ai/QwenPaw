# -*- coding: utf-8 -*-
"""Agent 成员分享、所有权转移和管理员公用发布 API。"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel

from ...access.actor import ActorContext
from ...access.agent_governance import (
    AgentGovernanceDeniedError,
    AgentGovernanceService,
)
from ...access.agent_repository import (
    AgentResourceRole,
    AgentVisibility,
    PostgresAgentRepository,
)
from ...access.dependencies import get_actor, require_multi_user_mode
from ...config.config import AgentProfileConfig, load_agent_config
from ...config.utils import load_config
from ...identity.models import PlatformRole
from ...identity.repository import PostgresUserRepository
from ...identity.runtime import get_identity_schema
from .agents import (
    _display_agent_order,
    _persist_agent_update,
    _validate_agent_effective_model,
)

router = APIRouter(dependencies=[Depends(require_multi_user_mode)])


class MemberRoleRequest(BaseModel):
    role: Literal[AgentResourceRole.COLLABORATOR, AgentResourceRole.USER]


class TransferOwnerRequest(BaseModel):
    new_owner_user_id: UUID


class PublicationRequest(BaseModel):
    published: bool


class MutationResponse(BaseModel):
    success: bool = True


class PublicationResponse(MutationResponse):
    visibility: AgentVisibility


class AgentMemberResponse(BaseModel):
    user_id: UUID
    username: str
    role: AgentResourceRole


class DirectoryUserResponse(BaseModel):
    id: UUID
    username: str
    platform_role: PlatformRole


class AdminAgentSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_user_id: UUID
    visibility: AgentVisibility
    status: str
    governed_by_admin: bool = True


class AdminAgentListResponse(BaseModel):
    agents: list[AdminAgentSummary]


def get_governance_service() -> AgentGovernanceService:
    return AgentGovernanceService(
        PostgresAgentRepository(schema=get_identity_schema()),
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AgentGovernanceDeniedError):
        return HTTPException(status_code=403, detail="forbidden")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get(
    "/agents/{agentId}/members",
    response_model=list[AgentMemberResponse],
    tags=["agent-members"],
)
async def list_agent_members(
    agentId: str = Path(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> list[AgentMemberResponse]:
    try:
        members = await service.list_members(actor=actor, agent_key=agentId)
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return [
        AgentMemberResponse(
            user_id=member.user_id,
            username=member.username,
            role=member.role,
        )
        for member in members
    ]


@router.put(
    "/agents/{agentId}/members/{user_id}",
    response_model=MutationResponse,
    tags=["agent-members"],
)
async def grant_agent_member(
    agentId: str = Path(...),
    user_id: UUID = Path(...),
    body: MemberRoleRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> MutationResponse:
    try:
        await service.grant_member(
            actor=actor,
            agent_key=agentId,
            user_id=user_id,
            role=AgentResourceRole(body.role),
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return MutationResponse()


@router.delete(
    "/agents/{agentId}/members/{user_id}",
    response_model=MutationResponse,
    tags=["agent-members"],
)
async def revoke_agent_member(
    agentId: str = Path(...),
    user_id: UUID = Path(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> MutationResponse:
    try:
        await service.revoke_member(
            actor=actor,
            agent_key=agentId,
            user_id=user_id,
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return MutationResponse()


@router.post(
    "/agents/{agentId}/transfer-owner",
    response_model=MutationResponse,
    tags=["agent-members"],
)
async def transfer_agent_owner(
    agentId: str = Path(...),
    body: TransferOwnerRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> MutationResponse:
    try:
        await service.transfer_owner(
            actor=actor,
            agent_key=agentId,
            new_owner_user_id=body.new_owner_user_id,
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return MutationResponse()


@router.get(
    "/agent-sharing/users",
    response_model=list[DirectoryUserResponse],
    tags=["agent-members"],
)
async def list_shareable_users(
    actor: ActorContext = Depends(get_actor),
) -> list[DirectoryUserResponse]:
    repository = PostgresUserRepository(schema=get_identity_schema())
    users = await repository.list_users()
    return [
        DirectoryUserResponse(
            id=user.id,
            username=user.username,
            platform_role=user.platform_role,
        )
        for user in users
        if user.status == "active" and user.id != actor.user_id
    ]


@router.patch(
    "/admin/agents/{agentId}/publication",
    response_model=PublicationResponse,
    tags=["admin-agents"],
)
async def set_agent_publication(
    agentId: str = Path(...),
    body: PublicationRequest = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> PublicationResponse:
    try:
        await service.set_publication(
            actor=actor,
            agent_key=agentId,
            published=body.published,
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    return PublicationResponse(
        visibility=(
            AgentVisibility.PUBLIC if body.published else AgentVisibility.PRIVATE
        )
    )


@router.get(
    "/admin/agents",
    response_model=AdminAgentListResponse,
    tags=["admin-agents"],
)
async def list_admin_agents(
    request: Request,
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> AdminAgentListResponse:
    del request
    config = load_config()
    ordered_keys = _display_agent_order(config)
    try:
        governance = await service.list_all(
            actor=actor,
            agent_keys=ordered_keys,
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    records = []
    for item in governance:
        try:
            profile = load_agent_config(item.agent_key)
            name = profile.name
            description = profile.description or ""
        except Exception:  # noqa: BLE001 - governance list keeps legacy fallback
            name = item.agent_key.title()
            description = ""
        records.append(
            AdminAgentSummary(
                id=item.agent_key,
                name=name,
                description=description,
                owner_user_id=item.owner_user_id,
                visibility=item.visibility,
                status=item.status,
            )
        )
    return AdminAgentListResponse(agents=records)


@router.get(
    "/admin/agents/{agentId}/config",
    response_model=AgentProfileConfig,
    tags=["admin-agents"],
)
async def get_admin_agent_config(
    agentId: str = Path(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> AgentProfileConfig:
    try:
        await service.require_admin_agent(
            actor=actor,
            agent_key=agentId,
            action="agent.admin.config.view",
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    try:
        return load_agent_config(agentId)
    except Exception as exc:  # noqa: BLE001 - preserve legacy 404 boundary
        raise HTTPException(status_code=404, detail="agent_not_found") from exc


@router.put(
    "/admin/agents/{agentId}/config",
    response_model=AgentProfileConfig,
    tags=["admin-agents"],
)
async def update_admin_agent_config(
    request: Request,
    agentId: str = Path(...),
    body: AgentProfileConfig = Body(...),
    actor: ActorContext = Depends(get_actor),
    service: AgentGovernanceService = Depends(get_governance_service),
) -> AgentProfileConfig:
    try:
        await service.require_admin_agent(
            actor=actor,
            agent_key=agentId,
            action="agent.admin.config.update",
        )
    except (AgentGovernanceDeniedError, ValueError) as exc:
        raise _map_error(exc) from exc
    _validate_agent_effective_model(body)
    await _persist_agent_update(
        agentId=agentId,
        agent_config=body,
        request=request,
    )
    return body
