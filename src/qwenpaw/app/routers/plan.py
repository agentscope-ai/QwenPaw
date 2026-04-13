# -*- coding: utf-8 -*-
"""Plan API endpoints for real-time plan visualization and management."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..agent_context import get_agent_for_request
from ..auth import has_registered_users, is_auth_enabled
from ...plan.schemas import (
    FinishPlanRequest,
    PlanConfigUpdateRequest,
    PlanStateResponse,
    RevisePlanRequest,
)
from ...plan.schemas import plan_to_response
from ...plan.broadcast import register_sse_client, unregister_sse_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])

# Short-lived, single-use tickets for plan SSE (EventSource cannot send
# Authorization headers; avoids putting long-lived JWTs in query strings).
_SSE_TICKET_TTL_SECONDS = 60


@dataclass
class _SseTicket:
    agent_id: str
    created_at: float
    used: bool = False


_sse_tickets: dict[str, _SseTicket] = {}


def _purge_expired_sse_tickets() -> None:
    now = time.time()
    expired = [
        k
        for k, v in _sse_tickets.items()
        if v.used or (now - v.created_at) > _SSE_TICKET_TTL_SECONDS
    ]
    for k in expired:
        _sse_tickets.pop(k, None)


def _issue_sse_ticket(agent_id: str) -> str:
    _purge_expired_sse_tickets()
    raw = secrets.token_urlsafe(32)
    _sse_tickets[raw] = _SseTicket(
        agent_id=agent_id,
        created_at=time.time(),
    )
    return raw


def _consume_sse_ticket(raw: str) -> Optional[str]:
    """Return *agent_id* if *raw* is valid, else ``None``."""
    _purge_expired_sse_tickets()
    rec = _sse_tickets.get(raw)
    if rec is None:
        return None
    if rec.used:
        return None
    if (time.time() - rec.created_at) > _SSE_TICKET_TTL_SECONDS:
        _sse_tickets.pop(raw, None)
        return None
    rec.used = True
    return rec.agent_id


async def _get_plan_notebook(request: Request):
    """Resolve the PlanNotebook for the current request's agent."""
    workspace = await get_agent_for_request(request)
    nb = workspace.plan_notebook
    if nb is None:
        raise HTTPException(
            status_code=404,
            detail="Plan mode is not enabled for this agent",
        )
    return nb, workspace


@router.get(
    "/current",
    response_model=Optional[PlanStateResponse],
    summary="Get current plan state",
)
async def get_current_plan(request: Request):
    """Return the current plan state, or null if no plan is active."""
    workspace = await get_agent_for_request(request)
    nb = workspace.plan_notebook
    if nb is None or nb.current_plan is None:
        return None
    return plan_to_response(nb.current_plan)


@router.post(
    "/revise",
    response_model=PlanStateResponse,
    summary="Revise the current plan",
)
async def revise_plan(body: RevisePlanRequest, request: Request):
    """Revise the current plan by adding, revising, or deleting a subtask."""
    nb, _ = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to revise",
        )

    from agentscope.plan import SubTask

    subtask = None
    if body.subtask is not None:
        subtask = SubTask(
            name=body.subtask.name,
            description=body.subtask.description,
            expected_outcome=body.subtask.expected_outcome,
        )
    await nb.revise_current_plan(
        subtask_idx=body.subtask_idx,
        action=body.action,
        subtask=subtask,
    )
    return plan_to_response(nb.current_plan)


@router.post(
    "/finish",
    summary="Finish or abandon the current plan",
)
async def finish_plan(body: FinishPlanRequest, request: Request):
    """Finish or abandon the current plan."""
    nb, _ = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to finish",
        )
    await nb.finish_plan(state=body.state, outcome=body.outcome)
    return {"success": True}


@router.post(
    "/stream/ticket",
    summary="Issue a short-lived SSE ticket for plan stream",
)
async def issue_plan_stream_ticket(request: Request):
    """Return a single-use ticket for ``GET /plan/stream``.

    Call this with a normal ``Authorization: Bearer`` header; the ticket
    is bound to the resolved agent and must be used once within
    ``_SSE_TICKET_TTL_SECONDS``.
    """
    workspace = await get_agent_for_request(request)
    ticket = _issue_sse_ticket(workspace.agent_id)
    return {"ticket": ticket}


@router.get(
    "/stream",
    summary="SSE stream for real-time plan updates",
)
async def stream_plan_updates(request: Request):
    """Open an SSE connection that emits plan_update events."""
    auth_required = is_auth_enabled() and has_registered_users()
    ticket_raw = request.query_params.get("ticket")
    if auth_required:
        if not ticket_raw:
            raise HTTPException(
                status_code=401,
                detail="Missing SSE ticket; POST /plan/stream/ticket first",
            )
        bound_agent_id = _consume_sse_ticket(ticket_raw)
        if bound_agent_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired SSE ticket",
            )
        workspace = await get_agent_for_request(
            request,
            agent_id=bound_agent_id,
        )
    else:
        workspace = await get_agent_for_request(request)
    agent_id = workspace.agent_id

    q = register_sse_client(agent_id)

    async def _event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=60)
                    data = json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                    yield f"event: plan_update\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

                if await request.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            unregister_sse_client(agent_id, q)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/config",
    summary="Get plan configuration",
)
async def get_plan_config(request: Request):
    """Get the plan configuration for the current agent."""
    workspace = await get_agent_for_request(request)
    config = workspace.config
    return config.plan.model_dump()


@router.put(
    "/config",
    summary="Update plan configuration",
)
async def update_plan_config(
    body: PlanConfigUpdateRequest,
    request: Request,
):
    """Update the plan configuration and activate/deactivate
    the PlanNotebook dynamically (no restart required)."""
    from ...config.config import (
        PlanConfig,
        load_agent_config,
        save_agent_config,
    )

    workspace = await get_agent_for_request(request)
    agent_id = workspace.agent_id

    agent_config = load_agent_config(agent_id)
    was_enabled = agent_config.plan.enabled
    agent_config.plan = PlanConfig(**body.model_dump())
    save_agent_config(agent_id, agent_config)

    if body.enabled and not was_enabled:
        await workspace.activate_plan_notebook()
    elif not body.enabled and was_enabled:
        await workspace.deactivate_plan_notebook()

    return agent_config.plan.model_dump()


@router.post(
    "/confirm",
    summary="Confirm and start executing the current plan",
)
async def confirm_plan(request: Request):
    """Mark the first todo subtask as in_progress so the agent
    begins execution on the next user message."""
    nb, _ = await _get_plan_notebook(request)
    if nb.current_plan is None:
        raise HTTPException(
            status_code=400,
            detail="No active plan to confirm",
        )

    plan = nb.current_plan
    for idx, st in enumerate(plan.subtasks):
        if st.state == "todo":
            await nb.update_subtask_state(idx, "in_progress")
            return {
                "confirmed": True,
                "started_subtask_idx": idx,
            }

    return {"confirmed": True, "started_subtask_idx": None}
