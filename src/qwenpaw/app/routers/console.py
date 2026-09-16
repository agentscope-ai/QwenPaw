# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""

from __future__ import annotations

from ...platform_ops.maintenance_lifecycle import admitted

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Union
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel
from starlette.responses import FileResponse, StreamingResponse

from qwenpaw.schemas import (
    AgentRequest,
    _coerce_content_item,
)
from ...access.dependencies import get_actor, require_platform_settings_manage
from ...access.agent_repository import agent_database_id
from ...envs import load_envs
from ...identity.runtime import is_multi_user_enabled
from ...platform_ops.log_redaction import redact_log_text
from ...utils.logging import LOG_FILE_PATH, sanitize_log_value
from ...utils.io_utils import run_sync_io
from ..agent_context import (
    get_agent_access_state,
    get_agent_for_request,
    get_files_workspace_access,
)
from ..approvals.display import approval_display_fields
from ..chats.access import (
    ChatAccessDeniedError,
    require_conversation_access,
    resolve_chat_user_id,
)
from ..chats.title_generator import generate_and_update_title
from ..chats.repo import AttachmentRecord
from ..utils import check_upload_size

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


# ── Background task store ──


@dataclass
class _BackgroundTask:
    """In-memory state for a background chat task."""

    status: str = "submitted"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    asyncio_task: Optional[asyncio.Task] = None
    owner_user_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""
    run_id: str = ""
    actor_context: Optional[Dict[str, Any]] = None


_bg_tasks: Dict[str, _BackgroundTask] = {}
_bg_lock = asyncio.Lock()


class MarkInboxReadRequest(BaseModel):
    event_ids: list[str] = []
    all: bool = False


class DeleteInboxEventsRequest(BaseModel):
    event_ids: list[str] = []


MAX_DEBUG_LOG_LINES = 1000
MAX_PERSONAL_LIBRARY_REFERENCES = 5


def _personal_library_service():
    """构造当前请求使用的个人资料库服务。"""
    from ...identity.runtime import get_identity_schema
    from ...personal_library.repository import PostgresPersonalLibraryRepository
    from ...personal_library.service import PersonalLibraryService

    return PersonalLibraryService(
        repository=PostgresPersonalLibraryRepository(
            schema=get_identity_schema(),
        ),
    )


def _requested_conversation_id(request_data: Union[AgentRequest, dict]) -> str:
    """读取前端显式提交的 PostgreSQL 会话 ID。"""
    if isinstance(request_data, dict):
        return str(request_data.get("conversation_id") or "").strip()
    return str(getattr(request_data, "conversation_id", "") or "").strip()


async def _require_console_conversation_write(
    request: Request,
    workspace,
    conversation_id: str,
) -> None:
    """现有会话的 Console 写操作必须由会话所有者发起。"""
    if not is_multi_user_enabled() or not conversation_id:
        return
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        parsed_id = UUID(conversation_id)
        await require_conversation_access(
            repository=workspace.chat_manager.conversation_repository,
            conversation_id=parsed_id,
            user_id=actor.user_id,
            expected_agent_id=agent_database_id(workspace.agent_id),
            write=True,
        )
    except (ValueError, ChatAccessDeniedError) as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc


async def _resolve_console_runtime_project(
    request: Request,
    workspace,
    *,
    project_dir: Path,
    project_source: str,
    conversation_id: str,
    authorized_project_dir: Path | None = None,
) -> tuple[Path, str]:
    """普通聊天按用户和会话隔离；显式项目保留已有编辑授权。"""
    from ...access.agent_repository import AgentResourceRole
    from ...services.workspace_files import resolve_private_task_directory

    if not is_multi_user_enabled():
        return project_dir, project_source
    role, historical_read_only = get_agent_access_state(request)
    if historical_read_only:
        raise HTTPException(status_code=403, detail="Historical workspace is read-only")
    if role is not AgentResourceRole.USER and project_source in {"session", "fork"}:
        allowed_root = Path(authorized_project_dir or workspace.workspace_dir).resolve()
        selected = Path(project_dir).resolve()
        if project_source == "fork":
            from ...agents.fork_project import resolve_allowed_fork_project_dir

            selected = resolve_allowed_fork_project_dir(
                str(selected), workspace_dir=workspace.workspace_dir,
                coding_project_dir=allowed_root,
            )
        elif not selected.is_relative_to(allowed_root):
            selected = None
        if selected is None:
            raise HTTPException(status_code=403, detail="Project directory is outside authorized scope")
        return selected, project_source
    path = await run_sync_io(
        resolve_private_task_directory,
        actor_user_id=get_actor(request).user_id,
        agent_id=workspace.agent_id,
        conversation_id=conversation_id,
    )
    return path, "user_task"


async def _bind_console_task_output(request, workspace, chat, request_context):
    """覆盖客户端运行路径字段，产物始终落在当前主体的私有会话目录。"""
    if not is_multi_user_enabled():
        return
    from ...services.workspace_files import resolve_private_task_directory

    request_context["task_output_dir"] = str(await run_sync_io(
        resolve_private_task_directory,
        actor_user_id=get_actor(request).user_id,
        agent_id=workspace.agent_id,
        conversation_id=str(chat.id),
    ))
    request_context["agent_id"] = workspace.agent_id
    request_context["workspace_dir"] = str(workspace.workspace_dir)
    request_context.pop("active_mode_project_dir", None)
    if request_context.get("project_dir_source") == "user_task":
        request_context.pop("fork_project_dir", None)


async def _resolve_console_upload_dir(
    request: Request,
    workspace,
    *,
    legacy_media_dir: Path,
) -> Path:
    """仅使用用户的聊天附件保存到个人运行空间。"""
    from ...access.agent_repository import AgentResourceRole

    role, historical_read_only = get_agent_access_state(request)
    if role is not AgentResourceRole.USER or historical_read_only:
        return legacy_media_dir
    access = await get_files_workspace_access(request, workspace)
    return access.project.path / "media"


async def _resolve_console_chat(
    workspace,
    *,
    requested_conversation_id: str,
    session_id: str,
    user_id: str,
    channel_id: str,
    name: str,
):
    """显式会话已鉴权时复用其 ChatSpec；仅新会话执行自动创建。"""
    if is_multi_user_enabled() and requested_conversation_id:
        chat = await workspace.chat_manager.get_chat(requested_conversation_id)
        if chat is None or str(getattr(chat, "id", "")) != requested_conversation_id:
            raise HTTPException(status_code=404, detail="Chat not found")
        return chat.model_copy(update={"user_id": user_id})
    return await workspace.chat_manager.get_or_create_chat(
        session_id,
        user_id,
        channel_id,
        name=name,
    )


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


def _attachment_id_from_url(value: str) -> UUID | None:
    """从受保护附件 URL 中提取不透明 ID。"""
    match = re.search(
        r"/api/console/attachments/([0-9a-fA-F-]{36})(?:[?#]|$)",
        value,
    )
    if match is None:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


def _part_value(part: Any, key: str) -> Any:
    return part.get(key) if isinstance(part, dict) else getattr(part, key, None)


def _set_part_value(part: Any, key: str, value: Any) -> None:
    if isinstance(part, dict):
        part[key] = value
    else:
        setattr(part, key, value)


async def _resolve_console_attachment_refs(
    request: Request,
    workspace,
    native_payload: dict[str, Any],
    *,
    conversation_id: str,
) -> None:
    """验证附件所有者和 Agent，并仅向运行时暴露实际磁盘路径。"""
    if not is_multi_user_enabled():
        return
    media_parts: list[tuple[Any, str, str]] = []
    for part in native_payload.get("content_parts") or []:
        raw_type = _part_value(part, "type")
        content_type = str(getattr(raw_type, "value", raw_type))
        url_key = {"image": "image_url", "file": "file_url", "audio": "data"}.get(
            content_type
        )
        if url_key is not None:
            media_parts.append((part, url_key, str(_part_value(part, url_key) or "")))
    if not media_parts:
        return
    try:
        parsed_conversation_id = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Chat not found") from exc
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    repository = workspace.chat_manager.conversation_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="Attachment storage unavailable")
    repository = repository.with_user(actor.user_id)
    expected_agent_id = agent_database_id(workspace.agent_id)
    for part, url_key, display_url in media_parts:
        attachment_id = _attachment_id_from_url(display_url)
        if attachment_id is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        record = await repository.get_attachment(
            attachment_id=attachment_id,
            owner_user_id=actor.user_id,
        )
        if (
            record is None
            or record.owner_user_id != actor.user_id
            or record.lifecycle == "deleted"
            or record.agent_id != expected_agent_id
            or record.conversation_id not in {None, parsed_conversation_id}
        ):
            raise HTTPException(status_code=404, detail="Attachment not found")
        target = Path(record.storage_key).resolve()
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Attachment not found")
        _set_part_value(part, "attachment_id", str(record.id))
        _set_part_value(part, "attachment_url", display_url)
        _set_part_value(part, url_key, str(target))


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


async def _apply_session_project_dir(
    workspace,
    chat,
    native_payload: dict[str, Any],
):
    """Persist a Session project selection before dispatch."""
    request_context = native_payload["meta"].get("request_context")
    if not isinstance(request_context, dict):
        return chat
    raw_value = request_context.pop("session_project_dir", None)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return chat

    def _resolve_target() -> Path:
        target = Path(raw_value).expanduser().resolve()
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
    updated = await workspace.chat_manager.set_project_dir(
        chat.id,
        str(target),
    )
    return updated or chat


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract run_key (ChatSpec.id), session_id, and native payload.

    run_key must be ChatSpec.id (chat_id) so it matches list_chats/get_chat.
    """
    from ...models.runtime import validate_candidate

    validate_candidate(request_data)
    if isinstance(request_data, AgentRequest):
        channel_id = getattr(request_data, "channel", None) or "console"
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = (
            list(request_data.input[0].content) if request_data.input else []
        )
        message_metadata = (
            request_data.input[0].metadata if request_data.input else None
        )
    else:
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = request_data.get("session_id", "default")
        input_data = request_data.get("input", [])
        content_parts = []
        message_metadata = None
        for content_part in input_data:
            if hasattr(content_part, "content"):
                content_parts.extend(list(content_part.content or []))
                message_metadata = getattr(
                    content_part,
                    "metadata",
                    message_metadata,
                )
            elif isinstance(content_part, dict) and "content" in content_part:
                # Coerce raw dicts to typed Content models so downstream
                # getattr checks (e.g. _content_has_text) see real attrs.
                content_parts.extend(
                    _coerce_content_item(c) for c in (content_part["content"] or [])
                )
                if isinstance(content_part.get("metadata"), dict):
                    message_metadata = content_part["metadata"]

    meta: dict = {
        "session_id": session_id,
        "user_id": sender_id,
    }

    # Preserve request_context (e.g. session-level approval_level)
    if isinstance(request_data, AgentRequest):
        rc = getattr(request_data, "request_context", None)
    else:
        rc = request_data.get("request_context")
    if isinstance(rc, dict) and rc:
        meta["request_context"] = rc

    native_payload = {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "content_parts": content_parts,
        "message_metadata": message_metadata,
        "meta": meta,
    }

    if isinstance(request_data, AgentRequest):
        mso = getattr(request_data, "model_slot_override", None)
    else:
        mso = request_data.get("model_slot_override")
    if mso is not None:
        native_payload["model_slot_override"] = mso

    return native_payload


def _apply_trusted_chat_identity(request: Request, native_payload: dict) -> None:
    """用认证主体覆盖客户端可伪造的 Console 会话用户标识。"""
    if not is_multi_user_enabled():
        return
    actor = get_actor(request)
    user_id = resolve_chat_user_id(
        actor=actor,
        requested_user_id=str(native_payload.get("sender_id") or "default"),
        multi_user=True,
    )
    native_payload["sender_id"] = user_id
    meta = native_payload.setdefault("meta", {})
    meta["user_id"] = user_id
    request_context = dict(meta.get("request_context") or {})
    request_context["user_id"] = user_id
    request_context["approval_user_id"] = user_id
    request_context["actor_context"] = {
        "user_id": user_id,
        "actor_type": actor.actor_type.value,
        "platform_role": (
            actor.platform_role.value if actor.platform_role is not None else None
        ),
        "admin_mode": actor.admin_mode,
        "request_id": actor.request_id,
    }
    meta["request_context"] = request_context


def _chat_file_resolver(request, workspace, conversation_id):
    from ..chat_file_references import ChatFileReferences
    from ...artifacts.repository import PostgresArtifactRepository
    from ...artifacts.service import ArtifactService
    from ...identity.runtime import get_identity_schema

    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(401, "not_authenticated")
    repository = workspace.chat_manager.conversation_repository
    return ChatFileReferences(
        owner=actor.user_id,
        agent_key=str(workspace.agent_id),
        conversation_id=conversation_id,
        profile_root=workspace.workspace_dir,
        library=_personal_library_service(),
        attachments=repository.with_user(actor.user_id)
        if repository is not None
        else None,
        artifacts=ArtifactService(
            repository=PostgresArtifactRepository(schema=get_identity_schema())
        ),
    )


@router.get("/file-references")
async def list_chat_file_references(
    request: Request, conversation_id: UUID | None = None
):
    workspace = await get_agent_for_request(request)
    if conversation_id:
        await _require_console_conversation_write(
            request, workspace, str(conversation_id)
        )
    return await _chat_file_resolver(
        request, workspace, str(conversation_id) if conversation_id else ""
    ).catalog()


async def _resolve_personal_library_references(
    request: Request,
    workspace: Any,
    native_payload: dict[str, Any],
) -> None:
    """按认证用户和当前 Agent 授权解析本轮显式选择的资料。"""
    meta = native_payload.setdefault("meta", {})
    request_context = dict(meta.get("request_context") or {})
    raw_ids = request_context.pop("personal_library_document_ids", [])
    request_context.pop("personal_library_references", None)
    # 只允许服务端写入检索轨迹，避免客户端伪造工具执行记录。
    request_context.pop("personal_library_retrieval_trace", None)
    file_refs = request_context.pop("file_references", [])
    if not isinstance(file_refs, list) or len(file_refs) > 5:
        raise HTTPException(400, "invalid_file_references")
    request_context.pop("resolved_file_references", None)
    meta["request_context"] = request_context
    if file_refs:
        if raw_ids:
            raise HTTPException(400, "mixed_file_reference_protocols")
        conversation_id = str(native_payload.get("_reference_conversation_id") or "")
        request_context["personal_library_references"] = await _chat_file_resolver(
            request,
            workspace,
            conversation_id,
        ).resolve(file_refs)
        return
    automatic_match = raw_ids in (None, [])
    if automatic_match:
        actor = get_actor(request)
        text = "\n".join(
            str(_part_value(part, "text") or "")
            for part in native_payload.get("content_parts") or []
            if _part_value(part, "type") == "text"
        )
        if actor.user_id is None or not text.strip():
            return
        documents = await _personal_library_service().match_prompt_documents(
            owner_user_id=actor.user_id,
            agent_key=str(workspace.agent_id),
            text=text,
        )
        raw_ids = [str(document.id) for document in documents]
        if not raw_ids:
            return
    if (
        not isinstance(raw_ids, list)
        or not raw_ids
        or len(raw_ids) > MAX_PERSONAL_LIBRARY_REFERENCES
    ):
        raise HTTPException(
            status_code=400,
            detail="invalid_personal_library_references",
        )

    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")

    from ...personal_library.service import (
        PersonalLibraryNotFound,
    )

    service = _personal_library_service()
    resolved: list[dict[str, Any]] = []
    seen: set[UUID] = set()
    try:
        for raw_id in raw_ids:
            document_id = UUID(str(raw_id))
            if document_id in seen:
                continue
            seen.add(document_id)
            result = await service.read_text_for_agent(
                owner_user_id=actor.user_id,
                agent_key=str(workspace.agent_id),
                document_id=document_id,
                limit=65_536,
            )
            resolved.append(
                {
                    "document_id": str(result.document.id),
                    "name": result.document.name,
                    "relative_path": result.document.relative_path,
                    "content": result.content,
                    "truncated": result.truncated,
                },
            )
    except (
        ValueError,
        PersonalLibraryNotFound,
    ) as exc:
        raise HTTPException(
            status_code=404,
            detail="personal_library_reference_unavailable",
        ) from exc

    request_context["personal_library_references"] = resolved
    if automatic_match:
        request_context["personal_library_retrieval_trace"] = {
            "mode": "automatic",
            "documents": [
                {
                    "document_id": item["document_id"],
                    "name": item["name"],
                }
                for item in resolved
            ],
        }
    meta["request_context"] = request_context


def _bind_run_context(
    native_payload: dict[str, Any],
    *,
    conversation_id: str,
    run_id: str,
) -> dict[str, Any]:
    """将实际会话与后台运行 ID 固定到不可变执行快照。"""
    meta = native_payload.setdefault("meta", {})
    request_context = dict(meta.get("request_context") or {})
    request_context["conversation_id"] = conversation_id
    request_context["run_id"] = run_id
    meta["request_context"] = request_context
    native_payload["_qwenpaw_run_id"] = run_id
    return request_context


def _is_reconnect_request(request_data: Union[AgentRequest, dict]) -> bool:
    """Return whether the chat request asks to attach to a running stream.

    ``AgentRequest`` uses ``extra="allow"`` and has no required fields,
    so FastAPI parses ``{"reconnect": true, ...}`` bodies into an
    ``AgentRequest`` instance — a dict-only check silently classified
    every reconnect as a fresh send and restarted a run with an empty
    input. Check both shapes.
    """
    if isinstance(request_data, dict):
        return request_data.get("reconnect") is True
    return getattr(request_data, "reconnect", None) is True


def _console_stream_access_scope(
    request: Request,
    chat_id: str,
) -> str | None:
    """将 Console 实时流绑定到可信用户与实际会话。"""
    if not is_multi_user_enabled():
        return None
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return f"{actor.user_id}:{chat_id}"


def _persisting_stream_source(workspace, chat, stream_fn):
    """兼容测试/插件提供的旧 ChatManager，同时接入新持久化包装器。"""
    wrapper = getattr(
        type(workspace.chat_manager),
        "persisting_stream_source",
        None,
    )
    if wrapper is None:
        return stream_fn
    return wrapper(workspace.chat_manager, chat, stream_fn)


def _with_personal_library_retrieval_trace(stream_fn):
    """把自动资料库检索作为只读工具轨迹发送并持久化。"""

    async def traced(payload: dict[str, Any]):
        request_context = (
            payload.get("meta", {}).get("request_context", {})
            if isinstance(payload, dict)
            else {}
        )
        trace = request_context.get("personal_library_retrieval_trace")
        documents = trace.get("documents") if isinstance(trace, dict) else None
        names = [
            str(item.get("name") or "").strip()
            for item in documents or []
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if names:
            call_id = f"auto_personal_library_{uuid.uuid4().hex}"
            call_message_id = f"msg_{uuid.uuid4().hex}"
            output_message_id = f"msg_{uuid.uuid4().hex}"
            arguments = json.dumps(
                {
                    "mode": "automatic",
                    "matched_documents": names,
                },
                ensure_ascii=False,
            )
            output = (
                f"自动检索命中 {len(names)} 份个人知识库资料："
                + "、".join(names)
            )

            def content(data: dict[str, Any]) -> list[dict[str, Any]]:
                return [
                    {
                        "data": data,
                        "type": "data",
                        "delta": False,
                        "index": 0,
                        "msg_id": None,
                        "object": "content",
                        "status": "completed",
                    },
                ]

            call_wire = {
                "id": call_message_id,
                "name": "assistant",
                "role": "assistant",
                "type": "plugin_call",
                "object": "message",
                "status": "completed",
                "content": content(
                    {
                        "name": "personal_library_search",
                        "call_id": call_id,
                        "arguments": arguments,
                    },
                ),
                "metadata": {
                    "qwenpaw_source": "automatic_personal_library_retrieval",
                },
            }
            output_wire = {
                "id": output_message_id,
                "name": "assistant",
                "role": "tool",
                "type": "plugin_call_output",
                "object": "message",
                "status": "completed",
                "content": content(
                    {
                        "name": "personal_library_search",
                        "call_id": call_id,
                        "state": "success",
                        "output": output,
                    },
                ),
                "metadata": {
                    "qwenpaw_source": "automatic_personal_library_retrieval",
                },
            }
            yield f"data: {json.dumps(call_wire, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps(output_wire, ensure_ascii=False)}\n\n"

        async for line in stream_fn(payload):
            yield line

    return traced


def _empty_sse_response() -> StreamingResponse:
    """An SSE response that terminates immediately."""

    async def _empty() -> AsyncGenerator[str, None]:
        return
        yield  # pragma: no cover — makes this an async generator

    return StreamingResponse(
        _empty(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
    is_reconnect = _is_reconnect_request(request_data)
    requested_conversation_id = _requested_conversation_id(request_data)
    if is_multi_user_enabled() and is_reconnect and not requested_conversation_id:
        raise HTTPException(
            status_code=400,
            detail="conversation_id is required for reconnect",
        )

    workspace = await get_agent_for_request(request)
    await _require_console_conversation_write(
        request,
        workspace,
        requested_conversation_id,
    )
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
    _apply_trusted_chat_identity(request, native_payload)
    if not is_reconnect:
        native_payload["_reference_conversation_id"] = requested_conversation_id
        await _resolve_personal_library_references(
            request,
            workspace,
            native_payload,
        )
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name, first_text = _extract_placeholder_name(
        native_payload["content_parts"],
    )
    chat = await _resolve_console_chat(
        workspace,
        requested_conversation_id=requested_conversation_id,
        session_id=session_id,
        user_id=native_payload["sender_id"],
        channel_id=native_payload["channel_id"],
        name=name,
    )
    if not is_reconnect:
        from ...models.runtime import prepare_console_model

        await prepare_console_model(
            request, workspace, chat, request_data, native_payload
        )
    await _resolve_console_attachment_refs(
        request,
        workspace,
        native_payload,
        conversation_id=chat.id,
    )
    if requested_conversation_id:
        native_payload["meta"]["session_id"] = chat.session_id
    tracker = workspace.task_tracker
    access_scope = _console_stream_access_scope(request, chat.id)

    if is_reconnect:
        queue = await tracker.attach(
            chat.id,
            access_scope=access_scope,
        )
        if queue is None:
            # The run finished (or never existed): reply with an
            # immediately-terminated SSE stream so the client's reader
            # completes normally and falls back to the persisted
            # history. Returning a JSON null here left the chat blank.
            return _empty_sse_response()
    else:
        chat = await _apply_session_project_dir(
            workspace,
            chat,
            native_payload,
        )
        _bind_run_context(
            native_payload,
            conversation_id=chat.id,
            run_id=str(uuid.uuid4()),
        )
        from ...config.config import load_agent_config
        from ...services.project_directory import (
            resolve_effective_project_dir,
            session_project_dir,
        )

        agent_config = await asyncio.to_thread(
            load_agent_config,
            workspace.agent_id,
        )
        project_dir, project_source = await asyncio.to_thread(
            resolve_effective_project_dir,
            workspace.workspace_dir,
            agent_config.project_dir,
            session_project_dir(chat.meta),
        )
        project_dir, project_source = await _resolve_console_runtime_project(
            request,
            workspace,
            project_dir=project_dir,
            project_source=project_source,
            conversation_id=str(chat.id),
            authorized_project_dir=Path(agent_config.project_dir or workspace.workspace_dir),
        )
        request_context = dict(
            native_payload["meta"].get("request_context") or {},
        )
        request_context["project_dir"] = str(project_dir)
        request_context["project_dir_source"] = project_source
        await _bind_console_task_output(request, workspace, chat, request_context)
        native_payload["meta"]["request_context"] = request_context

        # Title generation is only needed when starting a new run.
        if first_text and chat.name == name:
            asyncio.create_task(
                generate_and_update_title(
                    workspace=workspace,
                    chat_id=chat.id,
                    user_message=first_text,
                    placeholder_name=name,
                ),
            )
        stream_source = _persisting_stream_source(
            workspace,
            chat,
            _with_personal_library_retrieval_trace(console_channel.stream_one),
        )
        try:
            queue, _ = await tracker.attach_or_start(
                chat.id,
                native_payload,
                stream_source,
                owner=workspace,
                access_scope=access_scope,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=404,
                detail="Chat not found",
            ) from exc

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
            "X-QwenPaw-Chat-Id": chat.id,
            "Access-Control-Expose-Headers": "X-QwenPaw-Chat-Id",
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
    resolved_chat_id = chat_id
    try:
        UUID(chat_id)
    except ValueError:
        logger.debug(
            "[STOP API] Resolving session_id before ownership validation...",
        )
        chat_manager = workspace.chat_manager
        if chat_manager:
            actor = get_actor(request)
            resolved = await chat_manager.get_chat_id_by_session(
                session_id=chat_id,
                channel="console",
                user_id=(
                    str(actor.user_id)
                    if is_multi_user_enabled() and actor.user_id is not None
                    else None
                ),
            )
            if not resolved:
                if is_multi_user_enabled():
                    raise HTTPException(status_code=404, detail="Chat not found")
                return {"stopped": False}
            resolved_chat_id = resolved

    await _require_console_conversation_write(
        request,
        workspace,
        resolved_chat_id,
    )
    logger.debug(
        "[STOP API] Got workspace, calling task_tracker.request_stop...",
    )
    stopped = await workspace.task_tracker.request_stop(resolved_chat_id)

    logger.debug(
        "[STOP API] task_tracker.request_stop returned: stopped=%s",
        stopped,
    )
    return {"stopped": stopped}


@router.post("/upload", response_model=dict, summary="Upload file for chat")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(..., description="File to attach"),
    conversation_id: str | None = Query(
        None,
        description="Existing conversation id receiving this attachment",
    ),
) -> dict:
    """Save to console channel media_dir."""

    workspace = await get_agent_for_request(request)
    await _require_console_conversation_write(
        request,
        workspace,
        conversation_id if isinstance(conversation_id, str) else "",
    )
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    media_dir = await _resolve_console_upload_dir(
        request,
        workspace,
        legacy_media_dir=console_channel.media_dir,
    )
    media_dir.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    check_upload_size(data)
    safe_name = _safe_filename(file.filename or "file")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"

    path = (media_dir / stored_name).resolve()
    path.write_bytes(data)
    if is_multi_user_enabled():
        actor = get_actor(request)
        if actor.user_id is None:
            path.unlink(missing_ok=True)
            raise HTTPException(status_code=401, detail="not_authenticated")
        repository = workspace.chat_manager.conversation_repository
        if repository is None:
            path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=503,
                detail="Attachment storage unavailable",
            )
        parsed_conversation_id: UUID | None = None
        if conversation_id:
            try:
                parsed_conversation_id = UUID(conversation_id)
            except ValueError as exc:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=404, detail="Chat not found") from exc
        attachment_id = uuid.uuid4()
        media_type = file.content_type or mimetypes.guess_type(safe_name)[0]
        now = datetime.now(UTC)
        record = AttachmentRecord(
            id=attachment_id,
            agent_id=agent_database_id(workspace.agent_id),
            conversation_id=parsed_conversation_id,
            message_id=None,
            owner_user_id=actor.user_id,
            storage_key=str(path),
            original_name=safe_name,
            media_type=media_type or "application/octet-stream",
            size=len(data),
            content_hash=f"sha256:{hashlib.sha256(data).hexdigest()}",
            created_at=now,
            updated_at=now,
        )
        try:
            await repository.with_user(actor.user_id).add_attachment(record)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {
            "url": f"/api/console/attachments/{attachment_id}",
            "attachment_id": str(attachment_id),
            "file_name": safe_name,
            "size": len(data),
        }
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
    request: Request,
    lines: int = Query(
        200,
        ge=20,
        le=MAX_DEBUG_LOG_LINES,
        description="Number of trailing log lines to return",
    ),
) -> dict:
    """Return the tail of the project log file for the debug UI."""
    if is_multi_user_enabled():
        require_platform_settings_manage(get_actor(request))
    log_path = LOG_FILE_PATH.resolve()
    try:
        st = log_path.stat()
        return {
            "path": log_path.name,
            "exists": True,
            "lines": lines,
            "updated_at": st.st_mtime,
            "size": st.st_size,
            "content": redact_log_text(
                _tail_text_file(log_path, lines=lines),
                secret_values=load_envs().values(),
            ),
        }
    except FileNotFoundError:
        return {
            "path": log_path.name,
            "exists": False,
            "lines": lines,
            "updated_at": None,
            "size": 0,
            "content": "",
        }


@router.get("/push-messages")
async def get_push_messages(
    request: Request,
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages and approvals assigned to this user.

    Messages:
    - With session_id: consumed messages for that session
    - Without session_id: recent messages (all sessions, last 60s)

    In multi-user mode approvals are filtered by the authenticated user before
    serialization. Session filtering remains a frontend presentation concern.
    """
    from ..console_push_store import get_recent, take
    from ..approvals import get_approval_service

    # Get messages (session-specific or global)
    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()

    approval_svc = get_approval_service()
    approval_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    all_pending = await approval_svc.list_pending_for_user(approval_user_id)

    # Serialize approval data with root_session_id for frontend filtering
    approvals_data = [
        {
            "request_id": p.request_id,
            "session_id": p.session_id,
            "root_session_id": p.root_session_id,
            "owner_agent_id": p.owner_agent_id,
            "agent_id": p.agent_id,
            "tool_name": p.tool_name,
            **approval_display_fields(p),
            "severity": p.severity,
            "findings_count": p.findings_count,
            "findings_summary": p.result_summary,
            "tool_params": p.extra.get("tool_call", {}).get("input", {}),
            "source_type": p.extra.get("source_type", "tool_guard"),
            "driver": p.extra.get("driver"),
            "created_at": p.created_at,
            "timeout_seconds": p.timeout_seconds,
        }
        for p in all_pending
    ]

    return {"messages": messages, "pending_approvals": approvals_data}


@router.get("/inbox/events")
async def get_inbox_events(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source_type: str | None = Query(None),
    source_types: list[str] | None = Query(None),
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    unread_only: bool = Query(False),
):
    from ..inbox_store import query_events

    selected_sources = set(source_types or [])
    recipient_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    if source_type:
        selected_sources.add(source_type)
    events, total, unread_count = await query_events(
        limit=limit,
        offset=offset,
        source_types=selected_sources or None,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
        recipient_user_id=recipient_user_id,
    )
    return {
        "events": events,
        "total": total,
        "unread_count": unread_count,
    }


@router.post("/inbox/read")
async def post_mark_inbox_read(
    payload: MarkInboxReadRequest,
    request: Request,
):
    from ..inbox_store import mark_all_read, mark_read

    recipient_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    if payload.all:
        updated = await mark_all_read(recipient_user_id=recipient_user_id)
    else:
        updated = await mark_read(
            payload.event_ids,
            recipient_user_id=recipient_user_id,
        )
    return {"updated": updated}


@router.delete("/inbox/events/{event_id}")
async def delete_inbox_event(event_id: str, request: Request):
    from ..inbox_store import delete_event
    from ..inbox_trace_store import delete_trace

    recipient_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    deleted, run_id, run_id_still_referenced = await delete_event(
        event_id,
        recipient_user_id=recipient_user_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="event not found")
    trace_deleted = False
    if not is_multi_user_enabled() and run_id and not run_id_still_referenced:
        trace_deleted = await delete_trace(run_id)
    return {
        "deleted": True,
        "trace_deleted": trace_deleted,
        "run_id": run_id,
    }


@router.post("/inbox/events/delete")
async def delete_inbox_events(
    payload: DeleteInboxEventsRequest,
    request: Request,
):
    from ..inbox_store import delete_events

    recipient_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    deleted = await delete_events(
        payload.event_ids,
        recipient_user_id=recipient_user_id,
    )
    return {"deleted": deleted}


@router.get("/inbox/traces/{run_id}")
async def get_inbox_trace(run_id: str, request: Request):
    from ..inbox_store import has_run_reference
    from ..inbox_trace_store import get_trace

    recipient_user_id = (
        str(get_actor(request).user_id) if is_multi_user_enabled() else None
    )
    if not await has_run_reference(
        run_id,
        recipient_user_id=recipient_user_id,
    ):
        raise HTTPException(status_code=404, detail="trace not found")
    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail="trace not found",
        )
    return trace


# ── Background chat task endpoints ──


def _parse_sse_payload(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE data line into a dict."""
    stripped = line.strip()
    if stripped.startswith("data: "):
        try:
            return json.loads(stripped[6:])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


async def _finalize_background_fork(
    project_dir: str,
    branch: str,
    *,
    scope_id: str,
) -> bool:
    """Finish an in-flight fork commit before publishing task state.

    Cancelling an ``asyncio.to_thread`` await cannot stop its worker thread.
    Once finalization starts, keep waiting for its authoritative result so the
    task API, fork registry, and branch HEAD cannot report conflicting states.
    """
    from qwenpaw.agents.fork_project import finalize_fork_worktree_or_fail

    finalizer = asyncio.create_task(
        asyncio.to_thread(
            finalize_fork_worktree_or_fail,
            project_dir,
            branch,
            message=f"fork worker {branch}",
            expected_scope=scope_id or None,
        ),
    )
    while True:
        try:
            return await asyncio.shield(finalizer)
        except asyncio.CancelledError:
            if finalizer.done():
                return finalizer.result()


async def _mark_background_fork_failed(
    project_dir: str,
    branch: str,
    *,
    scope_id: str,
    reason: str,
    context: str,
) -> None:
    """Best-effort fork failure bookkeeping for background tasks."""
    if not project_dir or not branch:
        return
    try:
        from qwenpaw.agents.fork_project import mark_fork_failed

        await asyncio.to_thread(
            mark_fork_failed,
            project_dir,
            branch,
            reason=reason,
            expected_scope=scope_id or None,
        )
    except Exception:
        logger.warning(
            "mark_fork_failed after %s failed for %s",
            context,
            sanitize_log_value(branch),
            exc_info=True,
        )


@router.post(
    "/chat/task",
    status_code=200,
    summary="Submit a background chat task",
)
async def post_console_chat_task(  # pylint: disable=too-many-statements
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> dict:
    """Run an agent chat as a background task.

    Returns a ``task_id`` immediately. Poll status via
    ``GET /console/chat/task/{task_id}``.
    """
    workspace = await get_agent_for_request(request)
    await _require_console_conversation_write(
        request,
        workspace,
        _requested_conversation_id(request_data),
    )
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    native_payload = _extract_session_and_payload(request_data)
    _apply_trusted_chat_identity(request, native_payload)
    native_payload["_reference_conversation_id"] = _requested_conversation_id(
        request_data
    )
    await _resolve_personal_library_references(
        request,
        workspace,
        native_payload,
    )
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name, _ = _extract_placeholder_name(native_payload["content_parts"])
    requested_conversation_id = _requested_conversation_id(request_data)
    chat = await _resolve_console_chat(
        workspace,
        requested_conversation_id=requested_conversation_id,
        session_id=session_id,
        user_id=native_payload["sender_id"],
        channel_id=native_payload["channel_id"],
        name=name,
    )
    from ...models.runtime import prepare_console_model

    await prepare_console_model(request, workspace, chat, request_data, native_payload)
    await _resolve_console_attachment_refs(
        request,
        workspace,
        native_payload,
        conversation_id=chat.id,
    )
    if requested_conversation_id:
        native_payload["meta"]["session_id"] = chat.session_id
    chat = await _apply_session_project_dir(
        workspace,
        chat,
        native_payload,
    )

    task_timeout: Optional[float] = None
    fork_project_dir = ""
    fork_worktree_branch = ""
    fork_scope_id = ""
    if isinstance(request_data, dict):
        task_timeout = request_data.get("timeout")
        rc = request_data.get("request_context")
        if isinstance(rc, dict):
            fork_project_dir = str(rc.get("fork_project_dir") or "")
            fork_worktree_branch = str(
                rc.get("fork_worktree_branch") or "",
            )
            fork_scope_id = str(rc.get("fork_scope_id") or "")
    elif hasattr(request_data, "timeout"):
        task_timeout = getattr(request_data, "timeout", None)
        rc = getattr(request_data, "request_context", None)
        if isinstance(rc, dict):
            fork_project_dir = str(rc.get("fork_project_dir") or "")
            fork_worktree_branch = str(
                rc.get("fork_worktree_branch") or "",
            )
            fork_scope_id = str(rc.get("fork_scope_id") or "")

    if is_multi_user_enabled():
        from ...access.agent_repository import AgentResourceRole

        role, _ = get_agent_access_state(request)
        if role is AgentResourceRole.USER:
            fork_project_dir = ""
            fork_worktree_branch = ""
            fork_scope_id = ""

    from ...config.config import load_agent_config
    from ...services.project_directory import (
        resolve_effective_project_dir,
        session_project_dir,
    )

    agent_config = await asyncio.to_thread(
        load_agent_config,
        workspace.agent_id,
    )
    project_dir, project_source = await asyncio.to_thread(
        resolve_effective_project_dir,
        workspace.workspace_dir,
        agent_config.project_dir,
        session_project_dir(chat.meta),
        None,
        None,
        fork_project_dir or None,
    )
    project_dir, project_source = await _resolve_console_runtime_project(
        request,
        workspace,
        project_dir=project_dir,
        project_source=project_source,
        conversation_id=str(chat.id),
        authorized_project_dir=Path(agent_config.project_dir or workspace.workspace_dir),
    )
    run_id = str(uuid.uuid4())
    request_context = _bind_run_context(
        native_payload,
        conversation_id=chat.id,
        run_id=run_id,
    )
    request_context["project_dir"] = str(project_dir)
    request_context["project_dir_source"] = project_source
    await _bind_console_task_output(request, workspace, chat, request_context)
    native_payload["meta"]["request_context"] = request_context

    bg = _BackgroundTask(
        status="running",
        started_at=time.time(),
        owner_user_id=str(native_payload["sender_id"]),
        agent_id=str(workspace.agent_id),
        conversation_id=str(chat.id),
        run_id=run_id,
        actor_context=dict(request_context.get("actor_context") or {}),
    )

    async def _run() -> None:
        last_response: Optional[Dict[str, Any]] = None
        try:
            stream_source = _persisting_stream_source(
                workspace,
                chat,
                _with_personal_library_retrieval_trace(
                    console_channel.stream_one,
                ),
            )
            async for sse_line in stream_source(native_payload):
                parsed = _parse_sse_payload(sse_line)
                if parsed and parsed.get("type") != "turn_usage":
                    last_response = parsed

            # Fork subagents: commit dirty worktree so branch tips are
            # mergeable before exposing a completed task result.
            if fork_project_dir and fork_worktree_branch:
                try:
                    finalized = await _finalize_background_fork(
                        fork_project_dir,
                        fork_worktree_branch,
                        scope_id=fork_scope_id,
                    )
                except Exception:
                    logger.warning(
                        "Background fork finalize failed for %s (%s)",
                        sanitize_log_value(fork_worktree_branch),
                        sanitize_log_value(fork_project_dir),
                        exc_info=True,
                    )
                    await _mark_background_fork_failed(
                        fork_project_dir,
                        fork_worktree_branch,
                        scope_id=fork_scope_id,
                        reason="Fork finalization raised an exception",
                        context="finalize error",
                    )
                    finalized = False
                if not finalized:
                    bg.status = "finished"
                    bg.finished_at = time.time()
                    bg.result = {
                        "status": "failed",
                        "error": {
                            "message": "Failed to finalize fork worktree",
                        },
                    }
                    return
        except asyncio.CancelledError:
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": "Task cancelled"},
            }
            await _mark_background_fork_failed(
                fork_project_dir,
                fork_worktree_branch,
                scope_id=fork_scope_id,
                reason="Task cancelled",
                context="cancel",
            )
            return
        except Exception as exc:
            logger.error(
                "Background task failed (error_type=%s)",
                type(exc).__name__,
            )
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": "task_execution_failed"},
            }
            await _mark_background_fork_failed(
                fork_project_dir,
                fork_worktree_branch,
                scope_id=fork_scope_id,
                reason="Task execution failed",
                context="task error",
            )
            return

        bg.status = "finished"
        bg.finished_at = time.time()
        if last_response is not None:
            bg.result = {
                "status": "completed",
                "session_id": session_id,
                **last_response,
            }
        else:
            bg.result = {
                "status": "completed",
                "session_id": session_id,
                "output": [],
            }

    async def _admitted_run() -> None:
        try:
            await admitted(_run)()
        except asyncio.CancelledError:
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": "Task cancelled before admission"},
            }
            raise
        except Exception:
            logger.exception("Background task admission failed")
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": "task_admission_failed"},
            }

    atask = asyncio.create_task(_admitted_run())
    bg.asyncio_task = atask

    if task_timeout is not None and task_timeout > 0:

        async def _timeout_guard() -> None:
            await asyncio.sleep(task_timeout)
            if not atask.done():
                atask.cancel()

        asyncio.create_task(_timeout_guard())

    async with _bg_lock:
        _bg_tasks[task_id] = bg

    return {"task_id": task_id}


@router.get(
    "/chat/task/{task_id}",
    status_code=200,
    summary="Check background chat task status",
)
async def get_console_chat_task(
    task_id: str,
    request: Request = None,
) -> dict:
    """Return the current status of a background chat task."""
    async with _bg_lock:
        bg = _bg_tasks.get(task_id)
    if bg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}",
        )
    if is_multi_user_enabled() and request is not None:
        actor = get_actor(request)
        if actor.user_id is None or str(actor.user_id) != bg.owner_user_id:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    response: Dict[str, Any] = {
        "status": bg.status,
        "conversation_id": bg.conversation_id,
        "run_id": bg.run_id,
    }
    if bg.started_at is not None:
        response["started_at"] = bg.started_at
    if bg.status == "finished" and bg.result is not None:
        response["result"] = bg.result
    return response


@router.api_route(
    "/attachments/{attachment_id}",
    methods=["GET", "HEAD"],
    summary="Download one owned chat attachment",
)
async def get_console_attachment(
    attachment_id: UUID,
    request: Request,
):
    """只允许上传者读取附件，避免绝对路径成为访问凭证。"""
    if not is_multi_user_enabled():
        raise HTTPException(status_code=404, detail="Attachment not found")
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    from ...identity.runtime import get_identity_schema
    from ..chats.repo import PostgresConversationRepository

    repository = PostgresConversationRepository(
        schema=get_identity_schema(),
    ).with_user(actor.user_id)
    record = await repository.get_attachment(
        attachment_id=attachment_id,
        owner_user_id=actor.user_id,
    )
    if record is None or record.lifecycle == "deleted":
        raise HTTPException(status_code=404, detail="Attachment not found")
    target = Path(record.storage_key).resolve()
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        target,
        filename=record.original_name,
        media_type=record.media_type,
    )
