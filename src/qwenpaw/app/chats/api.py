# -*- coding: utf-8 -*-
"""Chat management API."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Literal, Optional
from uuid import uuid4
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
)
from pydantic import BaseModel, ConfigDict, Field

from .session import SafeJSONSession
from .manager import ChatManager, MAX_BATCH_SIZE
from .models import (
    BatchArchiveResult,
    ChatGroup,
    ChatGroupCreate,
    ChatGroupOrderUpdate,
    ChatGroupUpdate,
    ChatSpec,
    ChatUpdate,
    ChatHistory,
    ChatHistoryMetadata,
    ChatMessagePage,
)
from .transcript import TranscriptCursor, TranscriptPage
from .utils import session_state_to_messages
from ...services.project_directory import (
    agent_project_dirs_from_config,
    resolve_effective_project_dirs,
    session_project_dirs_raw_from_meta,
)
from ...providers.thinking import ThinkingPreference
from ...schemas import Message
from ...services.session_thinking import (
    session_model,
    thinking_view,
)
from ...config.config import ModelSlotConfig
from ...checkpoints.runtime import RUNTIME as CHECKPOINT_RUNTIME

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


def _encode_transcript_cursor(value: TranscriptCursor | None) -> str | None:
    if value is None:
        return None
    return f"{value.turn_seq}:{value.ordinal}"


def _decode_transcript_cursor(value: str | None) -> TranscriptCursor | None:
    if value is None:
        return None
    try:
        turn_seq, ordinal = (int(part) for part in value.split(":"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid history cursor",
        ) from exc
    if turn_seq < 1 or ordinal < 0:
        raise HTTPException(status_code=400, detail="Invalid history cursor")
    return TranscriptCursor(turn_seq=turn_seq, ordinal=ordinal)


def _history_metadata(page: TranscriptPage) -> ChatHistoryMetadata:
    return ChatHistoryMetadata(
        has_more=page.has_more,
        next_before=_encode_transcript_cursor(page.next_before),
    )


async def _read_transcript_page(
    workspace,
    chat: ChatSpec,
    *,
    before: TranscriptCursor | None = None,
    limit: int = 50,
    max_bytes: int = 512 * 1024,
) -> TranscriptPage | None:
    """Read one transcript page without blocking the event loop."""
    store = getattr(workspace, "transcript_store", None)
    if store is None:
        return None
    try:
        return await asyncio.to_thread(
            store.get_page,
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
            before=before,
            limit=limit,
            max_bytes=max_bytes,
        )
    except (OSError, sqlite3.Error, ValueError, TypeError):
        logger.warning(
            "Failed to read transcript for session %s",
            chat.session_id,
            exc_info=True,
        )
        return None


def _migrate_legacy_messages(
    workspace,
    chat: ChatSpec,
    messages: list[Message],
) -> None:
    """Best-effort import of legacy display history after a response."""
    store = getattr(workspace, "transcript_store", None)
    if store is None or not messages:
        return
    try:
        store.import_legacy_messages(
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
            messages=messages,
        )
    except Exception:
        logger.warning(
            "Failed to migrate legacy transcript for session %s",
            chat.session_id,
            exc_info=True,
        )


async def _delete_chat_data(workspace, chats: list[ChatSpec]) -> None:
    """Delete transcript, snapshot, and checkpoint data for chats."""
    store = getattr(workspace, "transcript_store", None)
    session = getattr(workspace, "session", None)
    try:
        if store is not None:
            for chat in chats:
                await asyncio.to_thread(
                    store.delete_session,
                    chat.session_id,
                )
        if session is not None:
            for chat in chats:
                await session.delete_session_state(
                    chat.session_id,
                    chat.user_id,
                    chat.channel,
                )
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [(chat.session_id, chat.user_id, chat.channel) for chat in chats],
        )
    except Exception as exc:
        logger.error("Failed to delete chat persistence", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete chat persistence",
        ) from exc


def _unshared_chat_data_targets(
    targets: list[ChatSpec],
    catalog: list[ChatSpec],
) -> list[ChatSpec]:
    """Return sessions whose every chat mapping is being deleted."""
    target_ids = {chat.id for chat in targets}
    retained_sessions = {
        (chat.session_id, chat.user_id, chat.channel)
        for chat in catalog
        if chat.id not in target_ids
    }
    result: list[ChatSpec] = []
    seen: set[tuple[str, str, str]] = set()
    for chat in targets:
        identity = (chat.session_id, chat.user_id, chat.channel)
        if identity in retained_sessions or identity in seen:
            continue
        seen.add(identity)
        result.append(chat)
    return result


def _is_app_owned_chat(chat: ChatSpec) -> bool:
    """Return whether a chat belongs to a PawApp-owned dialogue surface."""
    owner = chat.meta.get("pawapp") if isinstance(chat.meta, dict) else None
    return isinstance(owner, dict) and bool(owner.get("app_id"))


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


class ChatStatusResponse(BaseModel):
    """Lightweight TaskTracker status for one chat."""

    status: Literal["idle", "running"]


class ProjectDirEntryPayload(BaseModel):
    """One project-directory entry as sent by the client."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        ...,
        min_length=1,
        description="Absolute path to a project directory",
    )
    label: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Optional note describing what this directory is for",
    )


class ProjectDirsRequest(BaseModel):
    """Payload for setting a chat's project-directory list override.

    The list is ordered: the first entry becomes the PRIMARY project
    directory. The payload is the whole desired list — add, remove and
    make-primary are all expressed as list transforms followed by one
    PUT.
    """

    model_config = ConfigDict(extra="forbid")

    project_dirs: list[ProjectDirEntryPayload] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Full ordered list, primary first",
    )


class ProjectDirEntryView(BaseModel):
    """One effective project-directory entry for the UI."""

    path: str = Field(description="Directory path")
    label: Optional[str] = Field(
        default=None,
        description="Display name for this directory, when one was set",
    )
    exists: bool = Field(
        description=(
            "Whether the path exists. False is surfaced rather than "
            "silently corrected so the UI can flag it as unavailable."
        ),
    )
    nested_with: Optional[str] = Field(
        default=None,
        description=(
            "Path of the nearest ancestor root when this entry is "
            "nested inside another bound root (informational; the "
            "entry stays fully usable)."
        ),
    )
    is_workspace: bool = Field(
        default=False,
        description=(
            "Whether this entry is the agent's own workspace directory. "
            "Decided here by filesystem identity, because the client "
            "cannot: comparing the two paths as text splits one directory "
            "into two roots on a case-sensitive volume and merges two "
            "distinct ones on a folding volume. The Files switcher "
            "collapses such an entry onto its own 'workspace' root rather "
            "than giving it a second one with its own editor tabs."
        ),
    )


class ProjectDirsResponse(BaseModel):
    """Effective project-directory list for a chat, plus provenance."""

    project_dirs: list[ProjectDirEntryView] = Field(
        description=(
            "Effective list, primary first. Empty when nothing is "
            "configured (tools then fall back to the agent workspace; "
            "the workspace path itself is deliberately not listed)."
        ),
    )
    source: str = Field(
        description=(
            "Provenance of the list: 'session' (this chat overrides), "
            "'agent' (agent default), or 'workspace_fallback' (nothing "
            "configured)"
        ),
    )
    agent_project_dir: Optional[str] = Field(
        default=None,
        description=(
            "The agent-level default directory (single value), for "
            "showing inheritance"
        ),
    )


async def _project_directory_response(chat: ChatSpec, workspace) -> dict:
    """Build the effective Session project directory response."""
    from ...config.config import load_agent_config

    def _build() -> dict:
        try:
            config = load_agent_config(workspace.agent_id)
            agent_dir = config.project_dir
            agent_dirs = agent_project_dirs_from_config(config)
        except Exception:
            agent_dir, agent_dirs = None, []
        resolved = resolve_effective_project_dirs(
            workspace.workspace_dir,
            agent_project_dir=agent_dir,
            agent_project_dirs=agent_dirs,
            session_project_dirs=session_project_dirs_raw_from_meta(chat.meta),
        )
        project_dir = resolved.primary_path
        return {
            "project_dir": str(project_dir),
            "source": resolved.source,
            "agent_project_dir": agent_dir,
            "exists": project_dir.is_dir(),
        }

    return await asyncio.to_thread(_build)


async def _project_dirs_response(chat: ChatSpec, workspace) -> dict:
    """Build the effective Session project-directory list response."""
    from ...config.config import load_agent_config
    from ...services.project_directory import (
        nested_root_pairs,
    )

    def _build() -> dict:
        try:
            agent_config = load_agent_config(workspace.agent_id)
            agent_dir = agent_config.project_dir
            agent_dirs = agent_project_dirs_from_config(agent_config)
        except Exception:
            agent_dir, agent_dirs = None, []

        resolved = resolve_effective_project_dirs(
            workspace.workspace_dir,
            agent_project_dir=agent_dir,
            agent_project_dirs=agent_dirs,
            session_project_dirs=session_project_dirs_raw_from_meta(chat.meta),
        )
        # Nearest covering ancestor per entry, for the UI hint. Fed the
        # already-resolved paths so the nesting check does not resolve()
        # every entry a second time.
        nearest: dict[int, str] = {}
        for child_idx, anc_idx in nested_root_pairs(
            [entry.path for entry in resolved.dirs],
        ):
            candidate = str(resolved.dirs[anc_idx].path)
            current = nearest.get(child_idx)
            if current is None or len(candidate) > len(current):
                nearest[child_idx] = candidate

        return {
            "project_dirs": [
                {
                    "path": str(entry.path),
                    "label": entry.label,
                    "exists": entry.exists,
                    "nested_with": nearest.get(index),
                    # Compared by key, not by path text: these are the same
                    # directory exactly when they reach the same entry.
                    "is_workspace": bool(entry.key)
                    and entry.key == resolved.workspace_key,
                }
                for index, entry in enumerate(resolved.dirs)
            ],
            "source": resolved.source,
            "agent_project_dir": agent_dir,
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
    include_app_owned: bool = Query(
        True,
        description=(
            "Include PawApp-owned chats. Administrative and legacy callers "
            "keep the full catalog by default; the main Chat surface opts out."
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
    if not include_app_owned:
        chats = [chat for chat in chats if not _is_app_owned_chat(chat)]
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
        source=request.source,
        group_id=request.group_id,
        parent_session_id=request.parent_session_id,
        root_session_id=request.root_session_id,
    )
    try:
        return await mgr.create_chat(spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ----- Chat group endpoints -----


@router.get("/groups", response_model=list[ChatGroup])
async def list_chat_groups(
    mgr: ChatManager = Depends(get_chat_manager),
):
    """List built-in and custom groups in display order."""
    return await mgr.list_groups()


@router.post("/groups", response_model=ChatGroup)
async def create_chat_group(
    payload: ChatGroupCreate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a custom chat group."""
    try:
        return await mgr.create_group(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/groups/order", response_model=list[ChatGroup])
async def reorder_chat_groups(
    payload: ChatGroupOrderUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Replace the complete chat-group display order."""
    try:
        return await mgr.reorder_groups(payload.group_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/groups/{group_id}", response_model=ChatGroup)
async def update_chat_group(
    group_id: str,
    payload: ChatGroupUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Rename or pin a mutable chat group."""
    try:
        group = await mgr.update_group(
            group_id,
            name=payload.name,
            pinned=payload.pinned,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if group is None:
        raise HTTPException(status_code=404, detail="Chat group not found")
    return group


@router.delete("/groups/{group_id}", response_model=dict)
async def delete_chat_group(
    group_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete a custom group and re-home its chats."""
    try:
        deleted = await mgr.delete_group(group_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat group not found")
    return {"success": True, "group_id": group_id}


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
    catalog = await mgr.list_chats(archived=None)
    chats = {chat.id: chat for chat in catalog}
    targets = [
        chat
        for chat_id in chat_ids
        if (chat := chats.get(chat_id)) is not None
    ]
    data_targets = _unshared_chat_data_targets(targets, catalog)
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    if deleted and data_targets:
        await _delete_chat_data(
            workspace,
            data_targets,
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


@router.get("/{chat_id}/project-dir", deprecated=True)
async def get_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Return the Session override and effective project directory.

    Deprecated single-value view; use ``/project-dirs``.
    """
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.put("/{chat_id}/project-dir", deprecated=True)
async def set_chat_project_dir(
    chat_id: str,
    body: ProjectDirectoryUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Persist a validated Session project directory override.

    Deprecated single-value write; stored as a one-entry list so the
    plural endpoints see the same state. Use ``PUT /project-dirs``.
    """

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
    chat = await mgr.set_session_project_dirs(
        chat_id,
        [{"path": str(target), "label": None}],
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.delete("/{chat_id}/project-dir", deprecated=True)
async def clear_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Clear the override and inherit the Agent default project directory.

    Deprecated; use ``DELETE /project-dirs``.
    """
    chat = await mgr.set_session_project_dirs(chat_id, None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.get("/{chat_id}/project-dirs", response_model=ProjectDirsResponse)
async def get_chat_project_dirs(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Return this chat's effective project-directory list, primary first."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_dirs_response(chat, workspace)


@router.put("/{chat_id}/project-dirs", response_model=ProjectDirsResponse)
async def set_chat_project_dirs(
    chat_id: str,
    payload: ProjectDirsRequest,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Bind this chat to an ordered project-directory list.

    The first entry is the primary project directory. The override is
    persisted server-side, so it survives a page reload or a different
    browser. It takes effect on the **next** turn — an in-flight turn
    keeps the directories it started with.

    Paths that do not exist are rejected here (rather than stored and
    flagged) because this endpoint is the point where the user picks
    them and can still correct the mistake. Duplicate paths
    (case-insensitive) are collapsed, keeping the first occurrence.
    """
    from ...services.project_directory import (
        MAX_PROJECT_DIRS,
        normalize_project_dir_list,
    )

    def _normalize() -> tuple[list[dict], Optional[str], int]:
        """Normalize and existence-check in one worker thread.

        The ``is_dir()`` calls belong in here with the ``resolve()`` that
        ``normalize_project_dir_list`` does: leaving them on the event
        loop meant up to ``MAX_PROJECT_DIRS`` blocking stats per request,
        and one unresponsive mount stalled every other connection.
        """
        entries = normalize_project_dir_list(
            [entry.model_dump() for entry in payload.project_dirs],
        )
        missing = next(
            (str(path) for path, _label in entries if not path.is_dir()),
            None,
        )
        stored = [
            {"path": str(path), "label": label} for path, label in entries
        ]
        return stored, missing, len(entries)

    stored, missing, count = await asyncio.to_thread(_normalize)
    if not count:
        raise HTTPException(
            status_code=422,
            detail="project_dirs must contain at least one valid entry",
        )
    if count > MAX_PROJECT_DIRS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many project dirs (max {MAX_PROJECT_DIRS})",
        )
    if missing is not None:
        raise HTTPException(
            status_code=422,
            detail=f"Not a directory: {missing}",
        )

    updated = await mgr.set_session_project_dirs(chat_id, stored)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return await _project_dirs_response(updated, workspace)


@router.delete(
    "/{chat_id}/project-dirs",
    response_model=ProjectDirsResponse,
)
async def clear_chat_project_dirs(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Drop this chat's override so it inherits the agent default again."""
    updated = await mgr.set_session_project_dirs(chat_id, None)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return await _project_dirs_response(updated, workspace)


@router.get(f"/thinking-default")
async def get_default_thinking(
    provider_id: str | None = None,
    model: str | None = None,
    workspace=Depends(get_workspace),
):
    """Expose the agent default for a not-yet-created session."""
    selected = (
        ModelSlotConfig(provider_id=provider_id, model=model)
        if provider_id and model
        else None
    )
    return await thinking_view(workspace, model_override=selected)


@router.get(f"/{{chat_id}}/thinking")
async def get_chat_thinking(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Read the session override and effective model-specific setting."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, f"Chat not found")
    return await thinking_view(
        workspace,
        model_override=session_model(chat.meta),
        meta=chat.meta,
    )


@router.put(f"/{{chat_id}}/thinking")
async def set_chat_thinking(
    chat_id: str,
    preference: ThinkingPreference,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    model_key: str | None = None,
):
    """Persist a preference for subsequent turns of this session only."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, f"Chat not found")
    view = await thinking_view(workspace, preference, session_model(chat.meta))
    if model_key is not None and model_key != view[f"model_key"]:
        raise HTTPException(409, f"Session model changed; reload its settings")
    if preference.level != f"inherit" and view[f"reason"] is not None:
        raise HTTPException(422, f"Thinking setting is invalid for this model")
    chat = await mgr.set_session_thinking(
        chat_id,
        preference,
        view[f"model_key"],
    )
    if chat is None:
        raise HTTPException(404, f"Chat not found")
    return await thinking_view(
        workspace,
        model_override=session_model(chat.meta),
        meta=chat.meta,
    )


@router.put(f"/{{chat_id}}/model")
async def set_chat_model(
    chat_id: str,
    model: ModelSlotConfig | None = Body(None),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Select the model for this conversation only."""
    view = await thinking_view(workspace, model_override=model)
    if model is not None and (view[f"provider_id"], view[f"model"]) != (
        model.provider_id,
        model.model,
    ):
        raise HTTPException(422, f"Model provider is unavailable")
    chat = await mgr.set_session_model(
        chat_id,
        model.model_dump() if model else None,
    )
    if chat is None:
        raise HTTPException(404, f"Chat not found")
    return await thinking_view(
        workspace,
        model_override=session_model(chat.meta),
        meta=chat.meta,
    )


# ----- Existing CRUD endpoints -----


@router.get("/{chat_id}/status", response_model=ChatStatusResponse)
async def get_chat_status(
    chat_id: str,
    workspace=Depends(get_workspace),
) -> ChatStatusResponse:
    """Return agent-scoped run status without reading chat persistence."""
    status = await workspace.task_tracker.get_status(chat_id)
    return ChatStatusResponse(status=status)


@router.get("/{chat_id}/messages", response_model=ChatMessagePage)
async def get_chat_messages(
    chat_id: str,
    before: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    max_bytes: Annotated[
        int,
        Query(ge=1024, le=4 * 1024 * 1024),
    ] = 512
    * 1024,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> ChatMessagePage:
    """Return one item-bounded page of durable chat messages."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    page = await _read_transcript_page(
        workspace,
        chat,
        before=_decode_transcript_cursor(before),
        limit=limit,
        max_bytes=max_bytes,
    )
    if page is None:
        return ChatMessagePage()
    metadata = _history_metadata(page)
    return ChatMessagePage(
        messages=page.messages,
        **metadata.model_dump(),
    )


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    background_tasks: BackgroundTasks,
    include_app_owned: bool = Query(
        True,
        description=(
            "Allow reading PawApp-owned chat history. The main Chat surface "
            "opts out so app dialogues stay inside their owning app."
        ),
    ),
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
    if not include_app_owned and _is_app_owned_chat(chat_spec):
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    status = await workspace.task_tracker.get_status(chat_id)

    transcript_page = await _read_transcript_page(
        workspace,
        chat_spec,
    )
    if transcript_page is not None:
        return ChatHistory(
            messages=transcript_page.messages,
            status=status,
            history=_history_metadata(transcript_page),
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

    if not state:
        return ChatHistory(
            messages=[],
            status=status,
            history=ChatHistoryMetadata(),
        )

    messages = await asyncio.to_thread(session_state_to_messages, state)
    background_tasks.add_task(
        _migrate_legacy_messages,
        workspace,
        chat_spec,
        messages,
    )
    return ChatHistory(
        messages=messages,
        status=status,
        history=ChatHistoryMetadata(),
    )


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
    try:
        updated = await mgr.patch_chat(chat_id, spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    catalog = await mgr.list_chats(archived=None)
    data_targets = _unshared_chat_data_targets([chat], catalog)
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    if data_targets:
        await _delete_chat_data(workspace, data_targets)
    return {"deleted": True}
