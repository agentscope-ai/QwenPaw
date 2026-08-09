# -*- coding: utf-8 -*-
"""Chat management API."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agentscope.message import Msg
from agentscope.state import AgentState

from .session import SafeJSONSession
from .manager import ChatManager, MAX_BATCH_SIZE
from .models import (
    BatchArchiveResult,
    ChatSpec,
    ChatUpdate,
    ChatHistory,
    ForkChatRequest,
    ForkChatResponse,
)
from .utils import agentscope_msg_to_message, parse_legacy_memory_state
from ...services.project_directory import (
    resolve_effective_project_dir,
    session_project_dir,
)
from ...checkpoints.runtime import RUNTIME as CHECKPOINT_RUNTIME
from ...utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


def _scroll_history_path(workspace) -> Path | None:
    """Return the configured Scroll history path without creating a DB.

    Existing rows are cloned even when the agent currently runs in native
    mode: the source may have been compressed before the strategy changed,
    and those evicted turns exist only in this store.
    """
    try:
        light_context = workspace.config.running.light_context_config
        path = Path(workspace.workspace_dir) / (
            light_context.scroll_config.db_filename
        )
    except (AttributeError, TypeError):
        return None
    return path if path.exists() else None


def _clone_scroll_history(
    workspace,
    *,
    source_session_id: str,
    destination_session_id: str,
) -> dict[int, int]:
    """Clone durable Scroll rows and return source-to-fork seq mapping."""
    path = _scroll_history_path(workspace)
    if path is None:
        return {}
    from ...agents.context.scroll.history import HistoryStore

    history = HistoryStore(path)
    try:
        return history.clone_session_rows(
            source_session_id=source_session_id,
            destination_session_id=destination_session_id,
        )
    finally:
        history.close()


def _delete_scroll_history(workspace, session_id: str) -> int:
    """Best-effort rollback for durable rows created during a failed fork."""
    path = _scroll_history_path(workspace)
    if path is None:
        return 0
    from ...agents.context.scroll.history import HistoryStore

    history = HistoryStore(path)
    try:
        return history.delete_session_rows(session_id)
    finally:
        history.close()


async def get_workspace(request: Request):
    """Get the workspace for the active agent."""
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def get_chat_manager(
    request: Request,
) -> ChatManager:
    """Get the chat manager for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance for the specified agent

    Raises:
        HTTPException: If manager is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.chat_manager


async def get_session(
    request: Request,
) -> SafeJSONSession:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        SafeJSONSession instance for the specified agent

    Raises:
        HTTPException: If session is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.session


class ProjectDirectoryUpdate(BaseModel):
    """Controlled Session project directory update."""

    project_dir: str


async def _project_directory_response(chat: ChatSpec, workspace) -> dict:
    """Build the effective Session project directory response."""
    from ...config.config import load_agent_config

    def _build() -> dict:
        agent_config = load_agent_config(workspace.agent_id)
        project_dir, source = resolve_effective_project_dir(
            workspace.workspace_dir,
            agent_project_dir=agent_config.project_dir,
            session_override=session_project_dir(chat.meta),
        )
        return {
            "project_dir": str(project_dir),
            "source": source,
            "agent_project_dir": agent_config.project_dir,
            "exists": project_dir.is_dir(),
        }

    return await asyncio.to_thread(_build)


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    archived: Optional[bool] = Query(
        None,
        description=(
            "Filter by archived status. "
            "false=active only, true=archived only, "
            "null/omit=all (default)"
        ),
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    When ``archived`` is omitted, returns all chats (both active and archived).
    Pass ``archived=false`` for active only,
    ``archived=true`` for archived only.
    """
    chats = await mgr.list_chats(
        user_id=user_id,
        channel=channel,
        archived=archived,
    )
    tracker = workspace.task_tracker
    result = []
    for spec in chats:
        status = await tracker.get_status(spec.id)
        result.append(spec.model_copy(update={"status": status}))
    return result


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
    workspace=Depends(get_workspace),
):
    """Delete chats by chat IDs.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    chats = {chat.id: chat for chat in await mgr.list_chats(archived=None)}
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    if deleted:
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [
                (chat.session_id, chat.user_id, chat.channel)
                for chat_id in chat_ids
                if (chat := chats.get(chat_id)) is not None
            ],
        )
    return {"deleted": deleted}


# ----- Archive endpoints -----


class BatchChatIds(BaseModel):
    """Request body for batch archive/unarchive."""

    chat_ids: list[str] = Field(
        ...,
        max_length=MAX_BATCH_SIZE,
        description="List of chat IDs to process",
    )


@router.post("/actions/batch-archive", response_model=BatchArchiveResult)
async def batch_archive_chats(
    payload: BatchChatIds,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Batch archive chats. Running chats are skipped."""
    tracker = workspace.task_tracker
    return await mgr.batch_archive(
        chat_ids=payload.chat_ids,
        get_status=tracker.get_status,
    )


@router.post("/actions/batch-unarchive", response_model=BatchArchiveResult)
async def batch_unarchive_chats(
    payload: BatchChatIds,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Batch unarchive chats."""
    return await mgr.batch_unarchive(chat_ids=payload.chat_ids)


@router.post("/{chat_id}/archive", response_model=ChatSpec)
async def archive_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Archive a single chat. Idempotent.

    Returns 409 if the chat is currently running.
    """
    status = await workspace.task_tracker.get_status(chat_id)
    try:
        result = await mgr.archive_chat(chat_id, check_status=status)
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail="Chat is currently in progress, cannot archive",
        ) from e
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return result


@router.post("/{chat_id}/unarchive", response_model=ChatSpec)
async def unarchive_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Unarchive a single chat. Idempotent."""
    result = await mgr.unarchive_chat(chat_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return result


@router.get("/{chat_id}/project-dir")
async def get_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Return the Session override and effective project directory."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.put("/{chat_id}/project-dir")
async def set_chat_project_dir(
    chat_id: str,
    body: ProjectDirectoryUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Persist a validated Session project directory override."""

    def _resolve_target() -> Path:
        target = Path(body.project_dir).expanduser().resolve()
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        return target

    try:
        target = await asyncio.to_thread(_resolve_target)
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Project directory is unavailable: {exc}",
        ) from exc
    chat = await mgr.set_project_dir(chat_id, str(target))
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.delete("/{chat_id}/project-dir")
async def clear_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Clear the override and inherit the Agent default project directory."""
    chat = await mgr.set_project_dir(chat_id, None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


# ----- Fork endpoint -----


@router.post(
    "/{chat_id}/fork",
    response_model=ForkChatResponse,
    status_code=201,
)
async def fork_chat(
    chat_id: str,
    body: ForkChatRequest = ForkChatRequest(),
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Fork a chat: create a full snapshot in a new independent session.

    201 on success.
    404 if the source chat does not exist.
    409 if the source chat is currently running (best-effort guard;
         a TOCTOU window exists — see the design doc).
    500 on I/O or persistence failures.
    """
    # 1. Validate source exists
    source = await mgr.get_chat(chat_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    # 2. Best-effort guard: reject if currently running
    tracker = workspace.task_tracker
    status = await tracker.get_status(chat_id)
    if status == "running":
        raise HTTPException(
            status_code=409,
            detail=(
                "Source chat is still generating. "
                "Wait for it to finish before forking."
            ),
        )

    # 3. Generate new session_id
    fork_uuid = str(uuid4())[:8]
    new_session_id = f"{source.session_id}:fork-{fork_uuid}"

    # 4. Clone durable Scroll rows first. New globally addressed seq values
    #    are returned so the JSON checkpoint can be rebased onto fork-owned
    #    history instead of retaining source pointers.
    try:
        scroll_seq_map = await run_sync_io(
            _clone_scroll_history,
            workspace,
            source_session_id=source.session_id,
            destination_session_id=new_session_id,
        )
    except Exception as exc:
        logger.exception(
            "Failed to clone Scroll history for chat %s",
            chat_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to copy durable session history.",
        ) from exc

    # 5. Clone session state file (BEFORE creating ChatSpec).
    #    allow_missing_source=True: if source file was manually deleted,
    #    write {} to preserve the invariant that the session file exists
    #    before any ChatSpec references it.
    source_missing = False
    try:
        source_missing = await session.clone_session_state(
            src_session_id=source.session_id,
            dst_session_id=new_session_id,
            user_id=source.user_id,
            channel=source.channel,
            allow_missing_source=True,
            scroll_seq_map=scroll_seq_map,
        )
    except Exception as exc:
        try:
            await run_sync_io(
                _delete_scroll_history,
                workspace,
                new_session_id,
            )
        except Exception:
            logger.warning(
                "Failed to clean up fork Scroll history: %s",
                new_session_id,
                exc_info=True,
            )
        logger.exception(
            "Failed to clone session state for chat %s",
            chat_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to copy session state.",
        ) from exc

    # 6. Create ChatSpec (best-effort cleanup on failure)
    fork_name = body.name or f"Fork of {source.name}"
    try:
        new_spec = await mgr.fork_chat(
            source_chat_id=chat_id,
            new_session_id=new_session_id,
            name=fork_name,
        )
    except Exception as exc:
        # Best-effort cleanup of now-orphan session file
        deleted = await session.delete_session_state(
            session_id=new_session_id,
            user_id=source.user_id,
            channel=source.channel,
        )
        if not deleted:
            logger.warning(
                "ChatSpec creation failed; orphan session file could "
                "not be deleted: %s",
                new_session_id,
            )
        try:
            await run_sync_io(
                _delete_scroll_history,
                workspace,
                new_session_id,
            )
        except Exception:
            logger.warning(
                "ChatSpec creation failed; fork Scroll history could not "
                "be deleted: %s",
                new_session_id,
                exc_info=True,
            )
        logger.exception(
            "Failed to create forked chat for source %s",
            chat_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to create forked chat.",
        ) from exc

    return ForkChatResponse(
        chat_id=new_spec.id,
        session_id=new_spec.session_id,
        name=new_spec.name,
        created_at=new_spec.created_at,
        source_state="empty" if source_missing else "ok",
    )


# ----- Existing CRUD endpoints -----


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        request: FastAPI request (for agent context)
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: SafeJSONSession dependency

    Returns:
        ChatHistory with messages and status (idle/running)

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
        chat_spec.channel,
    )
    backend = workspace.config.backend
    context = ((state.get("agent") or {}).get("state") or {}).get("context")
    if not context and backend != "qwenpaw":
        try:
            await workspace.harness_runtime.hydrate_session(
                backend=backend,
                session_id=chat_spec.session_id,
                user_id=chat_spec.user_id,
                channel=chat_spec.channel,
                settings=dict(workspace.config.backend_settings),
            )
            state = await session.get_session_state_dict(
                chat_spec.session_id,
                chat_spec.user_id,
                chat_spec.channel,
            )
        except Exception:
            logger.debug(
                "Third-party session recovery failed for %s",
                chat_spec.session_id,
                exc_info=True,
            )
    status = await workspace.task_tracker.get_status(chat_id)
    if not state:
        return ChatHistory(messages=[], status=status)

    agent_raw = state.get("agent", {})
    memories: list[Msg] = []

    state_raw = agent_raw.get("state")
    if isinstance(state_raw, dict):
        try:
            agent_state = AgentState.model_validate(state_raw)
            memories = list(agent_state.context)
        except Exception:
            logger.debug(
                "Failed to parse agent.state, falling back to legacy",
                exc_info=True,
            )

    # Legacy fallback: 1.x ``agent.memory`` format.
    if not memories:
        memory_raw = agent_raw.get("memory", {})
        if memory_raw:
            memories, _summary = parse_legacy_memory_state(memory_raw)

    messages = agentscope_msg_to_message(memories)
    return ChatHistory(messages=messages, status=status)


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Partial chat update payload
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat not found (404)
    """
    updated = await mgr.patch_chat(chat_id, spec)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
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
    chat = await mgr.get_chat(chat_id)
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    if chat is not None:
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [(chat.session_id, chat.user_id, chat.channel)],
        )
    return {"deleted": True}
