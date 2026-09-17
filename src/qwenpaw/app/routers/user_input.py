# -*- coding: utf-8 -*-
"""Structured user input API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import StreamingResponse

from ...runtime_status.scope import request_user_id

from ...user_input.broadcast import (
    register_sse_client,
    unregister_sse_client,
)
from ...user_input.schemas import UserInputAnswer, UserInputRequest
from ...user_input.service import get_user_input_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user-input", tags=["user-input"])


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


@router.get(
    "/pending",
    response_model=UserInputRequest | None,
    summary="Get pending structured user input request",
)
async def get_pending_user_input(
    request: Request,
    session_id: str,
) -> UserInputRequest | None:
    """Return the oldest pending request for the current chat session."""
    workspace = await _get_workspace(request)
    return await get_user_input_service().get_pending(
        agent_id=workspace.agent_id,
        session_id=session_id,
        user_id=request_user_id(request),
    )


@router.post(
    "/{request_id}/answer",
    response_model=UserInputRequest,
    summary="Answer a structured user input request",
)
async def answer_user_input(
    request: Request,
    request_id: str,
    body: UserInputAnswer = Body(...),
) -> UserInputRequest:
    """Resolve a pending structured user input request."""
    workspace = await _get_workspace(request)
    resolved = await get_user_input_service().answer_request(
        request_id,
        body,
        agent_id=workspace.agent_id,
        user_id=request_user_id(request),
    )
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail="User input request not found or already resolved",
        )
    return resolved


@router.get(
    "/stream",
    summary="SSE stream for structured user input updates",
)
async def user_input_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events endpoint for user-input request updates."""
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
