# -*- coding: utf-8 -*-
"""Attachment lifecycle APIs for the authenticated user and active Agent."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from ...access.agent_repository import agent_database_id
from ...access.dependencies import get_actor
from ..agent_context import get_agent_for_request
from ..agent_context import get_files_workspace_access
from ..attachments.models import AttachmentListItem
from ..attachments.service import AttachmentLifecycleError, AttachmentLifecycleService

router = APIRouter(prefix="/console/attachments", tags=["attachments"])


@router.get("", response_model=list[AttachmentListItem])
async def list_console_attachments(
    request: Request,
    lifecycle: Literal["temporary", "saved", "deleted"] | None = Query(None),
    conversation_id: UUID | None = Query(None),
) -> list[AttachmentListItem]:
    actor = get_actor(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    workspace = await get_agent_for_request(request)
    repository = workspace.chat_manager.conversation_repository
    if repository is None:
        raise HTTPException(
            status_code=503,
            detail="Attachment storage unavailable",
        )
    records = await repository.with_user(actor.user_id).list_owned_attachments(
        owner_user_id=actor.user_id,
        agent_id=agent_database_id(workspace.agent_id),
        lifecycle=lifecycle,
        conversation_id=conversation_id,
    )
    return [AttachmentListItem.from_record(record) for record in records]


async def _lifecycle_service(request: Request):
    actor = get_actor(request)
    workspace = await get_agent_for_request(request)
    repository = workspace.chat_manager.conversation_repository
    if actor.user_id is None or repository is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    access = await get_files_workspace_access(request, workspace)
    return AttachmentLifecycleService(repository=repository.with_user(actor.user_id), runtime_root=access.project.path), actor.user_id


@router.post("/{attachment_id}/save", response_model=AttachmentListItem)
async def save_attachment(request: Request, attachment_id: UUID, payload: dict | None = None) -> AttachmentListItem:
    service, owner_user_id = await _lifecycle_service(request)
    try:
        record = await service.save(attachment_id=attachment_id, owner_user_id=owner_user_id, target_path=(payload or {}).get("target_path"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="attachment_not_found") from exc
    except (AttachmentLifecycleError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, AttachmentLifecycleError) else 400, detail=str(exc)) from exc
    return AttachmentListItem.from_record(record)


@router.post("/{attachment_id}/move", response_model=AttachmentListItem)
async def move_attachment(request: Request, attachment_id: UUID, payload: dict) -> AttachmentListItem:
    target_path = payload.get("target_path")
    if not isinstance(target_path, str) or not target_path.strip():
        raise HTTPException(status_code=400, detail="target_path_required")
    service, owner_user_id = await _lifecycle_service(request)
    try:
        record = await service.move(attachment_id=attachment_id, owner_user_id=owner_user_id, target_path=target_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="attachment_not_found") from exc
    except (AttachmentLifecycleError, ValueError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, AttachmentLifecycleError) else 400, detail=str(exc)) from exc
    return AttachmentListItem.from_record(record)


@router.delete("/{attachment_id}", response_model=AttachmentListItem)
async def delete_attachment(request: Request, attachment_id: UUID) -> AttachmentListItem:
    service, owner_user_id = await _lifecycle_service(request)
    try:
        record = await service.delete(attachment_id=attachment_id, owner_user_id=owner_user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="attachment_not_found") from exc
    return AttachmentListItem.from_record(record)
