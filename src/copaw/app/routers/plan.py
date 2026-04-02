# -*- coding: utf-8 -*-
"""Plan API endpoints for real-time plan visualization and management."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..agent_context import get_agent_for_request
from ...plan.schemas import (
    CreatePlanRequest,
    FinishPlanRequest,
    PlanConfigUpdateRequest,
    PlanStateResponse,
    PlanSummary,
    RevisePlanRequest,
)
from ...plan.schemas import plan_to_response, plan_to_summary
from ...plan.broadcast import register_sse_client, unregister_sse_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


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
    "/create",
    response_model=PlanStateResponse,
    summary="Manually create a plan",
)
async def create_plan(body: CreatePlanRequest, request: Request):
    """Create a new plan with the given subtasks."""
    nb, _ = await _get_plan_notebook(request)

    from agentscope.plan import SubTask

    subtasks = [
        SubTask(
            name=st.name,
            description=st.description,
            expected_outcome=st.expected_outcome,
        )
        for st in body.subtasks
    ]
    await nb.create_plan(
        name=body.name,
        description=body.description,
        expected_outcome=body.expected_outcome,
        subtasks=subtasks,
    )
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


@router.get(
    "/history",
    response_model=list[PlanSummary],
    summary="List historical plans",
)
async def get_plan_history(request: Request):
    """List all historical plans from storage."""
    nb, _ = await _get_plan_notebook(request)
    plans = await nb.storage.get_plans()
    return [plan_to_summary(p) for p in plans]


@router.post(
    "/recover/{plan_id}",
    response_model=PlanStateResponse,
    summary="Recover a historical plan",
)
async def recover_plan(plan_id: str, request: Request):
    """Recover a historical plan by ID."""
    nb, _ = await _get_plan_notebook(request)
    await nb.recover_historical_plan(plan_id=plan_id)
    # recover_historical_plan leaves current_plan unchanged when *plan_id*
    # is missing; do not mutate an unrelated active plan in that case.
    if nb.current_plan is None or nb.current_plan.id != plan_id:
        raise HTTPException(
            status_code=404,
            detail=f"Plan '{plan_id}' not found in storage",
        )
    # Historical plans are stored as done/abandoned; reset so the UI treats
    # the restored plan as active and subtasks can be re-run from todo.
    plan = nb.current_plan
    plan.state = "todo"
    plan.outcome = None
    plan.finished_at = None
    for st in plan.subtasks:
        st.state = "todo"
        st.outcome = None
        st.finished_at = None
    await nb._trigger_plan_change_hooks()
    return plan_to_response(nb.current_plan)


@router.delete(
    "/history/{plan_id}",
    summary="Delete a historical plan",
)
async def delete_historical_plan(plan_id: str, request: Request):
    """Remove a plan from storage by ID (does not affect current_plan)."""
    nb, _ = await _get_plan_notebook(request)
    await nb.storage.delete_plan(plan_id)
    return {"success": True}


@router.get(
    "/stream",
    summary="SSE stream for real-time plan updates",
)
async def stream_plan_updates(request: Request):
    """Open an SSE connection that emits plan_update events."""
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
