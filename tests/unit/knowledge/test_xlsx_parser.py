# -*- coding: utf-8 -*-
"""Unit tests for XLSX knowledge parser."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from copaw.agents.knowledge.exceptions import (
    EmptyParsedContentError,
    KnowledgeError,
)
from copaw.agents.knowledge.parsers.xlsx_parser import XlsxParser


def _build_xlsx(path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    budget = workbook.active
    budget.title = "Budget"
    budget.append(["Month", "Revenue", "Reviewed"])
    budget.append(["2026-03", 12345.0, True])

    notes = workbook.create_sheet("Notes")
    notes.append(["Key", "Value"])
    notes.append(["Owner", "CoPaw"])

    workbook.save(path)
    workbook.close()


def test_xlsx_parser_extracts_rows_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "report.xlsx"
    _build_xlsx(source)

    parsed = XlsxParser().parse(source)

    assert parsed.source_type == "xlsx"
    assert parsed.title == "report"
    assert "<<<SHEET:Budget ROW:1>>>" in parsed.raw_text
    assert "Month | Revenue | Reviewed" in parsed.raw_text
    assert "2026-03 | 12345 | TRUE" in parsed.raw_text
    assert "<<<SHEET:Notes ROW:2>>>" in parsed.raw_text
    assert parsed.metadata["sheet_count"] == 2
    assert parsed.metadata["row_count"] == 4
    assert parsed.metadata["nonempty_cell_count"] == 10


def test_xlsx_parser_raises_for_empty_workbook(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "empty.xlsx"
    workbook = openpyxl.Workbook()
    workbook.save(source)
    workbook.close()

    with pytest.raises(EmptyParsedContentError):
        XlsxParser().parse(source)


def test_xlsx_parser_raises_when_openpyxl_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.xlsx"
    source.write_bytes(b"fake-xlsx")
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("openpyxl is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(KnowledgeError):
        XlsxParser().parse(source)
