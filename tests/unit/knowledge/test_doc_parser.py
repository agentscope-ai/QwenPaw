# -*- coding: utf-8 -*-
"""Unit tests for DOC parser bridge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from copaw.agents.knowledge.exceptions import KnowledgeError
from copaw.agents.knowledge.models import ParsedDocument
from copaw.agents.knowledge.parsers.doc_parser import DocParser


def test_doc_parser_converts_and_parses_successfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy-binary")

    def _fake_run(command, capture_output, text, check):
        del capture_output, text, check
        out_dir = Path(command[command.index("--outdir") + 1])
        (out_dir / "legacy.docx").write_bytes(b"converted-docx")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_docx_parse(_self, path: Path) -> ParsedDocument:
        return ParsedDocument(
            title="Legacy Title",
            source_path=str(path),
            source_type="docx",
            raw_text="legacy doc content",
            metadata={"paragraph_count": 1},
        )

    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser._resolve_soffice_cmd",
        lambda: "/usr/bin/soffice",
    )
    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser.subprocess.run",
        _fake_run,
    )
    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser.DocxParser.parse",
        _fake_docx_parse,
    )

    parsed = DocParser().parse(source)

    assert parsed.title == "Legacy Title"
    assert parsed.source_type == "doc"
    assert parsed.source_path == str(source)
    assert "legacy doc content" in parsed.raw_text
    assert parsed.metadata["paragraph_count"] == 1
    assert parsed.metadata["converted_via"] == "soffice"
    assert parsed.metadata["converted_from"] == ".doc"


def test_doc_parser_raises_when_soffice_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy-binary")
    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser._resolve_soffice_cmd",
        lambda: None,
    )

    with pytest.raises(KnowledgeError, match="soffice"):
        DocParser().parse(source)


def test_doc_parser_raises_when_conversion_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy-binary")

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="conversion failed",
        )

    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser._resolve_soffice_cmd",
        lambda: "soffice",
    )
    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser.subprocess.run",
        _fake_run,
    )

    with pytest.raises(KnowledgeError, match="conversion failed"):
        DocParser().parse(source)


def test_doc_parser_raises_when_output_docx_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy-binary")

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser._resolve_soffice_cmd",
        lambda: "soffice",
    )
    monkeypatch.setattr(
        "copaw.agents.knowledge.parsers.doc_parser.subprocess.run",
        _fake_run,
    )

    with pytest.raises(KnowledgeError, match="converted DOCX not found"):
        DocParser().parse(source)
