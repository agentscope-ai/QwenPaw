# -*- coding: utf-8 -*-
"""Unit tests for PPTX local-file import behavior in knowledge service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copaw.agents.knowledge.service import KnowledgeImportService


def _build_pptx(path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    util = pytest.importorskip("pptx.util")

    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    title_box = slide.shapes.add_textbox(
        util.Inches(0.8),
        util.Inches(0.8),
        util.Inches(8.0),
        util.Inches(1.0),
    )
    title_box.text_frame.text = "Roadmap Title"
    body_box = slide.shapes.add_textbox(
        util.Inches(0.8),
        util.Inches(2.0),
        util.Inches(8.0),
        util.Inches(1.2),
    )
    body_box.text_frame.text = "PPTX import should be searchable."
    presentation.save(path)


async def test_import_local_pptx_success(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "roadmap.pptx"
    source.parent.mkdir(parents=True, exist_ok=True)
    _build_pptx(source)

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source])

    assert response.success is True
    assert response.requested == 1
    assert response.imported_count == 1
    assert response.failed_count == 0
    imported = response.imported[0]
    assert imported.source_type == "pptx"

    index = service.repo.load_index()
    doc_state = index["documents"][imported.doc_id]
    assert doc_state["source_type"] == "pptx"

    markdown_path = tmp_path / doc_state["paths"]["markdown"]
    chunks_path = tmp_path / doc_state["paths"]["chunks"]
    assert markdown_path.exists()
    assert chunks_path.exists()

    markdown_body = markdown_path.read_text(encoding="utf-8")
    assert "<<<SLIDE:1>>>" in markdown_body
    assert "Roadmap Title" in markdown_body
    assert "PPTX import should be searchable." in markdown_body

    chunks_payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    assert chunks_payload["chunk_count"] >= 1
    assert any(
        "PPTX import should be searchable." in chunk["text"]
        for chunk in chunks_payload["chunks"]
    )
