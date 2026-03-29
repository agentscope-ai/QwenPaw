# -*- coding: utf-8 -*-
"""Unit tests for parser dispatch strategy."""

from __future__ import annotations

from pathlib import Path

import pytest

from copaw.agents.knowledge.exceptions import UnsupportedFileTypeError
from copaw.agents.knowledge.parsers.base import resolve_parsers_for_path


def _parser_names(path: Path) -> list[str]:
    return [
        parser.__class__.__name__ for parser in resolve_parsers_for_path(path)
    ]


def test_default_engine_uses_specialized_parser_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COPAW_KB_DOCUMENT_LOADING_ENGINE", raising=False)

    assert _parser_names(Path("paper.pdf")) == ["PdfParser"]
    assert _parser_names(Path("notes.docx")) == ["DocxParser"]
    assert _parser_names(Path("legacy.doc")) == ["DocParser"]
    assert _parser_names(Path("sheet.xlsx")) == ["XlsxParser"]
    assert _parser_names(Path("deck.pptx")) == ["PptxParser"]
    assert _parser_names(Path("notes.md")) == ["MarkdownParser"]
    with pytest.raises(UnsupportedFileTypeError):
        resolve_parsers_for_path(Path("webpage.html"))


def test_docling_engine_prioritizes_docling_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COPAW_KB_DOCUMENT_LOADING_ENGINE", "DOCLING")

    assert _parser_names(Path("paper.pdf")) == ["DoclingParser", "PdfParser"]
    assert _parser_names(Path("legacy.doc")) == ["DocParser"]
    assert _parser_names(Path("sheet.xlsx")) == [
        "DoclingParser",
        "XlsxParser",
    ]
    assert _parser_names(Path("deck.pptx")) == [
        "DoclingParser",
        "PptxParser",
    ]
    assert _parser_names(Path("webpage.html")) == ["DoclingParser"]
    assert _parser_names(Path("notes.docx")) == [
        "DoclingParser",
        "DocxParser",
    ]
    assert _parser_names(Path("notes.txt")) == ["DoclingParser", "TextParser"]


def test_invalid_engine_value_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COPAW_KB_DOCUMENT_LOADING_ENGINE", "invalid-value")

    assert _parser_names(Path("paper.pdf")) == ["PdfParser"]
    with pytest.raises(UnsupportedFileTypeError):
        resolve_parsers_for_path(Path("webpage.html"))


def test_unsupported_file_type_raises() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        resolve_parsers_for_path(Path("archive.bin"))
