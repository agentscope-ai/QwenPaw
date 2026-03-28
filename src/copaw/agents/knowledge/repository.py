# -*- coding: utf-8 -*-
"""Filesystem helpers for knowledge import workspace layout."""

from __future__ import annotations

from pathlib import Path

from .models import KnowledgeDocumentSummary


class KnowledgeRepository:
    """Manages knowledge workspace directories and document listing."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.knowledge_dir = workspace_dir / "knowledge"
        self.raw_dir = self.knowledge_dir / "raw"
        self.docs_dir = self.knowledge_dir / "docs"
        self.chunks_dir = self.knowledge_dir / "chunks"
        self.state_dir = self.knowledge_dir / "state"

    def ensure_dirs(self) -> None:
        """Create knowledge workspace directories if missing."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def list_documents(self) -> list[KnowledgeDocumentSummary]:
        """List known knowledge docs from markdown files."""
        self.ensure_dirs()
        results: list[KnowledgeDocumentSummary] = []
        for md_file in sorted(self.docs_dir.glob("*.md")):
            stat = md_file.stat()
            doc_id = md_file.stem
            results.append(
                KnowledgeDocumentSummary(
                    doc_id=doc_id,
                    title=doc_id,
                    source_file=md_file.name,
                    source_type=md_file.suffix.lstrip("."),
                    imported_at=str(stat.st_mtime),
                    markdown_path=str(md_file.relative_to(self.workspace_dir)),
                ),
            )
        return results
