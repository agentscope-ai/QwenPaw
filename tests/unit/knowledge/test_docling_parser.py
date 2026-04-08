# -*- coding: utf-8 -*-
"""Unit tests for Docling parser."""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest

from copaw.agents.knowledge.exceptions import (
    EmptyParsedContentError,
    KnowledgeError,
)
from copaw.agents.knowledge.parsers.docling_parser import DoclingParser


def test_docling_parser_declares_official_supported_suffixes() -> None:
    parser = DoclingParser()
    expected = {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".md",
        ".adoc",
        ".html",
        ".csv",
        ".png",
        ".mp3",
        ".mp4",
        ".vtt",
        ".xml",
        ".json",
    }
    assert expected.issubset(set(parser.supported_suffixes))


def _install_fake_docling(
    monkeypatch: pytest.MonkeyPatch,
    markdown: str,
) -> None:
    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []  # type: ignore[attr-defined]
    converter_module = types.ModuleType("docling.document_converter")

    class _FakeConverter:
        def convert(self, _path: Path):
            class _FakeDocument:
                def export_to_markdown(self) -> str:
                    return markdown

            class _FakeResult:
                document = _FakeDocument()

            return _FakeResult()

    converter_module.DocumentConverter = (  # type: ignore[attr-defined]
        _FakeConverter
    )
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(
        sys.modules,
        "docling.document_converter",
        converter_module,
    )


def test_docling_parser_extracts_content_with_mocked_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_docling(monkeypatch, "# Parsed Title\n\nBody from docling.")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"fake")

    parsed = DoclingParser().parse(source)

    assert parsed.source_type == "pdf"
    assert parsed.title == "sample"
    assert "Body from docling." in parsed.raw_text
    assert parsed.metadata["engine"] == "docling"


def test_docling_parser_raises_when_docling_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.docx"
    source.write_bytes(b"fake")
    real_import = builtins.__import__

    def _fake_import(
        name,
        globalns=None,
        localns=None,
        fromlist=(),
        level=0,
    ):
        if name == "docling.document_converter":
            raise ImportError("docling is not installed")
        return real_import(name, globalns, localns, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(KnowledgeError):
        DoclingParser().parse(source)


def test_docling_parser_raises_for_empty_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_docling(monkeypatch, "   \n")
    source = tmp_path / "empty.txt"
    source.write_text("placeholder", encoding="utf-8")

    with pytest.raises(EmptyParsedContentError):
        DoclingParser().parse(source)


def test_docling_parser_preserves_non_core_source_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_docling(monkeypatch, "# HTML Doc\n\ncontent")
    source = tmp_path / "index.html"
    source.write_text("<html></html>", encoding="utf-8")

    parsed = DoclingParser().parse(source)

    assert parsed.source_type == "html"
    assert parsed.metadata["source_suffix"] == ".html"
