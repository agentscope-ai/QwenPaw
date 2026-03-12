# -*- coding: utf-8 -*-
"""Chat management API."""
from __future__ import annotations

from copy import deepcopy
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agentscope.memory import InMemoryMemory
from agentscope_runtime.engine.schemas.agent_schemas import Message

from .session import SafeJSONSession
from .manager import ChatManager
from .models import (
    ChatSpec,
    ChatHistory,
)
from .utils import agentscope_msg_to_message


router = APIRouter(prefix="/chats", tags=["chats"])

_MAX_PLUGIN_OUTPUT_CHARS = 8000


def _is_tool_trace_message(msg: Message) -> bool:
    return msg.type in {"plugin_call", "plugin_call_output"}


def _compact_chat_history_messages(
    messages: list[Message],
) -> list[Message]:
    """Hide low-value tool trace messages for chat history rendering."""
    return [m for m in messages if not _is_tool_trace_message(m)]


def _paginate_chat_history_messages(
    messages: list[Message],
    offset: int,
    limit: int,
) -> tuple[list[Message], int, bool]:
    """Slice chat history into a stable page and provide pagination metadata."""
    total = len(messages)
    if offset >= total:
        return [], total, False

    page = messages[offset : offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def _truncate_chat_history_messages(
    messages: list[Message],
    max_plugin_output_chars: int = _MAX_PLUGIN_OUTPUT_CHARS,
) -> list[Message]:
    """Truncate oversized plugin call outputs for chat-history rendering.

    Large tool outputs can freeze web UI rendering for old sessions. Keep
    normal messages untouched while clipping only ``plugin_call_output`` data.
    """
    truncated: list[Message] = []

    for msg in messages:
        raw = msg.model_dump()
        content = raw.get("content")

        if raw.get("type") != "plugin_call_output" or not isinstance(
            content, list
        ):
            truncated.append(msg)
            continue

        msg_changed = False
        next_content = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "data":
                next_content.append(item)
                continue

            data = item.get("data")
            if not isinstance(data, dict):
                next_content.append(item)
                continue

            output = data.get("output")
            if (
                not isinstance(output, str)
                or len(output) <= max_plugin_output_chars
            ):
                next_content.append(item)
                continue

            clip_suffix = (
                "\n\n[truncated by CoPaw chat API: "
                f"showing first {max_plugin_output_chars} chars, "
                f"{len(output) - max_plugin_output_chars} chars omitted]"
            )
            next_item = deepcopy(item)
            next_item["data"]["output"] = (
                output[:max_plugin_output_chars] + clip_suffix
            )
            next_content.append(next_item)
            msg_changed = True

        if msg_changed:
            raw["content"] = next_content
            truncated.append(Message.model_validate(raw))
        else:
            truncated.append(msg)

    return truncated


def get_chat_manager(request: Request) -> ChatManager:
    """Get the chat manager from app state.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance

    Raises:
        HTTPException: If manager is not initialized
    """
    mgr = getattr(request.app.state, "chat_manager", None)
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="Chat manager not initialized",
        )
    return mgr


def get_session(request: Request) -> SafeJSONSession:
    """Get the session from app state.

    Args:
        request: FastAPI request object

    Returns:
        SafeJSONSession instance

    Raises:
        HTTPException: If session is not initialized
    """
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="Session not initialized",
        )
    return runner.session


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    mgr: ChatManager = Depends(get_chat_manager),
):
    """List all chats with optional filters.

    Args:
        user_id: Optional user ID to filter chats
        channel: Optional channel name to filter chats
        mgr: Chat manager dependency
    """
    return await mgr.list_chats(user_id=user_id, channel=channel)


@router.post("", response_model=ChatSpec)
async def create_chat(
    request: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a new chat.

    Server generates chat_id (UUID) automatically.

    Args:
        request: Chat creation request
        mgr: Chat manager dependency

    Returns:
        Created chat spec with UUID
    """
    chat_id = str(uuid4())
    spec = ChatSpec(
        id=chat_id,
        name=request.name,
        session_id=request.session_id,
        user_id=request.user_id,
        channel=request.channel,
        meta=request.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    chat_ids: list[str],
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete chats by chat IDs.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    return {"deleted": deleted}


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    offset: int = Query(
        0,
        ge=0,
        description="History page offset (0-based)",
    ),
    limit: int = Query(
        80,
        ge=1,
        le=500,
        description="History page size",
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: SafeJSONSession dependency

    Returns:
        ChatHistory with messages

    Raises:
        HTTPException: If chat not found (404)
    """
    chat_spec = await mgr.get_chat(chat_id)
    if not chat_spec:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
    )
    if not state:
        return ChatHistory(messages=[])
    memories = state.get("agent", {}).get("memory", [])
    memory = InMemoryMemory()
    memory.load_state_dict(memories)

    memories = await memory.get_memory()
    messages = agentscope_msg_to_message(memories)
    messages = _truncate_chat_history_messages(messages)
    messages = _compact_chat_history_messages(messages)
    page, total, has_more = _paginate_chat_history_messages(
        messages, offset, limit
    )
    return ChatHistory(
        messages=page,
        total=total,
        offset=offset,
        limit=limit,
        has_more=has_more,
    )


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Updated chat specification
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat_id mismatch (400) or not found (404)
    """
    if spec.id != chat_id:
        raise HTTPException(
            status_code=400,
            detail="chat_id mismatch",
        )

    # Check if exists
    existing = await mgr.get_chat(chat_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    updated = await mgr.update_chat(spec)
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete a chat by UUID.

    Note: This only deletes the chat spec (UUID mapping).
    JSONSession state is NOT deleted.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return {"deleted": True}
