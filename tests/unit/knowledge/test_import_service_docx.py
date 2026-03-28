# -*- coding: utf-8 -*-
"""Unit tests for DOCX import behavior in knowledge service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copaw.agents.knowledge.models import (
    KnowledgeImportItem,
    KnowledgeImportRequest,
)
from copaw.agents.knowledge.service import KnowledgeImportService


def _build_docx(path: Path) -> None:
    docx = pytest.importorskip("docx")

    document = docx.Document()
    document.add_paragraph("Knowledge Design")
    document.add_paragraph("DOCX import should be searchable.")
    document.save(path)


async def test_import_docx_upload_success(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    upload_id = "upload_docx.docx"
    _build_docx(media_dir / upload_id)

    service = KnowledgeImportService(tmp_path, media_dir=media_dir)
    request = KnowledgeImportRequest(
        uploads=[
            KnowledgeImportItem(
                upload_id=upload_id,
                file_name="design.docx",
            ),
        ],
    )

    response = await service.import_uploads(request)

    assert response.success is True
    assert response.imported_count == 1
    assert response.failed_count == 0
    imported = response.imported[0]
    assert imported.source_type == "docx"

    index = service.repo.load_index()
    doc_state = index["documents"][imported.doc_id]
    assert doc_state["source_type"] == "docx"

    markdown_path = tmp_path / doc_state["paths"]["markdown"]
    chunks_path = tmp_path / doc_state["paths"]["chunks"]
    assert markdown_path.exists()
    assert chunks_path.exists()

    markdown_body = markdown_path.read_text(encoding="utf-8")
    assert "Knowledge Design" in markdown_body

    chunks_payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    assert chunks_payload["chunk_count"] >= 1
    assert any(
        "DOCX import should be searchable." in chunk["text"]
        for chunk in chunks_payload["chunks"]
    )


async def test_import_doc_upload_is_unsupported(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    upload_id = "legacy.doc"
    (media_dir / upload_id).write_bytes(b"legacy-doc-bytes")

    service = KnowledgeImportService(tmp_path, media_dir=media_dir)
    request = KnowledgeImportRequest(
        uploads=[
            KnowledgeImportItem(
                upload_id=upload_id,
                file_name="legacy.doc",
            ),
        ],
    )

    response = await service.import_uploads(request)

    assert response.success is False
    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.failed[0].code == "UNSUPPORTED_FILE_TYPE"
