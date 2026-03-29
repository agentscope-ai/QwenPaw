# -*- coding: utf-8 -*-
"""Parser base types and registry helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, cast

from ..exceptions import UnsupportedFileTypeError
from ..models import ParsedDocument


class BaseKnowledgeParser(Protocol):
    """Protocol for knowledge source parsers."""

    supported_suffixes: tuple[str, ...]

    def parse(self, path: Path) -> ParsedDocument:
        """Parse file path into normalized text payload."""


def _all_parsers() -> tuple[BaseKnowledgeParser, ...]:
    from .doc_parser import DocParser
    from .docling_parser import DoclingParser
    from .docx_parser import DocxParser
    from .markdown_parser import MarkdownParser
    from .pdf_parser import PdfParser
    from .pptx_parser import PptxParser
    from .text_parser import TextParser
    from .xlsx_parser import XlsxParser

    parsers = (
        MarkdownParser(),
        TextParser(),
        PdfParser(),
        DocParser(),
        DocxParser(),
        XlsxParser(),
        PptxParser(),
        DoclingParser(),
    )
    return cast(tuple[BaseKnowledgeParser, ...], parsers)


def _resolve_kb_document_loading_engine() -> str:
    value = os.environ.get(
        "COPAW_KB_DOCUMENT_LOADING_ENGINE",
        "DEFAULT",
    ).strip()
    upper = value.upper()
    if upper in {"DEFAULT", "DOCLING"}:
        return upper
    return "DEFAULT"


def resolve_parsers_for_path(path: Path) -> tuple[BaseKnowledgeParser, ...]:
    """Resolve parser candidates by file suffix and engine preference."""
    from .docling_parser import DoclingParser

    suffix = path.suffix.lower()
    matched = [p for p in _all_parsers() if suffix in p.supported_suffixes]
    if not matched:
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {suffix or '<none>'}",
        )

    engine = _resolve_kb_document_loading_engine()
    docling = [p for p in matched if isinstance(p, DoclingParser)]
    specialized = [p for p in matched if not isinstance(p, DoclingParser)]
    if engine != "DOCLING":
        if specialized:
            return cast(tuple[BaseKnowledgeParser, ...], tuple(specialized))
        raise UnsupportedFileTypeError(
            f"Unsupported file type without DOCLING engine: {suffix}",
        )

    ordered = docling + specialized
    return cast(tuple[BaseKnowledgeParser, ...], tuple(ordered))


def resolve_parser_for_path(path: Path) -> BaseKnowledgeParser:
    """Resolve primary parser by file suffix and engine preference."""
    return resolve_parsers_for_path(path)[0]
