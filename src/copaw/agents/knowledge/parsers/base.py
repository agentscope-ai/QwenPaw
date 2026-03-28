# -*- coding: utf-8 -*-
"""Parser base types and registry helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..exceptions import UnsupportedFileTypeError
from ..models import ParsedDocument


class BaseKnowledgeParser(Protocol):
    """Protocol for knowledge source parsers."""

    supported_suffixes: tuple[str, ...]

    def parse(self, path: Path) -> ParsedDocument:
        """Parse file path into normalized text payload."""


def _all_parsers() -> tuple[BaseKnowledgeParser, ...]:
    from .markdown_parser import MarkdownParser
    from .text_parser import TextParser
    from .pdf_parser import PdfParser

    return (MarkdownParser(), TextParser(), PdfParser())


def resolve_parser_for_path(path: Path) -> BaseKnowledgeParser:
    """Resolve parser instance by file suffix."""
    suffix = path.suffix.lower()
    for parser in _all_parsers():
        if suffix in parser.supported_suffixes:
            return parser
    raise UnsupportedFileTypeError(f"Unsupported file type: {suffix or '<none>'}")
