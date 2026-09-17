# -*- coding: utf-8 -*-
"""Chat management API."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agentscope.message import Msg
from agentscope.state import AgentState

from ...access.dependencies import get_actor
from ...access.agent_repository import agent_database_id
from ...identity.models import PlatformRole
from ...identity.runtime import is_multi_user_enabled
from ...persistence.repository_provider import CutoverDomain, load_cutover_policy
from ...schemas import Message
from .session import SafeJSONSession
from .manager import ChatManager, MAX_BATCH_SIZE
from .access import (
    ChatAccessDeniedError,
    require_chat_access,
    require_chat_owner,
    resolve_chat_user_id,
)
from .models import (
    BatchArchiveResult,
    ChatSpec,
    ChatUpdate,
    ChatHistory,
    ChatListItem,
)
from .repo import (
    AttachmentRecord,
    ConversationMemberRecord,
    ConversationShareEligibilityError,
    ShareCandidate,
)
from .utils import agentscope_msg_to_message, parse_legacy_memory_state
from ...services.project_directory import (
    resolve_effective_project_dir,
    session_project_dir,
)
from ...checkpoints.runtime import RUNTIME as CHECKPOINT_RUNTIME

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


async def _load_postgres_history_messages(
    *,
    manager: ChatManager,
    conversation_id: UUID,
    user_id: UUID,
) -> list[Message]:
    """从 PostgreSQL 消息事实重建前端历史，不回退到 Legacy 会话文件。"""
    repository = manager.conversation_repository
    if repository is None:
        raise RuntimeError("conversation_repository_unavailable")
    records = await repository.with_user(user_id).list_messages(conversation_id)
    projected: list[Message] = []
    for record in records:
        try:
            stored_content = record.content
            if isinstance(stored_content.get("qwenpaw_payload_ref"), dict):
                persistence = getattr(manager, "run_persistence", None)
                loader = getattr(persistence, "load_event_payload", None)
                if loader is None:
                    raise RuntimeError("chat_event_payload_loader_unavailable")
                stored_content = await loader(stored_content)
            if record.message_type == "legacy_snapshot":
                projected.extend(
                    agentscope_msg_to_message(Msg.model_validate(stored_content))
                )
                continue
            payload = {
                "id": str(record.id),
                "type": record.message_type,
                "role": record.role,
                "status": record.status,
                **stored_content,
            }
            projected.append(Message.model_validate(payload))
        except Exception as exc:
            logger.error(
                "PostgreSQL message projection failed for conversation=%s sequence=%s",
                conversation_id,
                record.sequence,
                exc_info=True,
            )
            raise RuntimeError("postgres_message_projection_failed") from exc
    return projected


def _protect_history_attachment_urls(
    messages: list,
    attachments: list[AttachmentRecord],
    *,
    hide_unowned_local_urls: bool,
) -> None:
    """将历史消息中的附件磁盘路径替换为所有者鉴权 URL。"""
    protected_by_storage_key = {
        record.storage_key: f"/api/console/attachments/{record.id}"
        for record in attachments
        if record.lifecycle != "deleted"
    }
    protected_urls = set(protected_by_storage_key.values())
    for message in messages:
        for content in getattr(message, "content", []) or []:
            content_type = getattr(content, "type", None)
            content_type = str(getattr(content_type, "value", content_type))
            url_field = {
                "file": "file_url",
                "image": "image_url",
                "audio": "data",
            }.get(content_type)
            if url_field is None:
                continue
            url = getattr(content, url_field, None)
            if not isinstance(url, str) or not url:
                continue
            if content_type == "audio":
                # Called only at the multi-user history boundary. Inline context
                # bytes are not a substitute for an accessible live attachment.
                protected_url = protected_by_storage_key.get(url)
                setattr(
                    content,
                    url_field,
                    protected_url or (url if url in protected_urls else ""),
                )
                continue
            protected_url = protected_by_storage_key.get(url)
            if protected_url is not None:
                setattr(content, url_field, protected_url)
                continue
            if hide_unowned_local_urls and not url.startswith(
                ("/api/console/attachments/", "http://", "https://", "data:")
            ):
                setattr(content, url_field, "")


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
    """Lightweight TaskTracker status for one Agent-scoped chat."""

    status: Literal["idle", "running"]


class AddConversationMemberRequest(BaseModel):
    """将一个已具备当前 Agent 访问资格的用户加入只读会话。"""

    user_id: UUID


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


def _trusted_chat_user_id(request: Request, requested_user_id: str) -> str:
    """解析当前请求允许使用的会话用户标识。"""
    try:
        return resolve_chat_user_id(
            actor=get_actor(request),
            requested_user_id=requested_user_id,
            multi_user=is_multi_user_enabled(),
        )
    except ChatAccessDeniedError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc


def _legacy_chat_user_ids(request: Request) -> frozenset[str]:
    """仅为管理员自己的 Agent 保留原项目 default 会话读取。"""
    access = getattr(request.state, "agent_access", None)
    actor = get_actor(request)
    if (
        getattr(access, "role", None) == "owner"
        and actor.platform_role is PlatformRole.ADMIN
    ):
        return frozenset({"default"})
    return frozenset()


async def _require_owned_chat(
    request: Request,
    mgr: ChatManager,
    chat_id: str,
) -> ChatSpec:
    """读取会话并隐藏其他用户会话的存在。"""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail=f"Chat not found: {chat_id}")
    try:
        return require_chat_owner(
            actor=get_actor(request),
            chat=chat,
            multi_user=is_multi_user_enabled(),
            legacy_user_ids=_legacy_chat_user_ids(request),
        )
    except ChatAccessDeniedError as exc:
        raise HTTPException(
            status_code=404, detail=f"Chat not found: {chat_id}"
        ) from exc


async def _require_owned_chat_ids(
    request: Request,
    mgr: ChatManager,
    workspace,
    chat_ids: list[str],
) -> list[ChatSpec]:
    """批量操作必须在写入前确认所有会话均属于当前用户。"""
    return [
        await _require_writable_chat(request, mgr, workspace, chat_id)
        for chat_id in chat_ids
    ]


async def _require_readable_chat(
    request: Request,
    mgr: ChatManager,
    workspace,
    chat_id: str,
):
    """按 PostgreSQL 权限事实源解析可读会话；未授权统一隐藏为 404。"""
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        conversation_id = UUID(chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc
    repository = mgr.conversation_repository
    if repository is None:
        raise HTTPException(
            status_code=503,
            detail="conversation_authority_unavailable",
        )
    bound = repository.with_user(actor.user_id)
    access = await bound.get_conversation_for_user(
        conversation_id=conversation_id,
        user_id=actor.user_id,
    )
    if access is None or access.conversation.agent_id != agent_database_id(
        workspace.agent_id
    ):
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        access = await require_chat_access(
            repository=bound,
            conversation=access.conversation,
            user_id=actor.user_id,
            access=access,
        )
    except ChatAccessDeniedError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat, access


async def _require_writable_chat(
    request: Request,
    mgr: ChatManager,
    workspace,
    chat_id: str,
) -> ChatSpec:
    """多用户写操作只接受 PostgreSQL owner，Legacy 保持原行为。"""
    if not is_multi_user_enabled():
        return await _require_owned_chat(request, mgr, chat_id)
    chat, access = await _require_readable_chat(request, mgr, workspace, chat_id)
    actor = get_actor(request)
    try:
        await require_chat_access(
            repository=mgr.conversation_repository.with_user(actor.user_id),
            conversation=access.conversation,
            user_id=actor.user_id,
            write=True,
            access=access,
        )
    except ChatAccessDeniedError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc
    return chat


async def _require_owned_conversation(
    request: Request,
    mgr: ChatManager,
    workspace,
    chat_id: str,
):
    """以 PostgreSQL 权限事实源验证当前 Agent 下的会话所有者。"""
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        conversation_id = UUID(chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc
    repository = mgr.conversation_repository
    if repository is None:
        raise HTTPException(
            status_code=503,
            detail="conversation_authority_unavailable",
        )
    bound = repository.with_user(actor.user_id)
    conversation = await bound.get_conversation(conversation_id)
    if (
        conversation is None
        or conversation.owner_user_id != actor.user_id
        or conversation.agent_id != agent_database_id(workspace.agent_id)
    ):
        raise HTTPException(status_code=404, detail="Chat not found")
    return bound, conversation, actor


@router.get(
    "/{chat_id}/members",
    response_model=list[ConversationMemberRecord],
)
async def list_conversation_members(
    chat_id: str,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    repository, conversation, actor = await _require_owned_conversation(
        request, mgr, workspace, chat_id
    )
    return await repository.list_members(
        conversation_id=conversation.id,
        owner_user_id=actor.user_id,
    )


@router.get(
    "/{chat_id}/share-candidates",
    response_model=list[ShareCandidate],
)
async def list_conversation_share_candidates(
    chat_id: str,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    repository, conversation, actor = await _require_owned_conversation(
        request, mgr, workspace, chat_id
    )
    return await repository.list_share_candidates(
        conversation_id=conversation.id,
        owner_user_id=actor.user_id,
    )


@router.post(
    "/{chat_id}/members",
    response_model=ConversationMemberRecord,
)
async def add_conversation_member(
    chat_id: str,
    payload: AddConversationMemberRequest,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    repository, conversation, actor = await _require_owned_conversation(
        request, mgr, workspace, chat_id
    )
    try:
        return await repository.add_viewer(
            conversation_id=conversation.id,
            user_id=payload.user_id,
            granted_by=actor.user_id,
        )
    except ConversationShareEligibilityError as exc:
        raise HTTPException(
            status_code=409,
            detail="conversation_share_candidate_unavailable",
        ) from exc


@router.delete("/{chat_id}/members/{user_id}", response_model=dict)
async def remove_conversation_member(
    chat_id: str,
    user_id: UUID,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    repository, conversation, actor = await _require_owned_conversation(
        request, mgr, workspace, chat_id
    )
    removed = await repository.remove_viewer(
        conversation_id=conversation.id,
        user_id=user_id,
        owner_user_id=actor.user_id,
    )
    return {"success": True, "removed": removed}


@router.get("", response_model=list[ChatListItem])
async def list_chats(
    request: Request,
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
    scope: Literal["all", "owned", "shared"] = Query(
        "all",
        description="Conversation access scope: all, owned, or shared",
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    When ``archived`` is omitted, returns all chats (both active and archived).
    Pass ``archived=false`` for active only,
    ``archived=true`` for archived only.
    """
    if is_multi_user_enabled():
        actor = get_actor(request)
        if actor.user_id is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        if user_id is not None:
            _trusted_chat_user_id(request, user_id)
        try:
            accessible = await mgr.list_accessible_chats(
                user_id=UUID(str(actor.user_id)),
                scope=scope,
                channel=channel,
                archived=archived,
            )
        except RuntimeError as exc:
            logger.error("Conversation authority unavailable", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="conversation_authority_unavailable",
            ) from exc
        chats_with_access = accessible
    else:
        if scope == "shared":
            return []
        chats = await mgr.list_chats(
            user_id=user_id,
            channel=channel,
            archived=archived,
        )
        chats_with_access = None
    tracker = workspace.task_tracker
    result = []
    rows = chats_with_access
    source_chats = [row.chat for row in rows] if rows is not None else chats
    for index, spec in enumerate(source_chats):
        status = await tracker.get_status(spec.id)
        if chats_with_access is None:
            result.append(
                ChatListItem.model_validate(spec.model_dump() | {"status": status})
            )
            continue
        assert rows is not None
        access = rows[index].access
        result.append(
            ChatListItem.model_validate(
                spec.model_dump()
                | {
                    "status": status,
                    "access_role": access.access_role,
                    "read_only": access.read_only,
                    "shared_by": access.shared_by_username,
                }
            )
        )
    return result


@router.post("", response_model=ChatSpec)
async def create_chat(
    payload: ChatSpec,
    request: Request,
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
        name=payload.name,
        session_id=payload.session_id,
        user_id=_trusted_chat_user_id(request, payload.user_id),
        channel=payload.channel,
        meta=payload.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    chat_ids: list[str],
    request: Request,
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
    owned_chats = await _require_owned_chat_ids(request, mgr, workspace, chat_ids)
    chats = {chat.id: chat for chat in owned_chats}
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
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Batch archive chats. Running chats are skipped."""
    await _require_owned_chat_ids(request, mgr, workspace, payload.chat_ids)
    tracker = workspace.task_tracker
    return await mgr.batch_archive(
        chat_ids=payload.chat_ids,
        get_status=tracker.get_status,
    )


@router.post("/actions/batch-unarchive", response_model=BatchArchiveResult)
async def batch_unarchive_chats(
    payload: BatchChatIds,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Batch unarchive chats."""
    await _require_owned_chat_ids(request, mgr, workspace, payload.chat_ids)
    return await mgr.batch_unarchive(chat_ids=payload.chat_ids)


@router.post("/{chat_id}/archive", response_model=ChatSpec)
async def archive_chat(
    chat_id: str,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Archive a single chat. Idempotent.

    Returns 409 if the chat is currently running.
    """
    await _require_writable_chat(request, mgr, workspace, chat_id)
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
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Unarchive a single chat. Idempotent."""
    await _require_writable_chat(request, mgr, workspace, chat_id)
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
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Return the Session override and effective project directory."""
    chat = await _require_owned_chat(request, mgr, chat_id)
    return await _project_directory_response(chat, workspace)


@router.put("/{chat_id}/project-dir")
async def set_chat_project_dir(
    chat_id: str,
    body: ProjectDirectoryUpdate,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Persist a validated Session project directory override."""
    await _require_writable_chat(request, mgr, workspace, chat_id)

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
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
) -> dict:
    """Clear the override and inherit the Agent default project directory."""
    await _require_writable_chat(request, mgr, workspace, chat_id)
    chat = await mgr.set_project_dir(chat_id, None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


# ----- Existing CRUD endpoints -----


@router.get("/{chat_id}/status", response_model=ChatStatusResponse)
async def get_chat_status(
    chat_id: str,
    workspace=Depends(get_workspace),
) -> ChatStatusResponse:
    """Return run status without loading and projecting full chat history."""
    status = await workspace.task_tracker.get_status(chat_id)
    return ChatStatusResponse(status=status)


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    request: Request,
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
    access = None
    if is_multi_user_enabled():
        chat_spec, access = await _require_readable_chat(
            request, mgr, workspace, chat_id
        )
    else:
        chat_spec = await _require_owned_chat(request, mgr, chat_id)

    status = await workspace.task_tracker.get_status(chat_id)
    use_postgres_history = (
        is_multi_user_enabled()
        and load_cutover_policy().read_uses_postgres(CutoverDomain.MESSAGES)
    )
    if use_postgres_history:
        actor = get_actor(request)
        if actor.user_id is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        try:
            messages = await _load_postgres_history_messages(
                manager=mgr,
                conversation_id=UUID(chat_id),
                user_id=actor.user_id,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        attachments = []
        if access is not None and not access.read_only:
            attachments = await mgr.conversation_repository.with_user(
                actor.user_id
            ).list_attachments(UUID(chat_id))
        _protect_history_attachment_urls(
            messages,
            attachments,
            hide_unowned_local_urls=bool(access and access.read_only),
        )
        return ChatHistory(
            messages=messages,
            status=status,
            access_role=access.access_role if access else "owner",
            read_only=access.read_only if access else False,
            shared_by=access.shared_by_username if access else None,
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
            access_role=access.access_role if access else "owner",
            read_only=access.read_only if access else False,
            shared_by=access.shared_by_username if access else None,
        )

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
    if is_multi_user_enabled():
        actor = get_actor(request)
        attachments = []
        if actor.user_id is not None and access is not None and not access.read_only:
            attachments = await mgr.conversation_repository.with_user(
                actor.user_id
            ).list_attachments(UUID(chat_id))
        _protect_history_attachment_urls(
            messages,
            attachments,
            hide_unowned_local_urls=bool(access and access.read_only),
        )
    return ChatHistory(
        messages=messages,
        status=status,
        access_role=access.access_role if access else "owner",
        read_only=access.read_only if access else False,
        shared_by=access.shared_by_username if access else None,
    )


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatUpdate,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
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
    await _require_writable_chat(request, mgr, workspace, chat_id)
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
    request: Request,
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
    chat = await _require_writable_chat(request, mgr, workspace, chat_id)
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
