# -*- coding: utf-8 -*-
"""Parser registry for knowledge import supported file types."""

from .base import (
    BaseKnowledgeParser,
    resolve_parser_for_path,
    resolve_parsers_for_path,
)
from .doc_parser import DocParser
from .docling_parser import DoclingParser
from .docx_parser import DocxParser
from .markdown_parser import MarkdownParser
from .pdf_parser import PdfParser
from .text_parser import TextParser

__all__ = [
    "BaseKnowledgeParser",
    "resolve_parser_for_path",
    "resolve_parsers_for_path",
    "DocParser",
    "DoclingParser",
    "DocxParser",
    "MarkdownParser",
    "TextParser",
    "PdfParser",
]
