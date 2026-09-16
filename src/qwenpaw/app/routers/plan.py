# -*- coding: utf-8 -*-
"""Plan mode API endpoints.

Provides read-only plan state, enable/disable toggle, and SSE stream.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Request
from starlette.responses import StreamingResponse

from ...config.config import PlanConfig, save_agent_config
from ...plan.broadcast import (
    get_live_plan,
    register_sse_client,
    unregister_sse_client,
)
from ...plan.schemas import (
    PlanConfigResponse,
    PlanStateResponse,
    plan_to_response,
)
from ..agent_context import (
    get_running_config_workspace,
    require_running_config_editor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def _plan_from_session_state(
    workspace,
    session_id: str,
) -> PlanStateResponse | None:
    """Try to load the plan from the persisted session state on disk."""
    try:
        session = workspace.runner.session
        states = await session.get_session_state_dict(
            session_id=session_id,
            user_id="default",
            allow_not_exist=True,
        )
        if not states:
            states = await session.get_session_state_dict(
                session_id=session_id,
                allow_not_exist=True,
            )
    except Exception:
        logger.debug("Failed to read session state for plan", exc_info=True)
        return None

    agent_state = states.get("agent", {})
    nb_state = agent_state.get("plan_notebook") or {}
    plan_data = nb_state.get("current_plan")
    if not plan_data:
        return None

    try:
        from agentscope.plan import Plan

        plan = Plan(**plan_data)
        return plan_to_response(plan)
    except Exception:
        logger.debug("Failed to parse plan from session state", exc_info=True)
        return None


@router.get(
    "/current",
    response_model=PlanStateResponse | None,
    summary="Get current plan state",
)
async def get_current_plan(
    request: Request,
    session_id: str | None = None,
) -> PlanStateResponse | None:
    """Return the current plan for the active session.

    Checks the live in-memory cache first (available during agent
    execution), then falls back to the session state file on disk.
    """
    workspace = await _get_workspace(request)
    agent_id = workspace.agent_id

    found, live = get_live_plan(agent_id, session_id=session_id)
    logger.debug(
        "get_current_plan: agent=%s session_id=%r found=%s has_plan=%s",
        agent_id,
        session_id,
        found,
        live is not None,
    )
    if found:
        if live is None:
            return None
        try:
            return PlanStateResponse(**live)
        except Exception:
            logger.debug("Failed to parse live plan cache", exc_info=True)

    if not session_id:
        return None

    return await _plan_from_session_state(workspace, session_id)


@router.get(
    "/config",
    response_model=PlanConfigResponse,
    summary="Get plan config",
)
async def get_plan_config(request: Request) -> PlanConfigResponse:
    workspace = await get_running_config_workspace(
        request,
        action="agent.admin.runtime_config.plan.view",
    )
    require_running_config_editor(request)
    plan_cfg = workspace.config.plan
    if plan_cfg is None:
        plan_cfg = PlanConfig()
    return PlanConfigResponse(
        enabled=plan_cfg.enabled,
        auto_enabled=plan_cfg.auto_enabled,
        auto_execute=plan_cfg.auto_execute,
        complexity_threshold=plan_cfg.complexity_threshold,
    )


@router.put(
    "/config",
    response_model=PlanConfigResponse,
    summary="Update plan config",
)
async def put_plan_config(
    request: Request,
    body: PlanConfigResponse = Body(...),
) -> PlanConfigResponse:
    workspace = await get_running_config_workspace(
        request,
        action="agent.admin.runtime_config.plan.update",
    )
    require_running_config_editor(request)
    if workspace.config.plan is None:
        workspace.config.plan = PlanConfig()
    workspace.config.plan.enabled = body.enabled
    workspace.config.plan.auto_enabled = body.auto_enabled
    workspace.config.plan.auto_execute = body.auto_execute
    workspace.config.plan.complexity_threshold = body.complexity_threshold
    save_agent_config(workspace.agent_id, workspace.config)
    return PlanConfigResponse(
        enabled=workspace.config.plan.enabled,
        auto_enabled=workspace.config.plan.auto_enabled,
        auto_execute=workspace.config.plan.auto_execute,
        complexity_threshold=workspace.config.plan.complexity_threshold,
    )


@router.get(
    "/stream",
    summary="SSE stream for plan updates",
)
async def plan_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events endpoint for real-time plan updates.

    Subscribes to updates for the agent resolved from the request
    context (``X-Agent-Id`` header or active-agent fallback).
    """
    workspace = await _get_workspace(request)
    agent_id = workspace.agent_id

    q = register_sse_client(agent_id)

    async def event_generator():
        try:
            yield 'data: {"type": "connected"}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield (
                        f"data: "
                        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unregister_sse_client(agent_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
