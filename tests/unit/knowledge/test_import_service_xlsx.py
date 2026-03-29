# -*- coding: utf-8 -*-
"""Unit tests for XLSX import behavior in knowledge service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copaw.agents.knowledge.models import (
    KnowledgeImportItem,
    KnowledgeImportRequest,
)
from copaw.agents.knowledge.service import KnowledgeImportService


def _build_xlsx(path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Month", "Region", "Revenue"])
    sheet.append(["2026-03", "East", 12880])
    workbook.save(path)
    workbook.close()


async def test_import_xlsx_upload_success(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    upload_id = "sales.xlsx"
    _build_xlsx(media_dir / upload_id)

    service = KnowledgeImportService(tmp_path, media_dir=media_dir)
    request = KnowledgeImportRequest(
        uploads=[
            KnowledgeImportItem(
                upload_id=upload_id,
                file_name="sales.xlsx",
            ),
        ],
    )

    response = await service.import_uploads(request)

    assert response.success is True
    assert response.imported_count == 1
    assert response.failed_count == 0
    imported = response.imported[0]
    assert imported.source_type == "xlsx"

    index = service.repo.load_index()
    doc_state = index["documents"][imported.doc_id]
    assert doc_state["source_type"] == "xlsx"

    markdown_path = tmp_path / doc_state["paths"]["markdown"]
    chunks_path = tmp_path / doc_state["paths"]["chunks"]
    assert markdown_path.exists()
    assert chunks_path.exists()

    markdown_body = markdown_path.read_text(encoding="utf-8")
    assert "Month | Region | Revenue" in markdown_body
    assert "2026-03 | East | 12880" in markdown_body

    chunks_payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    assert chunks_payload["chunk_count"] >= 1
    assert any(
        "2026-03 | East | 12880" in chunk["text"]
        for chunk in chunks_payload["chunks"]
    )
