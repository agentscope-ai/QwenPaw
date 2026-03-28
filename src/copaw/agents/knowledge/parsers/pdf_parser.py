# -*- coding: utf-8 -*-
"""PDF parser for knowledge import."""

from __future__ import annotations

from pathlib import Path

from ..exceptions import EmptyParsedContentError, KnowledgeError
from ..models import ParsedDocument


class PdfParser:
    """Parser for text-based PDF files."""

    supported_suffixes = (".pdf",)

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from pypdf import (
                PdfReader,
            )  # lazy import to avoid hard import cost
        except ImportError as exc:
            raise KnowledgeError(
                "pypdf is required for PDF knowledge import support",
            ) from exc

        reader = PdfReader(str(path))
        page_texts: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            content = (page.extract_text() or "").strip()
            page_texts.append(f"<<<PAGE:{index}>>>\n{content}")

        combined = "\n\n".join(page_texts).strip()
        if not combined or all(
            not block.split("\n", 1)[1].strip()
            for block in page_texts
            if "\n" in block
        ):
            raise EmptyParsedContentError(
                "PDF contains no extractable text content",
            )

        return ParsedDocument(
            title=path.stem,
            source_path=str(path),
            source_type="pdf",
            raw_text=combined,
            metadata={"page_count": len(reader.pages)},
        )
