# -*- coding: utf-8 -*-
"""Agent statistics API for console."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from ...agent_stats import AgentStatsSummary, get_agent_stats_service
from ...agent_stats.postgres_repository import PostgresAgentStatsRepository
from ...access.agent_repository import AgentResourceRole
from ...access.dependencies import get_actor
from ...identity.runtime import get_identity_schema, is_multi_user_enabled
from ...token_usage.usage_repository import PostgresUsageRepository
from ...token_usage.usage_service import UsageScopeDenied, UsageScopeService
from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/agent-stats", tags=["agent-stats"])


def _usage_scope_service() -> UsageScopeService:
    schema = get_identity_schema()
    return UsageScopeService(
        repository=PostgresUsageRepository(schema=schema),
        schema=schema,
    )


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@router.get(
    "",
    summary="Get agent statistics summary",
    description="Return comprehensive agent statistics for the date range",
)
async def get_agent_statistics(
    request: Request,
    start_date: str | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
) -> AgentStatsSummary:
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    workspace = await get_agent_for_request(request)
    service = get_agent_stats_service()
    token_summary = None
    if is_multi_user_enabled():
        try:
            token_summary = await _usage_scope_service().get_summary(
                actor=get_actor(request),
                scope="agent",
                agent_key=workspace.agent_id,
                start_date=start_d,
                end_date=end_d,
            )
        except UsageScopeDenied as exc:
            raise HTTPException(status_code=403, detail="forbidden") from exc
        access = getattr(request.state, "agent_access", None)
        role = getattr(access, "role", AgentResourceRole.OWNER)
        if not isinstance(role, AgentResourceRole):
            role = AgentResourceRole(getattr(role, "value", role))
        return await PostgresAgentStatsRepository(
            schema=get_identity_schema()
        ).get_summary(
            agent_key=workspace.agent_id,
            viewer_user_id=get_actor(request).user_id,
            aggregate_all=role
            in {
                AgentResourceRole.OWNER,
                AgentResourceRole.COLLABORATOR,
            },
            start_date=start_d,
            end_date=end_d,
            token_summary=token_summary,
        )
    return await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
        token_summary=token_summary,
    )
