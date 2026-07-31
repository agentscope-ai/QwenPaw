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
    elapsed: float
    offload_remaining: float | None
    kill_remaining: float | None
    extra: dict[str, Any]
    end_state: str | None
    force_cancelled: bool
    max_internal_timeout_secs: float | None
    # Present after backgrounding; console uses this to skip fg completions.
    offload_reason: str | None = None


class ListResponse(BaseModel):
    items: list[ToolCallInfo]
    total: int


class CancelRequest(BaseModel):
    force: bool = False


class ExtendRequest(BaseModel):
    seconds: float | None = Field(default=None, gt=0)
    no_deadline: bool = False
    target: str = Field(
        default="offload",
        pattern="^(offload|kill)$",
    )


# ─── Helpers ───


def _get_coordinator(request: Request) -> Any:
    app_services = getattr(request.app.state, "app_services", None)
    if app_services is None:
        raise HTTPException(503, "Service not available")
    coordinator = getattr(app_services, "tool_coordinator", None)
    if coordinator is None:
        raise HTTPException(503, "ToolCoordinator not available")
    return coordinator


def _safe_log_token(value: str) -> str:
    """Neutralize CR/LF so untrusted IDs cannot forge log lines (CWE-117)."""
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _get_entry(
    coordinator: Any,
    tool_call_id: str,
    session_id: str = "",
) -> Any:
    """Look up by tool_call_id and enforce session scoping.

    When *session_id* is provided it must match ``entry.ctx.session_id``;
    otherwise the call is treated as not found (404). This prevents
    cross-session cancel/offload/stream using only a leaked tool_call_id.
    """
    entry = coordinator.get(tool_call_id)
    if entry is None:
        raise HTTPException(404, "Tool call not found")
    if session_id and entry.ctx.session_id != session_id:
        import logging

        logging.getLogger(__name__).warning(
            "session_id mismatch: url=%s backend=%s tc=%s",
            _safe_log_token(session_id),
            _safe_log_token(entry.ctx.session_id),
            _safe_log_token(tool_call_id),
        )
        raise HTTPException(404, "Tool call not found")
    return entry


def _entry_to_info(entry: Any, coordinator: Any = None) -> ToolCallInfo:
    loop = asyncio.get_running_loop()
    now = loop.time()
    elapsed = now - entry.ctx.started_at
    ctx = entry.ctx

    offload_remaining = None
    if ctx.offload_deadline is not None:
        offload_remaining = max(0.0, ctx.offload_deadline - now)

    kill_remaining = None
    if ctx.kill_deadline is not None:
        kill_remaining = max(0.0, ctx.kill_deadline - now)

    max_internal = None
    if coordinator is not None:
        hook = coordinator.hooks.get(ctx.tool_name)
        if hook is not None:
            max_internal = hook.max_internal_timeout_secs

    return ToolCallInfo(
        tool_call_id=ctx.tool_call_id,
        tool_name=ctx.tool_name,
        session_id=ctx.session_id,
        agent_id=ctx.agent_id,
        status=entry.status.value,
        started_at=ctx.started_at,
        elapsed=elapsed,
        offload_remaining=offload_remaining,
        kill_remaining=kill_remaining,
        extra=ctx.extra,
        end_state=entry.end_state,
        force_cancelled=entry.force_cancelled,
        max_internal_timeout_secs=max_internal,
        offload_reason=(
            ctx.offload_reason.value
            if ctx.offload_reason is not None
            else None
        ),
    )


def _remaining_snapshot(entry: Any) -> dict[str, float | None]:
    """Return current remaining values for an entry's deadlines."""
    loop = asyncio.get_running_loop()
    now = loop.time()
    ctx = entry.ctx
    return {
        "offload_remaining": (
            max(0.0, ctx.offload_deadline - now)
            if ctx.offload_deadline is not None
            else None
        ),
        "kill_remaining": (
            max(0.0, ctx.kill_deadline - now)
            if ctx.kill_deadline is not None
            else None
        ),
    }


# ─── Endpoints ───


@router.get("/{session_id}", response_model=ListResponse)
async def list_calls(
    session_id: str,
    request: Request,
) -> ListResponse:
    coordinator = _get_coordinator(request)
    entries = coordinator.list_entries(session_id=session_id)
    items = [_entry_to_info(e, coordinator) for e in entries]
    return ListResponse(items=items, total=len(items))


@router.get("/{session_id}/{tool_call_id}", response_model=ToolCallInfo)
async def get_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> ToolCallInfo:
    coordinator = _get_coordinator(request)
    entry = _get_entry(coordinator, tool_call_id, session_id)
    return _entry_to_info(entry, coordinator)


@router.post("/{session_id}/{tool_call_id}/offload", status_code=202)
async def offload_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    _get_entry(coordinator, tool_call_id, session_id)
    ok = await coordinator.request_offload(tool_call_id)
    if not ok:
        raise HTTPException(
            409,
            "Cannot offload (not running, or kill window too short; "
            "extend timeout first)",
        )
    return {"status": "accepted", "tool_call_id": tool_call_id}


@router.post("/{session_id}/{tool_call_id}/cancel", status_code=202)
async def cancel_call(
    session_id: str,
    tool_call_id: str,
    request: Request,
    body: CancelRequest | None = None,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    _get_entry(coordinator, tool_call_id, session_id)
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
    entry = _get_entry(coordinator, tool_call_id, session_id)

    if body.target == "kill":
        ok = await coordinator.extend_kill_deadline(
            tool_call_id,
            seconds=body.seconds,
            no_deadline=body.no_deadline,
        )
    else:
        ok = await coordinator.extend_offload_deadline(
            tool_call_id,
            seconds=body.seconds,
            no_deadline=body.no_deadline,
        )

    if not ok:
        raise HTTPException(
            409,
            "Cannot extend deadline (capped or invalid)",
        )

    return {
        "status": "accepted",
        "tool_call_id": tool_call_id,
        **_remaining_snapshot(entry),
    }


@router.get("/{session_id}/{tool_call_id}/output")
async def get_output(
    session_id: str,
    tool_call_id: str,
    request: Request,
) -> dict[str, Any]:
    coordinator = _get_coordinator(request)
    entry = _get_entry(coordinator, tool_call_id, session_id)
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
    entry = _get_entry(coordinator, tool_call_id, session_id)

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
