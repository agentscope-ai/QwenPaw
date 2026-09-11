# -*- coding: utf-8 -*-
"""Agent workspace checkpoint endpoints for the Console graph page."""

from __future__ import annotations

from dataclasses import asdict
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...checkpoints.models import (
    CheckpointEntry,
    CheckpointError,
    RestoreResult,
)
from ...checkpoints.policy import session_key
from ...checkpoints.runtime import RUNTIME
from ..agent_context import get_agent_for_request

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
        return await RUNTIME.get_for_workspace_async(workspace)
    except CheckpointError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _checkpoint_error(exc: CheckpointError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _workspace_sessions(service) -> list[dict]:
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
        if chat.session_id
    ]


@router.get("/status")
async def checkpoint_status(request: Request) -> dict:
    service = await _service(request)
    try:
        entries = await service.graph_entries(limit=1)
        auto_enabled, _debounce_seconds = await service.auto_settings()
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return {
        "auto_enabled": auto_enabled,
        "has_checkpoints": bool(entries),
        "workspace_dir": str(service.workspace_dir),
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
        entries = await service.graph_entries(limit=limit)
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    sessions = await _workspace_sessions(service)
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
            user_id=body.user_id,
            channel=body.channel,
            name=body.name or None,
            message=body.name,
        )
    except (CheckpointError, ValueError) as exc:
        raise _checkpoint_error(CheckpointError(str(exc))) from exc
    return asdict(result)


async def _restore(body: RestoreRequest, request: Request, *, dry_run: bool):
    service = await _service(request)
    kwargs = {
        "target": body.commit,
        "session_id": body.session_id,
        "user_id": body.user_id,
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
    service = await _service(request)
    try:
        await service.reset()
        auto_enabled, _debounce_seconds = await service.auto_settings()
    except CheckpointError as exc:
        raise _checkpoint_error(exc) from exc
    return {"reset": True, "auto_enabled": auto_enabled}
