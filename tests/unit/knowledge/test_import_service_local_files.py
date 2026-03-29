# -*- coding: utf-8 -*-
"""Unit tests for local-file import behavior in knowledge service."""

from __future__ import annotations

from pathlib import Path

from copaw.agents.knowledge.service import KnowledgeImportService


async def test_import_local_files_success(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "notes.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Local file import content.", encoding="utf-8")

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source])

    assert response.success is True
    assert response.requested == 1
    assert response.imported_count == 1
    assert response.failed_count == 0
    assert response.skipped_count == 0
    assert response.imported[0].source_type == "txt"


async def test_import_local_files_duplicate_path_in_request(
    tmp_path: Path,
) -> None:
    source = tmp_path / "incoming" / "dup.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("Duplicate path file.", encoding="utf-8")

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source, source])

    assert response.requested == 2
    assert response.imported_count == 1
    assert response.skipped_count == 1
    assert response.failed_count == 0
    assert response.skipped[0].code == "DUPLICATE_LOCAL_FILE_IN_REQUEST"


async def test_import_local_files_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "incoming" / "missing.txt"

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([missing])

    assert response.success is False
    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.failed[0].code == "UPLOAD_NOT_FOUND"


async def test_import_local_files_unsupported_type(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "unsupported.bin"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"\x00\x01\x02")

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source])

    assert response.success is False
    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.failed[0].code == "UNSUPPORTED_FILE_TYPE"


async def test_import_local_files_duplicate_content(tmp_path: Path) -> None:
    source_a = tmp_path / "incoming" / "same_a.txt"
    source_b = tmp_path / "incoming" / "same_b.txt"
    source_a.parent.mkdir(parents=True, exist_ok=True)
    source_a.write_text("same normalized content\n", encoding="utf-8")
    source_b.write_text(
        "\n\nsame normalized content   \r\n",
        encoding="utf-8",
    )

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source_a, source_b])

    assert response.imported_count == 1
    assert response.skipped_count == 1
    assert response.failed_count == 0
    assert response.skipped[0].code == "DUPLICATE_CONTENT"
