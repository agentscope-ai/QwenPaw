# -*- coding: utf-8 -*-
"""Console APIs: push messages and chat."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncGenerator, Union
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from starlette.responses import StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import (
    AgentRequest,
    ContentType,
    FileContent,
    TextContent,
)

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

MAX_CONSOLE_UPLOAD_SIZE = 100 * 1024 * 1024


def _sanitize_upload_filename(filename: str | None) -> str:
    """Return a basename-only filename safe for local storage."""
    safe_name = Path(filename or "upload").name.strip()
    return safe_name or "upload"


async def _save_console_upload(request: Request, file: UploadFile) -> Path:
    """Persist a browser-uploaded file into the console uploads folder."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    safe_name = _sanitize_upload_filename(file.filename)
    original_path = Path(safe_name)
    target_dir = WORKING_DIR / "media" / "console" / workspace.agent_id
    target_dir.mkdir(parents=True, exist_ok=True)

    target_name = (
        f"{original_path.stem or 'upload'}-{uuid4().hex}"
        f"{original_path.suffix}"
    )
    target_path = target_dir / target_name

    size = 0
    try:
        with target_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_CONSOLE_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Uploaded file is too large; "
                            "maximum size is 100MB"
                        ),
                    )
                out.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return target_path


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

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/chat-upload",
    status_code=200,
    summary="Upload a file and chat with console",
    description=(
        "Accept a browser-uploaded file, persist it locally, then stream "
        "the agent response as an SSE event stream."
    ),
)
async def post_console_chat_upload(
    request: Request,
    file: UploadFile = File(..., description="File uploaded from the browser"),
    session_id: str = Form("default"),
    user_id: str = Form("default"),
    channel: str = Form("console"),
    text: str = Form(""),
) -> StreamingResponse:
    """Bridge browser file uploads into console chat file content parts."""
    from ..agent_context import get_agent_for_request

    saved_path = await _save_console_upload(request, file)
    display_name = _sanitize_upload_filename(file.filename) or saved_path.name
    prompt_text = (text or "").strip() or (
        f"Please process the uploaded file: {display_name}"
    )

    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    native_payload = {
        "channel_id": channel or "console",
        "sender_id": user_id or "default",
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=prompt_text),
            FileContent(type=ContentType.FILE, file_url=str(saved_path)),
        ],
        "meta": {
            "session_id": session_id or "default",
            "user_id": user_id or "default",
        },
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event_data in console_channel.stream_one(native_payload):
                yield event_data
        except Exception as e:
            logger.exception("Console chat upload stream error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
