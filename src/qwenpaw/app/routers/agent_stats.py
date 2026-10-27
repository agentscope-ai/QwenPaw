# -*- coding: utf-8 -*-
"""Agent statistics API for console."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request

from ...agent_stats import AgentStatsSummary, get_agent_stats_service
from ...agent_stats.models import LlmToolDaily
from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/agent-stats", tags=["agent-stats"])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _resolved_date_range(
    start_date: str | None,
    end_date: str | None,
) -> tuple[date, date]:
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    return start_d, end_d


@router.get(
    "",
    summary="Get agent statistics summary",
    description="Return comprehensive agent statistics for the date range",
)
async def get_agent_statistics(
    request: Request,
    start_date: str
    | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str
    | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
) -> AgentStatsSummary:
    start_d, end_d = _resolved_date_range(start_date, end_date)

    workspace = await get_agent_for_request(request)
    service = get_agent_stats_service()
    return await service.get_summary(
        workspace_dir=workspace.workspace_dir,
        start_date=start_d,
        end_date=end_d,
    )


@router.get(
    "/llm-tool-trend",
    summary="Global LLM and tool-call trend",
    description="Sum Agent Statistics LLM turns and tool calls across agents",
)
async def get_global_llm_tool_trend(
    start_date: str
    | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str
    | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
) -> list[LlmToolDaily]:
    start_d, end_d = _resolved_date_range(start_date, end_date)
    service = get_agent_stats_service()
    return await service.get_global_llm_tool_by_date(start_d, end_d)
