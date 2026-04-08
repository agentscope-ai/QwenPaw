# -*- coding: utf-8 -*-
"""Unit tests for DOCX knowledge parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from copaw.agents.knowledge.exceptions import EmptyParsedContentError
from copaw.agents.knowledge.parsers.docx_parser import DocxParser


def _build_docx(path: Path) -> None:
    docx = pytest.importorskip("docx")

    document = docx.Document()
    document.add_paragraph("Docx Parser Title")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "A1"
    table.cell(0, 1).text = "B1"
    table.cell(1, 0).text = "A2"
    table.cell(1, 1).text = "B2"
    document.add_paragraph("Tail paragraph")
    document.save(path)


def test_docx_parser_extracts_text_and_title(tmp_path: Path) -> None:
    source = tmp_path / "sample.docx"
    _build_docx(source)

    parsed = DocxParser().parse(source)

    assert parsed.source_type == "docx"
    assert parsed.title == "Docx Parser Title"
    assert parsed.metadata["paragraph_count"] == 2
    assert parsed.metadata["table_count"] == 1
    assert "A1 | B1" in parsed.raw_text
    assert "A2 | B2" in parsed.raw_text

    assert parsed.raw_text.index("Docx Parser Title") < parsed.raw_text.index(
        "A1 | B1",
    )
    assert parsed.raw_text.index("A1 | B1") < parsed.raw_text.index(
        "Tail paragraph",
    )


def test_docx_parser_raises_for_empty_document(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")

    source = tmp_path / "empty.docx"
    docx.Document().save(source)

    with pytest.raises(EmptyParsedContentError):
        DocxParser().parse(source)
