# -*- coding: utf-8 -*-
"""Knowledge import APIs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...agents.knowledge.models import (
    KnowledgeDocumentSummary,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
)
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
    console_channel = await workspace.channel_manager.get_channel("console")
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
