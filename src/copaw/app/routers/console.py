# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from starlette.responses import FileResponse, StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


@router.post(
    "/chat",
    status_code=200,
    summary="Chat with console (streaming response)",
    description="Agent API Request Format. "
    "See https://runtime.agentscope.io/en/protocol.html for "
    "more details.",
)
async def post_console_chat(
    request_data: dict,
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

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/upload", response_model=dict, summary="Upload file for chat")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(..., description="File to attach"),
) -> dict:
    """Save to console channel media_dir."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    media_dir = console_channel.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="File too large (max "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )
    safe_name = _safe_filename(file.filename or "file")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    (media_dir / stored_name).write_bytes(data)
    return {
        "url": stored_name,
        "file_name": safe_name,
        "size": len(data),
    }


@router.get("/files/{agent_id}/{filename}", summary="Serve uploaded chat file")
async def get_console_file(
    request: Request,
    agent_id: str,
    filename: str,
):
    """Serve file from console channel media_dir."""
    from ..agent_context import get_agent_for_request

    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    workspace = await get_agent_for_request(request)
    if workspace.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Not found")
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    media_dir = console_channel.media_dir
    path = (media_dir / filename).resolve()
    try:
        path.relative_to(media_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=filename)


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
