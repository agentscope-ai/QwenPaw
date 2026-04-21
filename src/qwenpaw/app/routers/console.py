# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import AsyncGenerator, Union

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from ...utils.logging import LOG_FILE_PATH
from ..agent_context import get_agent_for_request


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DEBUG_LOG_LINES = 1000


class PendingApprovalResponse(BaseModel):
    request_id: str = ""
    tool_name: str = ""
    operation_preview: str = ""
    result_summary: str = ""
    findings_count: int = 0
    created_at: float = 0.0


class ApprovalActionRequest(BaseModel):
    session_id: str = Field(default="")
    action: str = Field(default="approve")
    request_id: str | None = None
    user_id: str | None = None
    channel: str | None = None


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract run_key (ChatSpec.id), session_id, and native payload.

    run_key must be ChatSpec.id (chat_id) so it matches list_chats/get_chat.
    """
    if isinstance(request_data, AgentRequest):
        channel_id = getattr(request_data, "channel", None) or "console"
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


def _tail_text_file(
    path: Path,
    *,
    lines: int = 200,
    max_bytes: int = 512 * 1024,
) -> str:
    """Read the last N lines from a text file with bounded memory."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        if size == 0:
            return ""
        with open(path, "rb") as f:
            if size <= max_bytes:
                data = f.read()
            else:
                f.seek(max(size - max_bytes, 0))
                data = f.read()
        text = data.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        logger.exception("Failed to read backend debug log file")
        return ""


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
            return
    else:
        queue, _ = await tracker.attach_or_start(
            chat.id,
            native_payload,
            console_channel.stream_one,
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        # Hold iterator so finally can aclose(); guarantees stream_from_queue's
        # finally (detach_subscriber) on client abort / generator teardown.
        stream_it = tracker.stream_from_queue(queue, chat.id)
        try:
            try:
                async for event_data in stream_it:
                    yield event_data
            except Exception as e:
                logger.exception("Console chat stream error")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            await stream_it.aclose()

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


@router.post("/upload", response_model=dict, summary="Upload file for chat")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(..., description="File to attach"),
) -> dict:
    """Save to console channel media_dir."""

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

    path = (media_dir / stored_name).resolve()
    path.write_bytes(data)
    return {
        "url": path,
        "file_name": safe_name,
        "size": len(data),
    }


@router.get(
    "/debug/backend-logs",
    response_model=dict,
    summary="Read backend daemon logs for debug page",
)
async def get_backend_debug_logs(
    lines: int = Query(
        200,
        ge=20,
        le=MAX_DEBUG_LOG_LINES,
        description="Number of trailing log lines to return",
    ),
) -> dict:
    """Return the tail of the project log file for the debug UI."""
    log_path = LOG_FILE_PATH.resolve()
    try:
        st = log_path.stat()
        return {
            "path": str(log_path),
            "exists": True,
            "lines": lines,
            "updated_at": st.st_mtime,
            "size": st.st_size,
            "content": _tail_text_file(log_path, lines=lines),
        }
    except FileNotFoundError:
        return {
            "path": str(log_path),
            "exists": False,
            "lines": lines,
            "updated_at": None,
            "size": 0,
            "content": "",
        }


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


@router.get(
    "/approvals/pending",
    response_model=PendingApprovalResponse,
    summary="Get pending approval for current session",
)
async def get_pending_approval(
    session_id: str = Query(..., description="Session id"),
) -> PendingApprovalResponse:
    from ..approvals import get_approval_service

    pending = await get_approval_service().get_pending_by_session(session_id)
    if pending is None:
        return PendingApprovalResponse()

    operation_preview = ""
    extra = pending.extra if isinstance(pending.extra, dict) else {}
    tool_call = extra.get("tool_call") if isinstance(extra, dict) else None
    if isinstance(tool_call, dict):
        tool_input = tool_call.get("input", {})
        if isinstance(tool_input, dict):
            if (
                pending.tool_name == "execute_shell_command"
                and isinstance(tool_input.get("command"), str)
            ):
                operation_preview = tool_input["command"].strip()
            elif (
                pending.tool_name in {"write_file", "edit_file", "append_file"}
                and isinstance(tool_input.get("path"), str)
            ):
                operation_preview = (
                    f"{pending.tool_name} -> {tool_input['path'].strip()}"
                )
            elif (
                pending.tool_name == "browser_cdp"
                and isinstance(tool_input.get("action"), str)
            ):
                operation_preview = (
                    f"browser_cdp action={tool_input['action']}"
                )
            elif tool_input:
                preview_items = []
                for key, value in list(tool_input.items())[:3]:
                    val = str(value).strip().replace("\n", " ")
                    if len(val) > 120:
                        val = val[:117] + "..."
                    preview_items.append(f"{key}={val}")
                operation_preview = ", ".join(preview_items)

    return PendingApprovalResponse(
        request_id=pending.request_id,
        tool_name=pending.tool_name,
        operation_preview=operation_preview,
        result_summary=pending.result_summary,
        findings_count=pending.findings_count,
        created_at=pending.created_at,
    )


async def _dispatch_approval_command(
    request: Request,
    *,
    session_id: str,
    user_id: str,
    channel: str,
    command_text: str,
) -> None:
    """Dispatch '/approve' or '/deny' through the existing console path."""
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    native_payload = {
        "channel_id": channel,
        "sender_id": user_id,
        "content_parts": [{"type": "text", "text": command_text}],
        "meta": {
            "session_id": session_id,
            "user_id": user_id,
        },
    }
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        user_id,
        channel,
        name=command_text,
    )
    queue, is_new = await workspace.task_tracker.attach_or_start(
        chat.id,
        native_payload,
        console_channel.stream_one,
    )
    if not is_new:
        # If a previous run is still active, attach_or_start ignores payload.
        # Wait for the current run to finish, then start a fresh run for
        # this approval command.
        await workspace.task_tracker.detach_subscriber(chat.id, queue)

        for _ in range(40):
            status = await workspace.task_tracker.get_status(chat.id)
            if status != "running":
                break
            await asyncio.sleep(0.1)

        queue, _ = await workspace.task_tracker.attach_or_start(
            chat.id,
            native_payload,
            console_channel.stream_one,
        )

    async def _drain_queue() -> None:
        stream_it = workspace.task_tracker.stream_from_queue(queue, chat.id)
        try:
            async for _ in stream_it:
                pass
        finally:
            await stream_it.aclose()

    asyncio.create_task(_drain_queue())


@router.post(
    "/approvals/action",
    response_model=dict,
    summary="Resolve pending approval via frontend button",
)
async def post_approval_action(
    body: ApprovalActionRequest,
    request: Request,
) -> dict:
    action = (body.action or "").strip().lower()
    if action not in {"approve", "deny"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    from ..approvals import get_approval_service

    svc = get_approval_service()
    pending = await svc.get_pending_by_session(session_id)
    if pending is None:
        return {"ok": False, "reason": "no_pending"}
    if body.request_id and body.request_id != pending.request_id:
        return {"ok": False, "reason": "stale_request"}

    command_text = "/approve" if action == "approve" else "/deny"
    await _dispatch_approval_command(
        request,
        session_id=session_id,
        user_id=body.user_id or pending.user_id or "default",
        channel=body.channel or pending.channel or "console",
        command_text=command_text,
    )
    return {"ok": True}
