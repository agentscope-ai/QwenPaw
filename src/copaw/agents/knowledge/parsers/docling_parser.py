# -*- coding: utf-8 -*-
"""Docling parser for knowledge import."""

from __future__ import annotations

from pathlib import Path

from ..exceptions import EmptyParsedContentError, KnowledgeError
from ..models import ParsedDocument


class DoclingParser:
    """Generic document parser backed by Docling."""

    supported_suffixes = (
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".md",
        ".markdown",
        ".adoc",
        ".asciidoc",
        ".tex",
        ".html",
        ".htm",
        ".xhtml",
        ".csv",
        ".txt",
        ".text",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".flac",
        ".mp4",
        ".avi",
        ".mov",
        ".vtt",
        ".xml",
        ".json",
    )

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from docling.document_converter import (
                DocumentConverter,
            )  # lazy import to keep optional dependency
        except ImportError as exc:
            raise KnowledgeError(
                "docling is required for this knowledge import file type. "
                "Install with: pip install 'copaw[docling]'",
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


def _map_source_type(
    suffix: str,
) -> str:
    mapping: dict[str, str] = {
        ".md": "md",
        ".markdown": "md",
        ".txt": "txt",
        ".text": "txt",
        ".pdf": "pdf",
        ".docx": "docx",
        ".xlsx": "xlsx",
        ".pptx": "pptx",
    }
    source_type = mapping.get(suffix)
    if source_type is not None:
        return source_type

    normalized_suffix = suffix.strip().lower()
    if normalized_suffix.startswith(".") and len(normalized_suffix) > 1:
        return normalized_suffix[1:]
    return "txt"
