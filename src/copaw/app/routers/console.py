# -*- coding: utf-8 -*-
"""Console APIs: push messages and chat."""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


@router.post(
    "/chat",
    status_code=200,
    summary="Chat with console (streaming response)",
    description="Agent API Request Format. "
    "See https://runtime.agentscope.io/en/protocol.html for "
    "more details.",
)
async def post_console_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Accept a user message and stream the agent response.

    Accepts AgentRequest or dict, builds native payload, and streams events
    via channel.stream_one().
    """

    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)

    # Extract channel info from request
    if isinstance(request_data, AgentRequest):
        channel_id = request_data.channel or "console"
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = (
            list(request_data.input[0].content) if request_data.input else []
        )
    else:
        # Dict format - extract from request body
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = request_data.get("session_id", "default")
        input_data = request_data.get("input", [])

        # Extract content from input array
        content_parts = []
        if input_data and len(input_data) > 0:
            last_msg = input_data[-1]
            if hasattr(last_msg, "content"):
                content_parts = list(last_msg.content or [])
            elif isinstance(last_msg, dict) and "content" in last_msg:
                content_parts = last_msg["content"] or []

    #
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    # Build native payload
    native_payload = {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "content_parts": content_parts,
        "meta": {
            "session_id": session_id,
            "user_id": sender_id,
        },
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event_data in console_channel.stream_one(native_payload):
                yield event_data
        except Exception as e:
            logger.exception("Console chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/push-messages")
async def get_push_messages(
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages. Without session_id: recent messages
    (all sessions, last 60s), not consumed so every tab sees them.
    """
    from ..console_push_store import get_recent, take

    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()
    return {"messages": messages}
