# -*- coding: utf-8 -*-
"""Chat management API."""

from __future__ import annotations

import asyncio
import logging
import sys
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

from ..task_tracker import RunUnavailableError
from .session import DatabaseSession, LegacyConversationSnapshot
from .provider_migration import (
    recover_codex_boundaries,
    recover_qoder_boundaries,
)
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
    ChatContextState,
    ChatHistoryMetadata,
    ChatMessagePage,
    ChatUserMessage,
    ChatUserMessagePage,
)
from .history_store import (
    ConversationHistoryError,
    ConversationHistoryPage,
    TranscriptHistoryStore,
)
from .transcript_paging import TranscriptPageBudgetError
from .utils import session_state_to_messages
from .resolver import (
    ChatResolution,
    find_chat_matches,
    is_app_owned_chat as _is_app_owned_chat,
)
from ...config.utils import load_config
from ...harnesses.registry import get_provider
from ...constant import QWENPAW_CLIENT_MESSAGE_ID_KEY
from ...utils.io_utils import run_sync_io
from ...services.project_directory import (
    agent_project_dirs_from_config,
    resolve_effective_project_dirs,
    session_project_dirs_raw_from_meta,
)
from ...providers.thinking import ThinkingPreference
from ...schemas import Message, Role, TextContent
from ...services.session_thinking import (
    session_model,
    thinking_view,
)
from ...config.config import ModelSlotConfig
from ...checkpoints.runtime import RUNTIME as CHECKPOINT_RUNTIME

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


def _history_metadata(page: ConversationHistoryPage) -> ChatHistoryMetadata:
    return ChatHistoryMetadata(
        has_more=page.has_more,
        next_before=page.next_before,
        snapshot=page.snapshot,
    )


def _history_store(workspace):
    store = getattr(workspace, "history_store", None)
    if store is not None:
        return store
    transcript = getattr(workspace, "transcript_store", None)
    if transcript is None:
        return None
    return TranscriptHistoryStore(transcript)


def _legacy_needs_page(messages, limit, max_bytes, max_content_blocks):
    """Keep an unprojected legacy snapshot within the same page budgets."""
    turns = blocks = size = 0
    for message in messages:
        turns += message.role == "user"
        blocks += max(1, len(message.content))
        size += len(message.model_dump_json().encode("utf-8"))
        if (
            turns > limit
            or blocks > max_content_blocks
            or size > max_bytes - 1024
        ):
            return True
    return False


async def _read_history_page(
    workspace,
    chat: ChatSpec,
    *,
    before: str | None = None,
    after_message_id: str | None = None,
    before_message_id: str | None = None,
    limit: int = 5,
    max_bytes: int = 2 * 1024 * 1024,
    max_content_blocks: int = 40,
) -> ConversationHistoryPage | None:
    """Read one history page without blocking the event loop."""
    if chat.meta.get("deletion_pending"):
        raise HTTPException(
            409,
            "Conversation deletion failed; retry deletion",
        )
    store = _history_store(workspace)
    if store is None:
        return None
    options = dict(
        session_id=chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
        before=before,
        **({"after_message_id": after_message_id} if after_message_id else {}),
        **(
            {"before_message_id": before_message_id}
            if before_message_id
            else {}
        ),
        limit=limit,
        max_bytes=max_bytes,
        max_content_blocks=max_content_blocks,
    )
    try:
        page = await asyncio.to_thread(store.get_page, **options)
        if page is None:
            snapshot = await _read_workspace_legacy_snapshot(workspace, chat)
            if snapshot is not None and _legacy_needs_page(
                snapshot.messages,
                limit,
                max_bytes,
                max_content_blocks,
            ):
                await workspace.session.start_legacy_migration(
                    session_id=chat.session_id,
                    user_id=chat.user_id,
                    channel=chat.channel,
                    snapshot=snapshot,
                    wait_for_projection=True,
                )
                return await asyncio.to_thread(store.get_page, **options)
        return page
    except ConversationHistoryError:
        logger.warning(
            "Failed to read conversation history for session %s",
            chat.session_id,
            exc_info=True,
        )
        raise HTTPException(503, "Conversation history unavailable")


async def _read_user_message_page(
    workspace,
    chat: ChatSpec,
    *,
    before: str | None = None,
    limit: int = 200,
):
    """Read one user-message index page without blocking the event loop."""
    if chat.meta.get("deletion_pending"):
        raise HTTPException(
            409,
            "Conversation deletion failed; retry deletion",
        )
    store = _history_store(workspace)
    if store is None:
        return None
    try:
        return await asyncio.to_thread(
            store.get_user_message_page,
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
            before=before,
            limit=limit,
        )
    except ConversationHistoryError:
        logger.warning(
            "Failed to read user-message index for session %s",
            chat.session_id,
            exc_info=True,
        )
        raise HTTPException(503, "Conversation history unavailable")


async def _read_context_state(
    session: DatabaseSession,
    chat: ChatSpec,
) -> ChatContextState | None:
    """Read current context state independently from historical messages."""
    getter = getattr(session, "get_current_usage", None)
    if getter is None:
        return None
    try:
        generation, usage = await getter(
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
        )
        return ChatContextState(generation=generation, usage=usage)
    except Exception:
        logger.warning(
            "Failed to read context state for session %s",
            chat.session_id,
            exc_info=True,
        )
        return None


async def _read_legacy_snapshot(
    session: DatabaseSession,
    chat: ChatSpec,
) -> LegacyConversationSnapshot | None:
    """Read legacy JSON and start its shared background migration."""
    snapshot = await session.get_legacy_snapshot(
        session_id=chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
    )
    if snapshot is not None:
        await session.start_legacy_migration(
            session_id=chat.session_id,
            user_id=chat.user_id,
            channel=chat.channel,
            snapshot=snapshot,
        )
    return snapshot


async def _read_workspace_legacy_snapshot(workspace, chat: ChatSpec):
    """Read a legacy snapshot through the workspace session service."""
    session = getattr(workspace, "session", None)
    if session is None:
        return None
    return await _read_legacy_snapshot(session, chat)


def _legacy_message_text(message: Message) -> str:
    """Return the complete textual content of one legacy message."""
    return "\n".join(
        part.text
        for part in message.content
        if isinstance(part, TextContent) and part.text
    )


def _legacy_user_messages(messages: list[Message]) -> list[ChatUserMessage]:
    """Build navigation entries directly from legacy messages."""
    items = []
    for message in messages:
        if message.role != Role.USER:
            continue
        text = _legacy_message_text(message)
        metadata = message.metadata or {}
        client_id = metadata.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
        nested = metadata.get("metadata")
        if not client_id and isinstance(nested, dict):
            client_id = nested.get(QWENPAW_CLIENT_MESSAGE_ID_KEY)
        items.append(
            ChatUserMessage(
                message_id=message.id,
                client_message_id=str(client_id) if client_id else None,
                preview=" ".join(text.split())[:160],
                created_at=str(metadata.get("timestamp") or ""),
                anchor="",
            ),
        )
    return items


async def _delete_chat_data(workspace, chats: list[ChatSpec]) -> None:
    """Delete transcript, snapshot, and checkpoint data for chats."""
    store = getattr(workspace, "transcript_store", None)
    session = getattr(workspace, "session", None)
    try:
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [(chat.session_id, chat.user_id, chat.channel) for chat in chats],
        )
        if session is not None:
            for chat in chats:
                channels = tuple(
                    target.channel
                    for target in chats
                    if target.session_id == chat.session_id
                    and target.user_id == chat.user_id
                )
                options = (
                    {"deleting_channels": channels}
                    if len(channels) > 1
                    else {}
                )
                await session.delete_session_state(
                    chat.session_id,
                    chat.user_id,
                    chat.channel,
                    **options,
                )
        if store is not None:
            for chat in chats:
                await asyncio.to_thread(
                    store.delete_session,
                    chat.session_id,
                    chat.user_id,
                    chat.channel,
                )

    except Exception as exc:
        logger.error("Failed to delete chat persistence", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete chat persistence",
        ) from exc


async def _delete_chats(workspace, mgr, chat_ids: list[str]) -> bool:
    """Block run registration and retain failed deletion for retry."""
    try:
        async with workspace.task_tracker.prevent_new_runs(chat_ids):
            catalog = await mgr.list_chats(archived=None)
            targets = [chat for chat in catalog if chat.id in chat_ids]
            await mgr.mark_deleting(chat_ids)
            for chat_id in chat_ids:
                await workspace.task_tracker.request_stop(chat_id)
            data_targets = _unshared_chat_data_targets(targets, catalog)
            identities = [
                (chat.session_id, chat.user_id, chat.channel)
                for chat in data_targets
            ]
            async with workspace.task_tracker.stop_session_writers(identities):
                if data_targets:
                    await _delete_chat_data(workspace, data_targets)
                return await mgr.delete_chats(chat_ids=chat_ids)
    except RunUnavailableError as exc:
        raise HTTPException(409, str(exc)) from exc


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
) -> DatabaseSession:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        DatabaseSession instance for the specified agent

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


class ChatForkRequest(BaseModel):
    """Completed turn selected as a new conversation boundary."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(..., min_length=1)


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


@router.get(f"/resolve", response_model=ChatResolution)
async def resolve_chat(
    chat_id: str = Query(..., min_length=1),
    current_agent_id: Optional[str] = Query(None),
):
    """Resolve a Console deep link using only persisted Chat metadata."""
    config = await run_sync_io(load_config)
    matches = await find_chat_matches(config, chat_id, current_agent_id)
    if not matches:
        raise HTTPException(404, f"Chat not found: {chat_id}")
    if len(matches) != 1:
        raise HTTPException(409, f"Chat reference is ambiguous: {chat_id}")
    return matches[0]


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


@router.get("/{chat_id}/fork-capability")
async def get_fork_capability(
    chat_id: str,
    turn_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Report exact native fork availability for one completed turn."""
    chat = await mgr.get_chat(chat_id)
    if chat is None or _is_app_owned_chat(chat):
        raise HTTPException(404, "Chat not found")
    backend = workspace.config.backend
    if backend == "qwenpaw":
        return {"can_fork": True, "reason": None}
    mode = get_provider(backend).capabilities.fork_mode
    if mode == "none":
        return {"can_fork": False, "reason": "Backend cannot fork"}
    if backend == "qoder":
        try:
            await run_sync_io(
                recover_qoder_boundaries,
                workspace.transcript_store,
                dict(
                    session_id=chat.session_id,
                    user_id=chat.user_id,
                    channel=chat.channel,
                ),
            )
        except (OSError, ValueError, ImportError):
            logger.warning("Cannot recover Qoder boundaries", exc_info=True)
    if backend == "codex":
        try:
            await recover_codex_boundaries(
                workspace.transcript_store,
                dict(
                    session_id=chat.session_id,
                    user_id=chat.user_id,
                    channel=chat.channel,
                ),
                binary=workspace.config.backend_settings.get("binary"),
            )
        except (OSError, ValueError, RuntimeError):
            logger.warning("Cannot recover Codex boundaries", exc_info=True)
    state = await run_sync_io(
        workspace.transcript_store.read_provider_state,
        session_id=chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
    )
    anchor = state["boundaries"].get(turn_id)
    available = bool(anchor and anchor["provider"] == backend)
    if mode == "latest":
        available = available and turn_id == next(
            reversed(state["boundaries"]),
            None,
        )
    return {
        "can_fork": available,
        "reason": (
            None
            if available
            else ("This turn has no completed native fork boundary")
        ),
    }


@router.post("/{chat_id}/fork", response_model=ChatSpec)
async def fork_chat_at_turn(
    chat_id: str,
    payload: ChatForkRequest,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> ChatSpec:
    """Create an independent conversation at one completed turn."""
    parent = await mgr.get_chat(chat_id)
    if parent is None or _is_app_owned_chat(parent):
        raise HTTPException(status_code=404, detail="Chat not found")
    store = getattr(workspace, "transcript_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation storage is not available",
        )

    backend = workspace.config.backend
    boundary = None
    if backend != "qwenpaw":
        capability = await get_fork_capability(
            chat_id,
            payload.turn_id,
            mgr,
            workspace,
        )
        if not capability["can_fork"]:
            raise HTTPException(409, capability["reason"])
        state = await run_sync_io(
            store.read_provider_state,
            session_id=parent.session_id,
            user_id=parent.user_id,
            channel=parent.channel,
        )
        boundary = state["boundaries"][payload.turn_id]

    child = ChatSpec(
        name=parent.name,
        session_id=f"fork-{uuid4()}",
        user_id=parent.user_id,
        channel=parent.channel,
        meta=dict(parent.meta),
        source=parent.source,
        group_id=parent.group_id,
        parent_chat_id=parent.id,
        fork_turn_id=payload.turn_id,
    )
    try:
        turn_seq = await run_sync_io(
            store.fork_at_turn,
            source_session_id=parent.session_id,
            source_user_id=parent.user_id,
            source_channel=parent.channel,
            source_chat_id=parent.id,
            turn_id=payload.turn_id,
            target_session_id=child.session_id,
            target_user_id=child.user_id,
            target_channel=child.channel,
            target_storage_id=child.storage_id,
            native_context=boundary is not None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    child = child.model_copy(update={"fork_turn_seq": turn_seq})
    external_id = None
    try:
        if boundary is not None:
            settings = dict(workspace.config.backend_settings)
            adapter = await workspace.harness_runtime.adapter(
                backend,
                settings,
            )
            external_id = await adapter.fork_session(
                boundary=boundary,
                cwd=workspace.workspace_dir.resolve(),
                settings=settings,
            )
            await run_sync_io(
                store.record_provider_fact,
                session_id=child.session_id,
                user_id=child.user_id,
                channel=child.channel,
                kind="session_bound",
                data={"provider": backend, "external_session_id": external_id},
            )
        return await mgr.create_chat(child)
    except BaseException as exc:
        if external_id:
            logger.error(
                "Native %s fork %s could not be registered for chat %s; "
                "the provider branch is retained for recovery",
                backend,
                external_id,
                child.id,
                exc_info=True,
            )
        await run_sync_io(
            store.delete_session,
            child.session_id,
            child.user_id,
            child.channel,
        )
        if boundary is not None and isinstance(exc, Exception):
            raise HTTPException(
                409,
                f"Native fork failed: {exc}",
            ) from exc
        raise


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
    deleted = await _delete_chats(workspace, mgr, chat_ids)
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


@router.put("/{chat_id}/decision-settings")
async def set_decision_settings(
    chat_id: str,
    enabled: bool = Body(..., strict=True),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Save a decision preference for an existing session."""
    from ...config.config import load_agent_config
    from ...services.session_thinking import decision_settings

    if await mgr.get_chat(chat_id) is None:
        raise HTTPException(404, "Chat not found")
    config = await asyncio.to_thread(load_agent_config, workspace.agent_id)
    settings = await asyncio.to_thread(decision_settings, config, enabled)
    if enabled and not settings["configured"]:
        raise HTTPException(
            422,
            "No agent or global decision model configured",
        )
    if await mgr.set_session_decision(chat_id, enabled) is None:
        raise HTTPException(404, "Chat not found")
    return settings


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
    after_message_id: str | None = None,
    before_message_id: str | None = None,
    limit: int = Query(5, ge=1, le=100),
    max_bytes: Annotated[
        int,
        Query(ge=2048, le=4 * 1024 * 1024),
    ] = 2
    * 1024
    * 1024,
    include_app_owned: bool = Query(
        True,
        description=(
            "Allow reading PawApp-owned chat history. The main Chat surface "
            "opts out so app dialogues stay inside their owning app."
        ),
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> ChatMessagePage:
    """Return one byte-bounded page of durable chat messages."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    if not include_app_owned and _is_app_owned_chat(chat):
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    try:
        page = await _read_history_page(
            workspace,
            chat,
            before=before,
            after_message_id=after_message_id,
            before_message_id=before_message_id,
            limit=limit,
            max_bytes=max_bytes,
        )
    except TranscriptPageBudgetError as exc:
        raise HTTPException(
            status_code=400,
            detail="History page byte limit is too small",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid history cursor",
        ) from exc
    if page is None:
        snapshot = await _read_workspace_legacy_snapshot(workspace, chat)
        if snapshot is None:
            return ChatMessagePage()
        return ChatMessagePage(messages=snapshot.messages)
    metadata = _history_metadata(page)
    return ChatMessagePage(
        messages=page.messages,
        **metadata.model_dump(),
    )


@router.get(
    "/{chat_id}/user-messages",
    response_model=ChatUserMessagePage,
)
async def get_chat_user_messages(
    chat_id: str,
    before: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    include_app_owned: bool = Query(False),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> ChatUserMessagePage:
    """Return lightweight user-message entries for history navigation."""
    chat = await mgr.get_chat(chat_id)
    if chat is None or (not include_app_owned and _is_app_owned_chat(chat)):
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    try:
        page = await _read_user_message_page(
            workspace,
            chat,
            before=before,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid history cursor",
        ) from exc
    if page is None:
        snapshot = await _read_workspace_legacy_snapshot(workspace, chat)
        if snapshot is None:
            return ChatUserMessagePage()
        items = _legacy_user_messages(snapshot.messages)
        return ChatUserMessagePage(total=len(items), items=items)
    return ChatUserMessagePage(
        total=page.total,
        items=[
            ChatUserMessage(
                message_id=item.message_id,
                client_message_id=item.client_message_id,
                preview=item.preview,
                created_at=item.created_at,
                anchor=item.anchor,
            )
            for item in page.items
        ],
        has_more=page.has_more,
        next_before=page.next_before,
        snapshot=page.snapshot,
    )


@router.get("/{chat_id}/user-messages/{message_id}")
async def get_chat_user_message_text(
    chat_id: str,
    message_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict[str, str]:
    """Recall one full input while keeping the navigation index lightweight."""
    chat = await mgr.get_chat(chat_id)
    if chat is None or _is_app_owned_chat(chat):
        raise HTTPException(status_code=404, detail="Chat not found")
    store = _history_store(workspace)
    text = None
    if store is not None:
        try:
            text = await asyncio.to_thread(
                store.get_user_message_text,
                session_id=chat.session_id,
                user_id=chat.user_id,
                channel=chat.channel,
                message_id=message_id,
            )
        except ConversationHistoryError as exc:
            raise HTTPException(
                status_code=503,
                detail="History temporarily unavailable",
            ) from exc
    if text is None:
        snapshot = await _read_workspace_legacy_snapshot(workspace, chat)
        if snapshot is not None:
            for message in snapshot.messages:
                if message.id == message_id and message.role == Role.USER:
                    text = _legacy_message_text(message)
                    break
    if text is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"text": text}


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    background_tasks: BackgroundTasks,
    full_history: bool = True,
    include_app_owned: bool = Query(
        True,
        description=(
            "Allow reading PawApp-owned chat history. The main Chat surface "
            "opts out so app dialogues stay inside their owning app."
        ),
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    session: DatabaseSession = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        request: FastAPI request (for agent context)
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: DatabaseSession dependency

    Returns:
        ChatHistory with messages and status (idle/running)

    Raises:
        HTTPException: If chat not found (404)
    """
    del background_tasks
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
    backend = workspace.config.backend

    transcript_page = await _read_history_page(
        workspace,
        chat_spec,
        limit=100 if full_history else 5,
        max_bytes=sys.maxsize if full_history else 2 * 1024 * 1024,
        max_content_blocks=sys.maxsize if full_history else 40,
    )
    if transcript_page is not None and (
        backend == "qwenpaw" or transcript_page.messages
    ):
        context_state = await _read_context_state(session, chat_spec)
        if full_history:
            messages = list(transcript_page.messages)
            page = transcript_page
            while page.has_more:
                page = await _read_history_page(
                    workspace,
                    chat_spec,
                    before=page.next_before,
                    limit=100,
                    max_bytes=sys.maxsize,
                    max_content_blocks=sys.maxsize,
                )
                if page is None:
                    raise HTTPException(
                        503,
                        "Conversation history unavailable",
                    )
                messages = list(page.messages) + messages
            return ChatHistory(
                messages=messages,
                status=status,
                history=ChatHistoryMetadata(),
                context_state=context_state,
            )
        return ChatHistory(
            messages=transcript_page.messages,
            status=status,
            history=_history_metadata(transcript_page),
            context_state=context_state,
        )
    if backend == "qwenpaw":
        if hasattr(session, "get_legacy_snapshot"):
            snapshot = await _read_legacy_snapshot(session, chat_spec)
            if snapshot is not None:
                return ChatHistory(
                    messages=snapshot.messages,
                    status=status,
                    history=ChatHistoryMetadata(),
                    context_state=None,
                )
            context_state = await _read_context_state(session, chat_spec)
            return ChatHistory(
                messages=[],
                status=status,
                history=ChatHistoryMetadata(),
                context_state=context_state,
            )

    context_state = await _read_context_state(session, chat_spec)
    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
        chat_spec.channel,
    )
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
            context_state=context_state,
        )

    messages = await asyncio.to_thread(session_state_to_messages, state)
    return ChatHistory(
        messages=messages,
        status=status,
        history=ChatHistoryMetadata(),
        context_state=context_state,
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
    deleted = await _delete_chats(workspace, mgr, [chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return {"deleted": True}
