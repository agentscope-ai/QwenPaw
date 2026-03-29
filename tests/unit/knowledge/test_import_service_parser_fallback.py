# -*- coding: utf-8 -*-
"""Unit tests for parser fallback behavior in knowledge import service."""

from __future__ import annotations

from pathlib import Path

from copaw.agents.knowledge.exceptions import KnowledgeError
from copaw.agents.knowledge.models import (
    KnowledgeImportItem,
    KnowledgeImportRequest,
    ParsedDocument,
)
from copaw.agents.knowledge.service import KnowledgeImportService


class _FailingParser:
    supported_suffixes = (".txt",)

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, _path: Path) -> ParsedDocument:
        self.calls += 1
        raise KnowledgeError("primary parser failed")


class _SuccessfulParser:
    supported_suffixes = (".txt",)

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, path: Path) -> ParsedDocument:
        self.calls += 1
        return ParsedDocument(
            title="Fallback Success",
            source_path=str(path),
            source_type="txt",
            raw_text="imported content from fallback parser",
            metadata={"engine": "specialized"},
        )


async def test_import_service_falls_back_to_next_parser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    upload_id = "fallback.txt"
    (media_dir / upload_id).write_text("hello", encoding="utf-8")

    failing = _FailingParser()
    successful = _SuccessfulParser()

    monkeypatch.setattr(
        "copaw.agents.knowledge.service.resolve_parsers_for_path",
        lambda _path: (failing, successful),
    )

    service = KnowledgeImportService(tmp_path, media_dir=media_dir)
    request = KnowledgeImportRequest(
        uploads=[
            KnowledgeImportItem(
                upload_id=upload_id,
                file_name="fallback.txt",
            ),
        ],
    )

    response = await service.import_uploads(request)

    assert response.success is True
    assert response.imported_count == 1
    assert response.failed_count == 0
    assert failing.calls == 1
    assert successful.calls == 1
    assert response.imported[0].source_type == "txt"


async def test_import_uploads_maps_knowledge_error_to_parser_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    upload_id = "broken.txt"
    (media_dir / upload_id).write_text("hello", encoding="utf-8")

    failing = _FailingParser()

    monkeypatch.setattr(
        "copaw.agents.knowledge.service.resolve_parsers_for_path",
        lambda _path: (failing,),
    )

    service = KnowledgeImportService(tmp_path, media_dir=media_dir)
    request = KnowledgeImportRequest(
        uploads=[
            KnowledgeImportItem(
                upload_id=upload_id,
                file_name="broken.txt",
            ),
        ],
    )

    response = await service.import_uploads(request)

    assert response.success is False
    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.failed[0].code == "PARSER_ERROR"
    assert response.failed[0].message == "primary parser failed"
    assert failing.calls == 1


async def test_import_local_files_maps_knowledge_error_to_parser_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "incoming" / "broken.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("hello", encoding="utf-8")

    failing = _FailingParser()

    monkeypatch.setattr(
        "copaw.agents.knowledge.service.resolve_parsers_for_path",
        lambda _path: (failing,),
    )

    service = KnowledgeImportService(tmp_path)
    response = await service.import_local_files([source])

    assert response.success is False
    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.failed[0].code == "PARSER_ERROR"
    assert response.failed[0].message == "primary parser failed"
    assert failing.calls == 1
