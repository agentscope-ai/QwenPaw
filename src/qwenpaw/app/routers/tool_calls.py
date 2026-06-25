# -*- coding: utf-8 -*-
"""API routes for tool call lifecycle management."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tool-calls", tags=["tool-calls"])


# ─── Pydantic models ───


class ToolCallInfo(BaseModel):
    tool_call_id: str
    tool_name: str
    session_id: str
    agent_id: str
    status: str
    started_at: float
    deadline: float | None
    elapsed: float
    extra: dict[str, Any]
    end_state: str | None
    force_cancelled: bool
    max_internal_timeout_secs: float | None


class ListResponse(BaseModel):
    items: list[ToolCallInfo]
    total: int


class CancelRequest(BaseModel):
    force: bool = False


class ExtendRequest(BaseModel):
    seconds: float | None = Field(default=None, gt=0)
    no_deadline: bool = False


# ─── Helpers ───


def _get_coordinator(request: Request) -> Any:
    app_services = getattr(request.app.state, "app_services", None)
    if app_services is None:
        raise HTTPException(503, "Service not available")
    coordinator = getattr(app_services, "tool_coordinator", None)
    if coordinator is None:
        raise HTTPException(503, "ToolCoordinator not available")
    return coordinator


def _entry_to_info(entry: Any) -> ToolCallInfo:
    loop = asyncio.get_running_loop()
    elapsed = loop.time() - entry.ctx.started_at
    return ToolCallInfo(
        tool_call_id=entry.ctx.tool_call_id,
        tool_name=entry.ctx.tool_name,
        session_id=entry.ctx.session_id,
        agent_id=entry.ctx.agent_id,
        status=entry.status.value,
        started_at=entry.ctx.started_at,
        deadline=entry.ctx.deadline,
        elapsed=elapsed,
        extra=entry.ctx.extra,
        end_state=entry.end_state,
        force_cancelled=entry.force_cancelled,
        max_internal_timeout_secs=None,
    )


# ─── Endpoints ───


@router.get("/{session_id}", response_model=ListResponse)
async def list_calls(session_id: str, request: Request) -> ListResponse:
    coordinator = _get_coordinator(request)
    entries = coordinator.list_entries(session_id=session_id)
    items = [_entry_to_info(e) for e in entries]
    return ListResponse(items=items, total=len(items))


@router.get("/{session_id}/{tool_call_id}", response_model=ToolCallInfo)
async def get_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> ToolCallInfo:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")
    return _entry_to_info(entry)


@router.post("/{session_id}/{tool_call_id}/offload", status_code=202)
async def offload_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")
    ok = await coordinator.request_offload(tool_call_id)
    if not ok:
        raise HTTPException(409, "Cannot offload (not running)")
    return {"status": "accepted", "tool_call_id": tool_call_id}


@router.post("/{session_id}/{tool_call_id}/cancel", status_code=202)
async def cancel_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
    body: CancelRequest | None = None,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")
    force = body.force if body else False
    ok = await coordinator.cancel(tool_call_id, force=force)
    if not ok:
        raise HTTPException(409, "Cannot cancel")
    return {"status": "accepted", "tool_call_id": tool_call_id}


@router.post(
    "/{session_id}/{tool_call_id}/extend-deadline",
    status_code=202,
)
async def extend_deadline(
    session_id: str,
    tool_call_id: str,
    request: Request,
    body: ExtendRequest,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")
    ok = await coordinator.extend_deadline(
        tool_call_id,
        seconds=body.seconds,
        no_deadline=body.no_deadline,
    )
    if not ok:
        raise HTTPException(
            409,
            "Cannot extend deadline (capped or invalid)",
        )
    return {"status": "accepted", "tool_call_id": tool_call_id}


@router.get("/{session_id}/{tool_call_id}/output")
async def get_output(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")
    content_blocks = []
    if entry.final_response and entry.final_response.content:
        for block in entry.final_response.content:
            content_blocks.append(block.model_dump())
    return {
        "tool_call_id": tool_call_id,
        "is_closed": entry.stream.is_closed,
        "final_state": entry.end_state,
        "content": content_blocks,
    }


@router.get("/{session_id}/{tool_call_id}/stream")
async def stream_output(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> StreamingResponse:
    coordinator = _get_coordinator(request)
    entry = coordinator.get(tool_call_id)
    if entry is None or entry.ctx.session_id != session_id:
        raise HTTPException(404, "Tool call not found")

    async def _generate():
        async for chunk in entry.stream.subscribe():
            data = {"type": "chunk"}
            if hasattr(chunk, "model_dump"):
                data["data"] = chunk.model_dump()
            else:
                data["data"] = str(chunk)
            yield f"data: {json.dumps(data)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
    )
