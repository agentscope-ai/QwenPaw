# -*- coding: utf-8 -*-
"""Pydantic models for knowledge import APIs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeImportItem(BaseModel):
    """A single uploaded file reference from console upload."""

    upload_id: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)


class KnowledgeImportRequest(BaseModel):
    """Request body for importing current-message uploads."""

    uploads: list[KnowledgeImportItem] = Field(default_factory=list)
    mode: Literal["current_message"] = "current_message"


class ImportedKnowledgeDoc(BaseModel):
    """Successfully imported knowledge document metadata."""

    doc_id: str
    file_name: str
    source_type: str
    markdown_path: str
    indexed: bool = True


class SkippedKnowledgeImport(BaseModel):
    """Skipped import item."""

    upload_id: str
    file_name: str
    reason: str
    code: str


class FailedKnowledgeImport(BaseModel):
    """Failed import item."""

    upload_id: str
    file_name: str
    message: str
    code: str


class KnowledgeImportResponse(BaseModel):
    """Response body for import endpoint."""

    success: bool = True
    imported: list[ImportedKnowledgeDoc] = Field(default_factory=list)
    skipped: list[SkippedKnowledgeImport] = Field(default_factory=list)
    failed: list[FailedKnowledgeImport] = Field(default_factory=list)


class KnowledgeDocumentSummary(BaseModel):
    """Minimal document list entry for knowledge docs."""

    doc_id: str
    title: str
    source_file: str
    source_type: str
    imported_at: str
    markdown_path: str


class ParsedDocument(BaseModel):
    """Normalized parser output used by downstream import pipeline."""

    title: str
    source_path: str
    source_type: Literal["md", "txt", "pdf"]
    raw_text: str
    metadata: dict = Field(default_factory=dict)
