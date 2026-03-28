# -*- coding: utf-8 -*-
"""Docling parser for knowledge import."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..exceptions import EmptyParsedContentError, KnowledgeError
from ..models import ParsedDocument


class DoclingParser:
    """Generic document parser backed by Docling."""

    supported_suffixes = (
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".pdf",
        ".docx",
    )

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from docling.document_converter import (
                DocumentConverter,
            )  # lazy import to keep optional dependency
        except ImportError as exc:
            raise KnowledgeError(
                "docling is required for DOCLING knowledge import engine",
            ) from exc

        converter = DocumentConverter()
        result = converter.convert(path)
        markdown = result.document.export_to_markdown()
        raw_text = markdown.strip()
        if not raw_text:
            raise EmptyParsedContentError(
                "Docling extracted no textual content",
            )

        return ParsedDocument(
            title=path.stem,
            source_path=str(path),
            source_type=_map_source_type(path.suffix.lower()),
            raw_text=raw_text,
            metadata={
                "engine": "docling",
                "source_suffix": path.suffix.lower(),
                "line_count": len(raw_text.splitlines()),
            },
        )


def _map_source_type(suffix: str) -> Literal["md", "txt", "pdf", "docx"]:
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".txt", ".text"}:
        return "txt"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "docx"
    return "txt"
