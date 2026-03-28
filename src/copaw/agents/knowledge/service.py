# -*- coding: utf-8 -*-
"""Service layer for knowledge import API orchestration."""

from __future__ import annotations

from pathlib import Path

from .models import (
    FailedKnowledgeImport,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
)
from .repository import KnowledgeRepository


class KnowledgeImportService:
    """Coordinates knowledge import actions."""

    def __init__(self, workspace_dir: Path):
        self.repo = KnowledgeRepository(workspace_dir)
        self.repo.ensure_dirs()

    async def import_uploads(
        self,
        request: KnowledgeImportRequest,
    ) -> KnowledgeImportResponse:
        """Import uploads (skeleton implementation for API scaffolding)."""
        failed = [
            FailedKnowledgeImport(
                upload_id=item.upload_id,
                file_name=item.file_name,
                code="NOT_IMPLEMENTED",
                message=(
                    "Knowledge import pipeline is scaffolded but not "
                    "implemented yet."
                ),
            )
            for item in request.uploads
        ]
        return KnowledgeImportResponse(
            success=len(failed) == 0,
            failed=failed,
        )
