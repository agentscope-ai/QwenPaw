# -*- coding: utf-8 -*-
"""当前用户在当前 Agent 下的私有资料库 API。"""

from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...access.dependencies import get_actor
from ...identity.runtime import get_identity_schema
from ...personal_library.repository import PostgresPersonalLibraryRepository
from ...personal_library.service import (
    PersonalLibraryConflict,
    PersonalLibraryNotFound,
    PersonalLibrarySourceDenied,
    PersonalLibraryService,
)
from ..agent_context import get_agent_for_request
from ..owned_content import owner_agent_key
from ..utils import check_upload_size

router = APIRouter(prefix="/console/personal-library", tags=["personal-library"])


class PersonalLibraryDocumentResponse(BaseModel):
    id: UUID
    relative_path: str
    name: str
    media_type: str
    size: int
    sha256: str
    created_at: datetime
    updated_at: datetime


class PersonalLibraryDocumentContentResponse(PersonalLibraryDocumentResponse):
    content: str
    offset: int
    next_offset: int | None
    truncated: bool


class CreateTextDocument(BaseModel):
    path: str = Field(min_length=1)
    content: str
    overwrite: bool = False


class PersonalLibraryPage(BaseModel):
    items: list[PersonalLibraryDocumentResponse]
    total: int


class MoveDocument(BaseModel):
    destination_path: str = Field(min_length=1, max_length=1024)
    expected_updated_at: datetime


class LibraryIndexStatusResponse(BaseModel):
    document_id: UUID
    status: Literal["pending", "ready", "partial", "empty", "unsupported", "too_large", "failed", "missing", "unavailable"]
    indexed_characters: int
    updated_at: datetime | None


class RebuildLibraryIndex(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=10)


class AttachmentImport(BaseModel):
    attachment_id: UUID
    destination_path: str = Field(min_length=1)
    overwrite: bool = False


class RuntimeFileImport(BaseModel):
    source_path: str = Field(min_length=1)
    destination_path: str = Field(min_length=1)
    overwrite: bool = False


def _get_service() -> PersonalLibraryService:
    return PersonalLibraryService(
        repository=PostgresPersonalLibraryRepository(schema=get_identity_schema()),
    )


def _owner_id(request: Request) -> UUID:
    user_id = get_actor(request).user_id
    if user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user_id


def _document_response(document) -> PersonalLibraryDocumentResponse:
    return PersonalLibraryDocumentResponse(
        id=document.id,
        relative_path=document.relative_path,
        name=document.name,
        media_type=document.media_type,
        size=document.size,
        sha256=document.sha256,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get("/index", response_model=list[LibraryIndexStatusResponse])
async def index_status(request: Request):
    return await _get_service().index_status(owner_user_id=_owner_id(request), agent_key=owner_agent_key(request))


@router.post("/index/rebuild", response_model=list[LibraryIndexStatusResponse])
async def rebuild_index(request: Request, payload: RebuildLibraryIndex):
    workspace = await get_agent_for_request(request)
    try:
        return await _get_service().rebuild_index(
            owner_user_id=_owner_id(request), agent_key=workspace.agent_id,
            document_ids=payload.document_ids,
        )
    except PersonalLibraryNotFound as exc:
        raise HTTPException(status_code=404, detail="library_document_not_found") from exc
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(status_code=503, detail="library_index_rebuild_failed") from exc


@router.post(
    "/documents/text",
    response_model=PersonalLibraryDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_text_document(
    request: Request,
    payload: CreateTextDocument,
) -> PersonalLibraryDocumentResponse:
    workspace = await get_agent_for_request(request)
    try:
        document = await _get_service().create_text(
            owner_user_id=_owner_id(request),
            relative_path=payload.path,
            content=payload.content,
            overwrite=payload.overwrite,
            agent_key=workspace.agent_id,
        )
    except PersonalLibraryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_response(document)


@router.post(
    "/documents/upload",
    response_model=PersonalLibraryDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="File to store in the personal library"),
) -> PersonalLibraryDocumentResponse:
    """上传一个文件到当前认证用户的个人资料库。"""
    data = await file.read()
    check_upload_size(data)
    workspace = await get_agent_for_request(request)
    try:
        document = await _get_service().save_upload(
            owner_user_id=_owner_id(request),
            filename=file.filename or "file",
            content=data,
            media_type=file.content_type or "application/octet-stream",
            agent_key=workspace.agent_id,
        )
    except PersonalLibraryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _document_response(document)


@router.get("/documents", response_model=list[PersonalLibraryDocumentResponse])
async def list_documents(
    request: Request,
    path: str = Query(""),
) -> list[PersonalLibraryDocumentResponse]:
    try:
        documents = await _get_service().list_directory(
            owner_user_id=_owner_id(request),
            path=path,
            agent_key=owner_agent_key(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_document_response(document) for document in documents]


@router.get("/documents/page", response_model=PersonalLibraryPage)
async def list_documents_page(
    request: Request,
    query: str = Query("", max_length=256),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PersonalLibraryPage:
    documents, total = await _get_service().list_page(
        owner_user_id=_owner_id(request), agent_key=owner_agent_key(request),
        query=query, offset=offset, limit=limit,
    )
    return PersonalLibraryPage(items=[_document_response(doc) for doc in documents], total=total)


@router.patch("/documents/{document_id}", response_model=PersonalLibraryDocumentResponse)
async def move_document(request: Request, document_id: UUID, payload: MoveDocument):
    workspace = await get_agent_for_request(request)
    try:
        document = await _get_service().move(
            owner_user_id=_owner_id(request), agent_key=workspace.agent_id,
            document_id=document_id, destination_path=payload.destination_path,
            expected_updated_at=payload.expected_updated_at,
        )
    except (PersonalLibraryNotFound, PersonalLibraryConflict, ValueError) as exc:
        raise _source_error(exc) from exc
    return _document_response(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    request: Request, document_id: UUID,
    expected_updated_at: datetime = Query(...),
):
    workspace = await get_agent_for_request(request)
    try:
        await _get_service().delete(
            owner_user_id=_owner_id(request), agent_key=workspace.agent_id,
            document_id=document_id, expected_updated_at=expected_updated_at,
        )
    except (PersonalLibraryNotFound, PersonalLibraryConflict, ValueError) as exc:
        raise _source_error(exc) from exc


@router.get(
    "/documents/{document_id}/text",
    response_model=PersonalLibraryDocumentContentResponse,
)
async def read_text_document(
    request: Request,
    document_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(65_536, ge=1, le=65_536),
) -> PersonalLibraryDocumentContentResponse:
    try:
        result = await _get_service().read_owned_text(
            owner_user_id=_owner_id(request),
            document_id=document_id,
            offset=offset,
            limit=limit,
            expected_agent_key=owner_agent_key(request) if request.path_params.get("agentId") else None,
        )
    except PersonalLibraryNotFound as exc:
        raise HTTPException(status_code=404, detail="library_document_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = _document_response(result.document)
    return PersonalLibraryDocumentContentResponse(
        **response.model_dump(),
        content=result.content,
        offset=result.offset,
        next_offset=result.next_offset,
        truncated=result.truncated,
    )


@router.api_route("/documents/{document_id}/download", methods=["GET", "HEAD"], response_class=FileResponse)
async def download_document(
    request: Request,
    document_id: UUID,
) -> FileResponse:
    """按稳定 ID 下载本人原始资料，导航或 Agent 状态不改变所有权。"""
    try:
        document, path, media_type = await _get_service().resolve_owned_download(
            owner_user_id=_owner_id(request),
            document_id=document_id,
            expected_agent_key=owner_agent_key(request) if request.path_params.get("agentId") else None,
        )
    except PersonalLibraryNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="library_document_not_found",
        ) from exc
    return FileResponse(
        path=path,
        filename=document.name,
        media_type=media_type,
    )


def _source_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PersonalLibraryNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PersonalLibraryConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/imports/attachment", response_model=PersonalLibraryDocumentResponse)
async def import_attachment(
    request: Request,
    payload: AttachmentImport,
) -> PersonalLibraryDocumentResponse:
    """将当前 Agent 中当前用户的临时或已保存附件复制到资料库。"""
    owner_user_id = _owner_id(request)
    workspace = await get_agent_for_request(request)
    repository = workspace.chat_manager.conversation_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="attachment_storage_unavailable")
    try:
        document = await _get_service().copy_from_attachment(
            owner_user_id=owner_user_id,
            attachment_id=payload.attachment_id,
            destination_path=payload.destination_path,
            overwrite=payload.overwrite,
            attachment_repository=repository.with_user(owner_user_id),
            agent_key=workspace.agent_id,
        )
    except (PersonalLibraryConflict, PersonalLibraryNotFound, PersonalLibrarySourceDenied) as exc:
        raise _source_error(exc) from exc
    return _document_response(document)


async def _import_runtime_source(
    request: Request,
    payload: RuntimeFileImport,
    *,
    artifact_only: bool,
) -> PersonalLibraryDocumentResponse:
    owner_user_id = _owner_id(request)
    workspace = await get_agent_for_request(request)
    try:
        service = _get_service()
        method = service.copy_from_artifact if artifact_only else service.copy_from_runtime_file
        document = await method(
            owner_user_id=owner_user_id,
            agent_id=workspace.agent_id,
            source_path=payload.source_path,
            destination_path=payload.destination_path,
            overwrite=payload.overwrite,
        )
    except (PersonalLibraryConflict, PersonalLibraryNotFound, PersonalLibrarySourceDenied) as exc:
        raise _source_error(exc) from exc
    return _document_response(document)


@router.post("/imports/runtime-file", response_model=PersonalLibraryDocumentResponse)
async def import_runtime_file(
    request: Request,
    payload: RuntimeFileImport,
) -> PersonalLibraryDocumentResponse:
    return await _import_runtime_source(request, payload, artifact_only=False)


@router.post("/imports/artifact", response_model=PersonalLibraryDocumentResponse)
async def import_artifact(
    request: Request,
    payload: RuntimeFileImport,
) -> PersonalLibraryDocumentResponse:
    return await _import_runtime_source(request, payload, artifact_only=True)
