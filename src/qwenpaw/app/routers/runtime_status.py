# -*- coding: utf-8 -*-
"""Runtime status API endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from ...runtime_status.scope import request_user_id

from ...runtime_status.broadcast import (
    get_runtime_status,
    register_sse_client,
    unregister_sse_client,
)

router = APIRouter(prefix="/runtime-status", tags=["runtime-status"])


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


@router.get("/current")
async def get_current_runtime_status(
    request: Request,
    session_id: str,
) -> dict | None:
    workspace = await _get_workspace(request)
    return get_runtime_status(
        workspace.agent_id, session_id, user_id=request_user_id(request)
    )


@router.get("/stream")
async def runtime_status_stream(request: Request) -> StreamingResponse:
    workspace = await _get_workspace(request)
    agent_id = workspace.agent_id
    user_id = request_user_id(request)
    q = register_sse_client(agent_id, user_id=user_id)

    async def event_generator():
        try:
            yield 'data: {"type": "connected"}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield (f"data: " f"{json.dumps(payload, ensure_ascii=False)}\n\n")
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unregister_sse_client(agent_id, q, user_id=user_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
