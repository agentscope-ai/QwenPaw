# -*- coding: utf-8 -*-
"""Knowledge import APIs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...agents.knowledge.models import (
    KnowledgeDocumentSummary,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from ...agents.knowledge.search_service import KnowledgeSearchService
from ...agents.knowledge.service import KnowledgeImportService
from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post(
    "/import",
    response_model=KnowledgeImportResponse,
    summary="Import uploaded files into knowledge base",
)
async def import_knowledge_uploads(
    body: KnowledgeImportRequest,
    request: Request,
) -> KnowledgeImportResponse:
    """Import current-message uploads into knowledge workspace."""
    workspace = await get_agent_for_request(request)
    channel_manager = workspace.channel_manager
    console_channel = (
        await channel_manager.get_channel("console")
        if channel_manager is not None
        else None
    )
    media_dir = (
        console_channel.media_dir
        if console_channel is not None
        else workspace.workspace_dir / "media"
    )
    service = KnowledgeImportService(
        workspace.workspace_dir,
        media_dir=media_dir,
    )
    return await service.import_uploads(body)


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentSummary],
    summary="List imported knowledge documents",
)
async def list_knowledge_documents(
    request: Request,
) -> list[KnowledgeDocumentSummary]:
    """List knowledge docs currently stored in workspace."""
    workspace = await get_agent_for_request(request)
    service = KnowledgeImportService(workspace.workspace_dir)
    return service.repo.list_documents()


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="Search imported knowledge chunks",
)
async def search_knowledge(
    body: KnowledgeSearchRequest,
    request: Request,
) -> KnowledgeSearchResponse:
    """Search imported knowledge by query and return ranked chunks."""
    workspace = await get_agent_for_request(request)
    service = KnowledgeSearchService(workspace.workspace_dir)
    hits = service.search(
        body.query,
        max_results=body.max_results,
        min_score=body.min_score,
    )
    return KnowledgeSearchResponse(
        query=body.query,
        total=len(hits),
        hits=[
            KnowledgeSearchHit(
                doc_id=item.doc_id,
                title=item.title,
                source_file=item.source_file,
                source_type=item.source_type,
                imported_at=item.imported_at,
                chunk_id=item.chunk_id,
                chunk_index=item.chunk_index,
                chunk_text=item.chunk_text,
                score=item.score,
            )
            for item in hits
        ],
    )
