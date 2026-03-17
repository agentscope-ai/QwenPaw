# -*- coding: utf-8 -*-
"""Console APIs: push messages and chat."""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from ..agent_context import get_agent_for_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract run_key (ChatSpec.id), session_id, and native payload.

    run_key must be ChatSpec.id (chat_id) so it matches list_chats/get_chat.
    """
    if isinstance(request_data, AgentRequest):
        channel_id = request_data.channel or "console"
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = (
            list(request_data.input[0].content) if request_data.input else []
        )
    else:
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = request_data.get("session_id", "default")
        input_data = request_data.get("input", [])
        content_parts = []
        for content_part in input_data:
            if hasattr(content_part, "content"):
                content_parts.extend(list(content_part.content or []))
            elif isinstance(content_part, dict) and "content" in content_part:
                content_parts.extend(content_part["content"] or [])

    native_payload = {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "content_parts": content_parts,
        "meta": {
            "session_id": session_id,
            "user_id": sender_id,
        },
    }
    return native_payload


@router.post(
    "/chat",
    status_code=200,
    summary="Chat with console (streaming response)",
    description="Agent API Request Format. See runtime.agentscope.io. "
    "Use body.reconnect=true to attach to a running stream.",
)
async def post_console_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response. Run continues in background after disconnect.
    Stop via POST /console/chat/stop. Reconnect with body.reconnect=true.
    """
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    try:
        native_payload = _extract_session_and_payload(request_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name = "New Chat"
    if len(native_payload["content_parts"]) > 0:
        content = native_payload["content_parts"][0]
        if content:
            name = content.text[:10]
        else:
            name = "Media Message"
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        native_payload["sender_id"],
        native_payload["channel_id"],
        name=name,
    )
    tracker = workspace.task_tracker

    is_reconnect = False
    if isinstance(request_data, dict):
        is_reconnect = request_data.get("reconnect") is True

    if is_reconnect:
        queue = await tracker.attach(chat.id)
        if queue is None:
            raise HTTPException(
                status_code=404,
                detail="No running chat for this session",
            )
    else:
        queue, _ = await tracker.attach_or_start(
            chat.id,
            native_payload,
            console_channel.stream_one,
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event_data in tracker.stream_from_queue(queue):
                yield event_data
        except Exception as e:
            logger.exception("Console chat stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/chat/stop",
    status_code=200,
    summary="Stop running console chat",
)
async def post_console_chat_stop(
    request: Request,
    chat_id: str = Query(..., description="Chat id (ChatSpec.id) to stop"),
) -> dict:
    """Stop the running chat. Only stops when called."""
    workspace = await get_agent_for_request(request)
    stopped = await workspace.task_tracker.request_stop(chat_id)
    return {"stopped": stopped}


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
