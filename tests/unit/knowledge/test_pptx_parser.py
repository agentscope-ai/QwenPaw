# -*- coding: utf-8 -*-
"""Unit tests for PPTX knowledge parser."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from copaw.agents.knowledge.exceptions import (
    EmptyParsedContentError,
    KnowledgeError,
)
from copaw.agents.knowledge.parsers.pptx_parser import PptxParser


def _build_pptx(path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    util = pytest.importorskip("pptx.util")

    presentation = pptx.Presentation()
    slide_1 = presentation.slides.add_slide(presentation.slide_layouts[6])
    title_box = slide_1.shapes.add_textbox(
        util.Inches(0.8),
        util.Inches(0.8),
        util.Inches(8.0),
        util.Inches(1.0),
    )
    title_box.text_frame.text = "PPTX Parser Title"

    table = slide_1.shapes.add_table(
        rows=2,
        cols=2,
        left=util.Inches(0.8),
        top=util.Inches(2.0),
        width=util.Inches(8.0),
        height=util.Inches(1.5),
    ).table
    table.cell(0, 0).text = "A1"
    table.cell(0, 1).text = "B1"
    table.cell(1, 0).text = "A2"
    table.cell(1, 1).text = "B2"

    slide_2 = presentation.slides.add_slide(presentation.slide_layouts[6])
    body_box = slide_2.shapes.add_textbox(
        util.Inches(0.8),
        util.Inches(0.8),
        util.Inches(8.0),
        util.Inches(1.5),
    )
    body_box.text_frame.text = "Second slide body"
    slide_2.notes_slide.notes_text_frame.text = "Speaker note line"

    presentation.save(path)


def test_pptx_parser_extracts_text_tables_and_notes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "deck.pptx"
    _build_pptx(source)

    parsed = PptxParser().parse(source)

    assert parsed.source_type == "pptx"
    assert parsed.title == "PPTX Parser Title"
    assert "<<<SLIDE:1>>>" in parsed.raw_text
    assert "A1 | B1" in parsed.raw_text
    assert "A2 | B2" in parsed.raw_text
    assert "<<<SLIDE:2 NOTES>>>" in parsed.raw_text
    assert "Speaker note line" in parsed.raw_text
    assert parsed.metadata["slide_count"] == 2
    assert parsed.metadata["table_count"] == 1
    assert parsed.metadata["notes_count"] == 1
    assert parsed.metadata["text_block_count"] >= 2


def test_pptx_parser_raises_for_empty_presentation(
    tmp_path: Path,
) -> None:
    pptx = pytest.importorskip("pptx")

    source = tmp_path / "empty.pptx"
    presentation = pptx.Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(source)

    with pytest.raises(EmptyParsedContentError):
        PptxParser().parse(source)


def test_pptx_parser_raises_when_python_pptx_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.pptx"
    source.write_bytes(b"fake-pptx")
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pptx":
            raise ImportError("python-pptx is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(KnowledgeError):
        PptxParser().parse(source)
