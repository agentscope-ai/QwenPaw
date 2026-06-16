# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Union

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from ...security.audit_foundation import (
    classify_lease_prompt,
    evaluate_high_risk_tool_boundary,
    extract_prompt_security_context,
    lock_mode_required,
    preflight_sensitive_action_recovery,
    project_security_rejection_record,
    read_security_center_recovery_state,
    write_reconnect_gap_proof_record,
    write_lease_heartbeat_record,
    write_lockdown_record,
    write_restored_model_access_record,
    write_security_rejection_record,
)
from ...security.rule_integrity_bridge import rule_integrity_lockdown_active
from ...utils.logging import LOG_FILE_PATH
from ..agent_context import get_agent_for_request
from ..approvals import get_approval_service
from ..runner.title_generator import generate_and_update_title
from ..utils import check_upload_size


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


class MarkInboxReadRequest(BaseModel):
    event_ids: list[str] = []
    all: bool = False


MAX_DEBUG_LOG_LINES = 1000


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


def _extract_placeholder_name(content_parts: list) -> tuple[str, str]:
    """Return ``(placeholder_name, first_user_text)`` for a new chat.

    The placeholder name shows up in the session drawer immediately while a
    background task asks the model for a real title. Content shapes match
    ``channels/base.py::_extract_chat_name``: dict blocks like
    ``{"type": "text", "text": "..."}``, raw strings, and objects with a
    ``.text`` attribute. Anything else (audio/image/file blocks) is treated
    as media and gets the generic "Media Message" placeholder.
    """
    if not content_parts:
        return "New Chat", ""
    content = content_parts[0]
    if not content:
        return "Media Message", ""
    if isinstance(content, str):
        first_text = content
    elif isinstance(content, dict):
        text = content.get("text", "")
        first_text = text if isinstance(text, str) else ""
    elif hasattr(content, "text"):
        first_text = content.text or ""
    else:
        first_text = ""
    if not first_text:
        return "Media Message", ""
    return first_text[:10], first_text


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


def _single_event_response(
    *,
    status_code: int,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Response:
    content = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    response_headers = {
        "Cache-Control": "no-cache",
        "Connection": "close",
        "Content-Length": str(len(content.encode("utf-8"))),
    }
    if headers:
        response_headers.update(headers)
    return Response(
        content=content,
        media_type="text/event-stream",
        status_code=status_code,
        headers=response_headers,
    )


def _extract_prompt_text(content_parts: list[Any]) -> str:
    for content in content_parts:
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
            continue
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            continue
        text = getattr(content, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


async def _maybe_handle_security_scenario(
    *,
    prompt_text: str,
    native_payload: dict[str, Any],
) -> Response | None:
    if not prompt_text:
        return None

    session_id = str(native_payload["meta"].get("session_id") or "default")
    user_id = str(native_payload["sender_id"] or "default")
    channel_id = str(native_payload["channel_id"] or "console")
    lease_prompt_kind = classify_lease_prompt(prompt_text)
    if lease_prompt_kind == "normal_reconnect_baseline":
        payload = await write_lease_heartbeat_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            prompt_text=prompt_text,
            ttl_seconds=120,
        )
        return _single_event_response(status_code=200, payload=payload)
    if lease_prompt_kind == "normal_reconnect_access":
        recovery_state = await read_security_center_recovery_state(
            session_id=session_id,
        )
        if recovery_state.get("recovery_required") is True or str(recovery_state.get("trust_state") or "ALIGNED") not in {"ALIGNED", "TRUSTED"}:
            payload = await write_lockdown_record(
                session_id=session_id,
                user_id=user_id,
                channel=channel_id,
                tool_name="model_access_resume_tool",
                prompt_text=prompt_text,
            )
            return _single_event_response(status_code=423, payload=payload)
        payload = await write_restored_model_access_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            prompt_text=prompt_text,
        )
        return _single_event_response(status_code=200, payload=payload)
    if lease_prompt_kind == "warmup":
        payload = await write_lease_heartbeat_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            prompt_text=prompt_text,
        )
        return _single_event_response(status_code=200, payload=payload)
    if lease_prompt_kind == "rejoin":
        payload = await write_lockdown_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            tool_name="model_access_resume_tool",
            prompt_text=prompt_text,
        )
        return _single_event_response(status_code=423, payload=payload)
    if lease_prompt_kind == "restored":
        recovery_state = await read_security_center_recovery_state(
            session_id=session_id,
        )
        if recovery_state.get("recovery_required") is True or str(recovery_state.get("trust_state") or "") not in {"ALIGNED", "TRUSTED"}:
            await write_reconnect_gap_proof_record(
                session_id=session_id,
                user_id=user_id,
                channel=channel_id,
                prompt_text=prompt_text,
            )
            recovery_state = await preflight_sensitive_action_recovery(
                session_id=session_id,
                user_id=user_id,
                tool_name="model_access_resume_tool",
                prompt_text=prompt_text,
            )
            if not recovery_state:
                recovery_state = await read_security_center_recovery_state(
                    session_id=session_id,
                )
        if recovery_state.get("recovery_required") is True or str(recovery_state.get("trust_state") or "") not in {"ALIGNED", "TRUSTED"}:
            payload = await write_lockdown_record(
                session_id=session_id,
                user_id=user_id,
                channel=channel_id,
                tool_name="model_access_resume_tool",
                prompt_text=prompt_text,
            )
            return _single_event_response(status_code=423, payload=payload)
        payload = await write_restored_model_access_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            prompt_text=prompt_text,
        )
        return _single_event_response(status_code=200, payload=payload)

    context = extract_prompt_security_context(
        prompt_text,
        fallback_employee_id=user_id,
        fallback_tool_name="",
    )
    tool_name = context["high_risk_tool_name"]

    if tool_name:
        boundary_decision = evaluate_high_risk_tool_boundary(
            session_id=session_id,
            user_id=user_id,
            tool_name=tool_name,
            prompt_text=prompt_text,
            delegated_agent_name=context["delegated_agent_name"] or "console_security_gate",
            third_party_plugin_name=context["third_party_plugin_name"] or "security_center_backend_api",
            user_confirmation_phrase=context["user_confirmation_phrase"],
        )
    else:
        boundary_decision = {"action": None, "guard_result": None, "tool_call": None}

    if boundary_decision["action"] == "auto_deny" and tool_name:
        payload = await write_security_rejection_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            tool_name=tool_name,
            prompt_text=prompt_text,
            tool_call_id=str((boundary_decision["tool_call"] or {}).get("id") or ""),
            guard_result=boundary_decision["guard_result"],
        )
        asyncio.create_task(project_security_rejection_record(payload))
        return _single_event_response(
            status_code=403,
            payload=payload,
            headers={
                "X-Security-Rejection-Nonce": payload["security_rejection_nonce"],
            },
        )

    recovery_gate = await preflight_sensitive_action_recovery(
        session_id=session_id,
        user_id=user_id,
        tool_name=tool_name,
        prompt_text=prompt_text,
    ) if tool_name else {}

    if tool_name and rule_integrity_lockdown_active():
        return _single_event_response(
            status_code=423,
            payload={
                "message": (
                    "Built-in security configuration integrity check failed; "
                    "all rules are disabled while auto-repair is in progress."
                ),
                "rules_disabled": True,
                "tool_name": tool_name,
            },
        )

    if tool_name and (lock_mode_required() or recovery_gate.get("recovery_required") is True):
        payload = await write_lockdown_record(
            session_id=session_id,
            user_id=user_id,
            channel=channel_id,
            tool_name=tool_name,
            prompt_text=prompt_text,
        )
        return _single_event_response(status_code=423, payload=payload)

    if boundary_decision["action"] == "needs_approval" and tool_name:
        approval_service = get_approval_service()
        tool_call = boundary_decision["tool_call"]
        pending = await approval_service.create_pending(
            session_id=session_id,
            root_session_id=session_id,
            owner_agent_id=context["delegated_agent_name"] or "console_security_gate",
            user_id=user_id,
            channel="local_console",
            agent_id=context["delegated_agent_name"] or "console_security_gate",
            tool_name=tool_name,
            result=boundary_decision["guard_result"],
            extra={
                "tool_call": tool_call,
                "request_prompt": prompt_text,
            },
        )
        return _single_event_response(
            status_code=200,
            payload={
                "status": "approval_pending",
                "request_id": pending.request_id,
                "tool_name": tool_name,
            },
        )

    return None


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
) -> Response:
    """Stream agent response. Run continues in background after disconnect.
    Stop via POST /console/chat/stop. Reconnect with body.reconnect=true.
    """
    try:
        native_payload = _extract_session_and_payload(request_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    prompt_text = _extract_prompt_text(native_payload["content_parts"])
    security_response = await _maybe_handle_security_scenario(
        prompt_text=prompt_text,
        native_payload=native_payload,
    )
    if security_response is not None:
        return security_response
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name, first_text = _extract_placeholder_name(
        native_payload["content_parts"],
    )
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        native_payload["sender_id"],
        native_payload["channel_id"],
        name=name,
    )
    tracker = workspace.task_tracker

    # Kick off an LLM-backed title generation in the background when the chat
    # was just created with the truncated placeholder. This runs detached so
    # the streaming response is never blocked by title generation latency.
    if first_text and chat.name == name:
        asyncio.create_task(
            generate_and_update_title(
                workspace=workspace,
                chat_id=chat.id,
                user_message=first_text,
                placeholder_name=name,
            ),
        )

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
    logger.debug("[STOP API] Received stop request for chat_id=%s", chat_id)
    workspace = await get_agent_for_request(request)

    # Try to stop with the provided chat_id first
    logger.debug(
        "[STOP API] Got workspace, calling task_tracker.request_stop...",
    )
    stopped = await workspace.task_tracker.request_stop(chat_id)

    # If not found, the chat_id might be a session_id (timestamp)
    # Try to resolve it to the actual chat UUID
    if not stopped:
        logger.debug(
            "[STOP API] chat_id not found in tracker, trying to resolve "
            "from session_id...",
        )
        chat_manager = getattr(workspace.runner, "_chat_manager", None)
        if chat_manager:
            resolved_chat_id = await chat_manager.get_chat_id_by_session(
                session_id=chat_id,
                channel="console",
            )
            if resolved_chat_id:
                logger.debug(
                    "[STOP API] Resolved session_id=%s to chat_id=%s",
                    chat_id[:12] if len(chat_id) >= 12 else chat_id,
                    resolved_chat_id,
                )
                stopped = await workspace.task_tracker.request_stop(
                    resolved_chat_id,
                )

    logger.debug(
        "[STOP API] task_tracker.request_stop returned: stopped=%s",
        stopped,
    )
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
    check_upload_size(data)
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
    Return pending push messages and ALL approval requests.

    Messages:
    - With session_id: consumed messages for that session
    - Without session_id: recent messages (all sessions, last 60s)

    Approvals:
    - Always returns ALL pending approvals across all sessions
    - Frontend filters by current session_id for display
    - Includes session_id in each approval for filtering
    """
    from ..console_push_store import get_recent, take
    from ..approvals import get_approval_service

    # Get messages (session-specific or global)
    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()

    # Get ALL pending approvals (not filtered by session)
    approval_svc = get_approval_service()
    # pylint: disable=protected-access
    async with approval_svc._lock:
        all_pending = list(approval_svc._pending.values())

    # Serialize approval data with root_session_id for frontend filtering
    from ..approvals.serialize import pending_approval_to_console_dict

    approvals_data = [
        pending_approval_to_console_dict(p)
        for p in all_pending
    ]

    return {"messages": messages, "pending_approvals": approvals_data}


@router.get("/inbox/events")
async def get_inbox_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    unread_only: bool = Query(False),
):
    from ..inbox_store import list_events

    events = await list_events(
        limit=limit,
        offset=offset,
        source_type=source_type,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
    )
    return {"events": events}


@router.post("/inbox/read")
async def post_mark_inbox_read(payload: MarkInboxReadRequest):
    from ..inbox_store import mark_all_read, mark_read

    if payload.all:
        updated = await mark_all_read()
    else:
        updated = await mark_read(payload.event_ids)
    return {"updated": updated}


@router.delete("/inbox/events/{event_id}")
async def delete_inbox_event(event_id: str):
    from ..inbox_store import delete_event
    from ..inbox_trace_store import delete_trace

    deleted, run_id, run_id_still_referenced = await delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="event not found")
    trace_deleted = False
    if run_id and not run_id_still_referenced:
        trace_deleted = await delete_trace(run_id)
    return {
        "deleted": True,
        "trace_deleted": trace_deleted,
        "run_id": run_id,
    }


@router.get("/inbox/traces/{run_id}")
async def get_inbox_trace(run_id: str):
    from ..inbox_trace_store import get_trace

    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace
