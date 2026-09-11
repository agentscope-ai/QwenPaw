# -*- coding: utf-8 -*-
"""File-native Source Intelligence analyze and read APIs."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import Field

from domain.errors import NotFoundError
from schemas.assets import SourceIndexQueryResult, SourceIntelligenceIndex
from schemas.common import StrictModel
from services.project_files.facade import CreatorFileServices
from services.source_analysis import source_analysis_service
from services.source_analysis.service import document_page_path

from .dependencies import (
    CreatorErrorRoute,
    project_file_services,
)

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["source-intelligence-files"],
    route_class=CreatorErrorRoute,
)


class SourceAnalysisRequest(StrictModel):
    client_request_id: str = Field(alias="clientRequestId")
    source_id: str | None = Field(None, alias="sourceId")
    asset_version_id: str | None = Field(None, alias="assetVersionId")


@router.post(
    "/assets/{asset_id}/analyze",
    status_code=status.HTTP_409_CONFLICT,
    deprecated=True,
)
async def analyze_source_asset(
    project_id: str,
    asset_id: str,
    request: SourceAnalysisRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, object]:
    del project_id, asset_id, request, idempotency_key, services
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Direct inner Source VLM analysis has been removed. "
            "Submit the asset through the Creator Agent so the outer Source "
            "Intelligence VLM can "
            "observe it and call commit_source_intelligence."
        ),
    )


@router.get(
    "/assets/{asset_id}/understanding",
    response_model=SourceIntelligenceIndex,
    response_model_by_alias=True,
)
@router.get(
    "/assets/{asset_id}/understanding/{version_id}",
    response_model=SourceIntelligenceIndex,
    response_model_by_alias=True,
)
async def get_asset_understanding(
    project_id: str,
    asset_id: str,
    version_id: str | None = None,
    services: CreatorFileServices = Depends(project_file_services),
) -> SourceIntelligenceIndex:
    return await asyncio.to_thread(
        source_analysis_service(services).load,
        project_id,
        asset_id,
        version_id,
    )


@router.get(
    "/assets/{asset_id}/source-index/query",
    response_model=SourceIndexQueryResult,
    response_model_by_alias=True,
)
async def query_source_index(
    project_id: str,
    asset_id: str,
    query: str = Query(""),
    services: CreatorFileServices = Depends(project_file_services),
) -> SourceIndexQueryResult:
    return await asyncio.to_thread(
        source_analysis_service(services).query,
        project_id,
        asset_id,
        query,
    )


_DOC_PAGE_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


@router.get("/doc-pages/{checksum}/{page}")
async def document_page_image(
    project_id: str,
    checksum: str,
    page: int,
    services: CreatorFileServices = Depends(project_file_services),
) -> FileResponse:
    """Serve one rendered document page image (doc-page:// evidence ref)."""
    if not _DOC_PAGE_CHECKSUM.fullmatch(checksum) or not 1 <= page <= 9999:
        raise NotFoundError("文档页图引用非法")
    # Assert the Project exists before touching its Runtime directory.
    await asyncio.to_thread(services.projects.read, project_id)
    target = document_page_path(
        services.projects.project_root(project_id),
        checksum,
        page,
    )
    if not target.is_file():
        raise NotFoundError("文档页图不存在")
    return FileResponse(
        target,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


__all__ = ["router"]
