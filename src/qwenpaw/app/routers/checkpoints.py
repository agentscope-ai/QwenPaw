# -*- coding: utf-8 -*-
"""Agent workspace checkpoint endpoints for the Console graph page."""

from __future__ import annotations

from dataclasses import asdict, replace
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...checkpoints.models import (
    CheckpointEntry,
    CheckpointError,
    RestoreResult,
)
from ...checkpoints.policy import session_file_path, session_key
from ...checkpoints.runtime import RUNTIME
from ...identity.runtime import is_multi_user_enabled
from ...access.dependencies import get_actor
from ...access.agent_repository import AgentResourceRole
from ..agent_context import get_agent_access_state, get_agent_for_request
from ..chats.models import ChatSpec

router = APIRouter(prefix="/workspace/checkpoints", tags=["checkpoints"])
logger = logging.getLogger(__name__)


class AutoRequest(BaseModel):
    enabled: bool


class SnapshotRequest(BaseModel):
    session_id: str = Field(min_length=1)
    user_id: str = ""
    channel: str = "console"
    name: str = Field(default="", max_length=200)


class RestoreRequest(BaseModel):
    commit: str = Field(min_length=7)
    session_id: str = Field(min_length=1)
    user_id: str = ""
    channel: str = "console"
    include_memory: bool = False
    include_files: bool = False
    files: list[str] | None = None


class GcRequest(BaseModel):
    compact: bool = False
    keep_count: int | None = Field(default=None, ge=0)
    keep_days: int | None = Field(default=None, ge=0)
    pre_restore_days: int | None = Field(default=None, ge=0)


class GcSettingsRequest(BaseModel):
    gc_keep_count: int = Field(ge=0, le=1_000_000)
    gc_keep_days: int = Field(ge=0, le=36_500)
    pre_restore_retention_days: int = Field(ge=0, le=36_500)


def _entry_payload(
    entry: CheckpointEntry,
    session_titles: dict[tuple[str, str, str], str] | None = None,
) -> dict:
    payload = asdict(entry)
    payload["sha"] = entry.commit[:12]
    payload["session_title"] = (session_titles or {}).get(
        (entry.channel, entry.user_id, entry.session_id),
        "",
    )
    return payload


def _restore_payload(result: RestoreResult) -> dict:
    return asdict(result)


async def _service(request: Request):
    workspace = await get_agent_for_request(request)
    try:
        if _uses_personal_runtime(request):
            from ..agent_context import get_files_workspace_access

            files_access = await get_files_workspace_access(request, workspace)
            service = await RUNTIME.get_for_workspace_dir_async(
                files_access.project.path,
            )
            service.workspace = workspace
            service.agent_id = workspace.agent_id
            service.checkpoint_scope = files_access.project.kind
            service.conversation_workspace_dir = workspace.workspace_dir
            return service
        return await RUNTIME.get_for_workspace_async(workspace)
    except CheckpointError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _trusted_user_id(request: Request, supplied_user_id: str) -> str:
    """多用户模式只接受认证中间件签发的用户身份。"""
    if not is_multi_user_enabled():
        return supplied_user_id
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return str(actor.user_id)


def _uses_personal_runtime(request: Request) -> bool:
    """仅使用成员的检查点必须绑定其独立运行空间。"""
    if not is_multi_user_enabled():
        return False
    role, historical_read_only = get_agent_access_state(request)
    return role is AgentResourceRole.USER and not historical_read_only


def _checkpoint_error(exc: CheckpointError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _workspace_sessions(service, *, user_id: str | None = None) -> list[dict]:
    """Return the complete lightweight chat catalog for this workspace."""
    workspace = service.workspace
    if workspace is None or not hasattr(workspace, "chat_manager"):
        return []
    try:
        chats = await workspace.chat_manager.list_chats(archived=None)
    except Exception:
        logger.warning(
            "Failed to load chat titles for checkpoint graph",
            exc_info=True,
        )
        return []
    return [
        {
            "session_key": session_key(
                channel=chat.channel,
                user_id=chat.user_id,
                session_id=chat.session_id,
            ),
            "session_id": chat.session_id,
            "user_id": chat.user_id,
            "channel": chat.channel,
            "title": chat.name or "",
            "archived": chat.archived,
        }
        for chat in chats
        if chat.session_id and (user_id is None or chat.user_id == user_id)
    ]


async def _visible_entries(service, request: Request, *, limit: int):
    """多用户模式只返回认证主体自身创建的检查点。"""
    if not is_multi_user_enabled():
        return await service.graph_entries(limit=limit)
    user_id = _trusted_user_id(request, "")
    return await service.graph_entries(limit=limit, user_id=user_id)


async def _require_restore_access(
    service,
    request: Request,
    *,
    commit: str,
    user_id: str,
    session_id: str,
    channel: str,
) -> CheckpointEntry | None:
    """恢复目标必须与可信 Agent、创建者和原始会话完全匹配。"""
    if not is_multi_user_enabled():
        return None
    agent_id = str(getattr(service, "agent_id", "") or "")
    try:
        entry = await service.resolve_target_entry(
            commit,
            session_id,
            user_id,
            channel,
        )
    except CheckpointError as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    if not (
        entry.commit == commit
        and entry.agent_id == agent_id
        and entry.session_id == session_id
        and entry.channel == channel
        and entry.user_id == user_id
    ):
        raise HTTPException(status_code=403, detail="forbidden")
    return entry


@router.get("/status")
async def checkpoint_status(request: Request) -> dict:
    service = await _service(request)
    try:
        entries = await _visible_entries(service, request, limit=1)
        auto_enabled, _debounce_seconds = await service.auto_settings()
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return {
        "auto_enabled": auto_enabled,
        "has_checkpoints": bool(entries),
        "scope": getattr(service, "checkpoint_scope", "agent_workspace"),
        "restore_mode": "new_chat" if is_multi_user_enabled() else "in_place",
    }


@router.patch("/auto")
async def set_checkpoint_auto(body: AutoRequest, request: Request) -> dict:
    service = await _service(request)
    try:
        auto_enabled, _debounce_seconds = await service.set_auto_enabled(
            body.enabled,
        )
    except (CheckpointError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"auto_enabled": auto_enabled}


@router.get("/graph")
async def checkpoint_graph(
    request: Request,
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict:
    service = await _service(request)
    try:
        entries = await _visible_entries(service, request, limit=limit)
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    user_id = _trusted_user_id(request, "") if is_multi_user_enabled() else None
    sessions = await _workspace_sessions(service, user_id=user_id)
    titles = {
        (item["channel"], item["user_id"], item["session_id"]): item["title"]
        for item in sessions
    }
    nodes = [_entry_payload(entry, titles) for entry in entries]
    return {
        "nodes": nodes,
        "sessions": sessions,
        "summary": {
            "total": len(nodes),
            "auto": sum(node["kind"] == "auto" for node in nodes),
            "snapshots": sum(node["kind"] == "snap" for node in nodes),
            "safety": sum(node["kind"] == "pre-restore" for node in nodes),
            "heads": sum(bool(node["is_head"]) for node in nodes),
        },
        "truncated": len(nodes) == limit,
    }


@router.post("/snapshot")
async def create_checkpoint(body: SnapshotRequest, request: Request) -> dict:
    service = await _service(request)
    try:
        result = await service.make_snapshot_result(
            kind="snap",
            session_id=body.session_id,
            user_id=_trusted_user_id(request, body.user_id),
            channel=body.channel,
            name=body.name or None,
            message=body.name,
        )
    except (CheckpointError, ValueError) as exc:
        raise _checkpoint_error(CheckpointError(str(exc))) from exc
    return asdict(result)


async def _restore(body: RestoreRequest, request: Request, *, dry_run: bool):
    service = await _service(request)
    user_id = _trusted_user_id(request, body.user_id)
    entry = await _require_restore_access(
        service,
        request,
        commit=body.commit,
        user_id=user_id,
        session_id=body.session_id,
        channel=body.channel,
    )
    restore_user_id = entry.user_id if entry is not None else user_id
    if is_multi_user_enabled():
        try:
            return await _restore_as_new_chat(
                service,
                body,
                user_id=restore_user_id,
                dry_run=dry_run,
            )
        except CheckpointError as exc:
            raise _checkpoint_error(exc) from exc
    kwargs = {
        "target": body.commit,
        "session_id": body.session_id,
        "user_id": restore_user_id,
        "channel": body.channel,
        "dry_run": dry_run,
    }
    try:
        if body.include_files:
            result = await service.restore_with_files(
                **kwargs,
                include_memory=body.include_memory,
                selected_files=(None if dry_run else tuple(body.files or ())),
            )
        elif body.include_memory:
            result = await service.restore_with_memory(**kwargs)
        else:
            result = await service.restore(**kwargs)
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return _restore_payload(result)


async def _restore_as_new_chat(
    service,
    body: RestoreRequest,
    *,
    user_id: str,
    dry_run: bool,
) -> dict:
    async with service.restore_copy_transaction(dry_run=dry_run):
        return await _restore_as_new_chat_unlocked(
            service,
            body,
            user_id=user_id,
            dry_run=dry_run,
        )


async def _restore_as_new_chat_unlocked(
    service,
    body: RestoreRequest,
    *,
    user_id: str,
    dry_run: bool,
) -> dict:
    """多用户恢复复制为新会话；源会话和历史记录保持不变。"""
    workspace = service.workspace
    chat_manager = getattr(workspace, "chat_manager", None)
    if chat_manager is None:
        raise HTTPException(status_code=409, detail="source_chat_unavailable")
    source_chat_id = await chat_manager.get_chat_id_by_session(
        body.session_id,
        body.channel,
        user_id=user_id,
    )
    if not source_chat_id:
        raise HTTPException(status_code=403, detail="forbidden")
    source_chat = await chat_manager.get_chat(source_chat_id)
    if source_chat is None or source_chat.user_id != user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    preview_session_id = f"preview-{body.commit[:12]}"
    if dry_run:
        session_preview = await service.restore_session_copy(
            target=body.commit,
            source_session_id=body.session_id,
            source_user_id=user_id,
            source_channel=body.channel,
            new_session_id=preview_session_id,
            new_user_id=user_id,
            new_channel=body.channel,
            dry_run=True,
        )
        if body.include_files or body.include_memory:
            file_preview = await service.restore_selected_files_copy(
                target=body.commit,
                source_session_id=body.session_id,
                source_user_id=user_id,
                source_channel=body.channel,
                selected_files=None,
                include_files=body.include_files,
                include_memory=body.include_memory,
                dry_run=True,
            )
            session_preview = replace(
                session_preview,
                include_memory=body.include_memory,
                include_files=True,
                deleted_paths=file_preview.deleted_paths,
                file_paths=file_preview.file_paths,
            )
        return _restore_payload(session_preview)

    new_session_id = str(uuid4())
    new_chat_id = str(uuid4())
    new_session_path = session_file_path(
        service.conversation_workspace_dir,
        session_id=new_session_id,
        user_id=user_id,
        channel=body.channel,
    )
    chat_created = False
    scope_result = None
    try:
        copied = await service.restore_session_copy(
            target=body.commit,
            source_session_id=body.session_id,
            source_user_id=user_id,
            source_channel=body.channel,
            new_session_id=new_session_id,
            new_user_id=user_id,
            new_channel=body.channel,
        )
        if body.include_files or body.include_memory:
            file_result = await service.restore_selected_files_copy(
                target=body.commit,
                source_session_id=body.session_id,
                source_user_id=user_id,
                source_channel=body.channel,
                selected_files=tuple(body.files or ()),
                include_files=body.include_files,
                include_memory=body.include_memory,
            )
            scope_result = file_result
            copied = replace(
                copied,
                include_memory=body.include_memory,
                include_files=True,
                deleted_paths=file_result.deleted_paths,
                file_paths=file_result.file_paths,
            )
        await chat_manager.create_chat(
            ChatSpec(
                id=new_chat_id,
                session_id=new_session_id,
                user_id=user_id,
                channel=body.channel,
                name=f"{source_chat.name} (restored)",
                meta={
                    "restored_from_chat_id": source_chat.id,
                    "restored_from_checkpoint": body.commit,
                },
            ),
        )
        chat_created = True
    except BaseException:
        if chat_created or await chat_manager.get_chat(new_chat_id) is not None:
            await chat_manager.delete_chats([new_chat_id])
        new_session_path.unlink(missing_ok=True)
        if scope_result is not None:
            await service.rollback_selected_scopes(scope_result)
        raise
    return _restore_payload(
        replace(
            copied,
            new_session_id=new_session_id,
            new_chat_id=new_chat_id,
        ),
    )


@router.post("/restore/preview")
async def preview_checkpoint_restore(
    body: RestoreRequest,
    request: Request,
) -> dict:
    return await _restore(body, request, dry_run=True)


@router.post("/restore")
async def apply_checkpoint_restore(
    body: RestoreRequest,
    request: Request,
) -> dict:
    if body.include_files and not body.files:
        raise HTTPException(
            status_code=400,
            detail="Select at least one file before restoring files.",
        )
    return await _restore(body, request, dry_run=False)


async def _run_gc(body: GcRequest, request: Request, *, dry_run: bool) -> dict:
    service = await _service(request)
    user_id = _trusted_user_id(request, "console")
    try:
        result = await service.gc(
            session_id="console",
            user_id="console",
            channel="console",
            compact=body.compact,
            all_sessions=True,
            dry_run=dry_run,
            keep_count=body.keep_count,
            keep_days=body.keep_days,
            pre_restore_days=body.pre_restore_days,
            creator_user_id=(user_id if is_multi_user_enabled() else None),
        )
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return asdict(result)


@router.post("/gc/preview")
async def preview_checkpoint_gc(body: GcRequest, request: Request) -> dict:
    return await _run_gc(body, request, dry_run=True)


@router.post("/gc")
async def apply_checkpoint_gc(body: GcRequest, request: Request) -> dict:
    return await _run_gc(body, request, dry_run=False)


@router.get("/gc/settings")
async def get_checkpoint_gc_settings(request: Request) -> dict:
    service = await _service(request)
    try:
        return await service.gc_settings()
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc


@router.patch("/gc/settings")
async def update_checkpoint_gc_settings(
    body: GcSettingsRequest,
    request: Request,
) -> dict:
    service = await _service(request)
    try:
        return await service.set_gc_settings(
            gc_keep_count=body.gc_keep_count,
            gc_keep_days=body.gc_keep_days,
            pre_restore_retention_days=body.pre_restore_retention_days,
        )
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc


@router.delete("")
async def reset_checkpoints(request: Request) -> dict:
    if is_multi_user_enabled() and getattr(request.state, "agent_access", None) is None:
        # 旧 /api 别名没有 scoped dependency，必须先解析可信角色再判断 reset。
        await get_agent_for_request(request)
    if is_multi_user_enabled() and not _uses_personal_runtime(request):
        role, historical_read_only = get_agent_access_state(request)
        if role is not AgentResourceRole.OWNER or historical_read_only:
            raise HTTPException(status_code=403, detail="forbidden")
    service = await _service(request)
    try:
        await service.reset()
        auto_enabled, _debounce_seconds = await service.auto_settings()
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return {"reset": True, "auto_enabled": auto_enabled}
