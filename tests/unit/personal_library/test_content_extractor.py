# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from qwenpaw.personal_library.content_extractor import (
    SEARCHABLE_EXTENSIONS,
    extract_searchable_text,
)


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects.append(
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream"
    )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


@pytest.mark.parametrize("suffix", [".md", ".txt", ".csv", ".json", ".yaml"])
def test_extracts_common_text_documents(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"资料{suffix}"
    path.write_text("威盾防水 W8 指标", encoding="utf-8")

    assert extract_searchable_text(path) == "威盾防水 W8 指标"


def test_extracts_text_pdf(tmp_path: Path) -> None:
    path = tmp_path / "指标.pdf"
    path.write_bytes(_pdf_bytes("Waterproof pressure 0.3MPa 120 minutes"))

    content = extract_searchable_text(path)

    assert "0.3MPa" in content
    assert "120 minutes" in content


def test_extracts_presentation_slides_in_order(tmp_path: Path) -> None:
    path = tmp_path / "方案.pptx"
    path.write_bytes(
        _zip_bytes(
            {
                "ppt/slides/slide2.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:t>第二页：施工节点</a:t></p:sld>',
                "ppt/slides/slide1.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:t>第一页：W8系统</a:t><a:t>不透水</a:t></p:sld>',
            }
        )
    )

    content = extract_searchable_text(path)

    assert content.index("第一页：W8系统") < content.index("第二页：施工节点")
    assert "不透水" in content


def test_extracts_spreadsheet_cells(tmp_path: Path) -> None:
    path = tmp_path / "参数.xlsx"
    path.write_bytes(
        _zip_bytes(
            {
                "xl/sharedStrings.xml": (
                    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    "<si><t>不透水性</t></si><si><t>0.3MPa</t></si></sst>"
                ),
                "xl/worksheets/sheet1.xml": (
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
                    '<c r="B1" t="s"><v>1</v></c><c r="C1"><v>120</v></c>'
                    "</row></sheetData></worksheet>"
                ),
            }
        )
    )

    content = extract_searchable_text(path)

    assert "不透水性\t0.3MPa\t120" in content


def test_extracts_open_document_text(tmp_path: Path) -> None:
    path = tmp_path / "规范.odt"
    path.write_bytes(
        _zip_bytes(
            {
                "content.xml": (
                    '<office:document-content xmlns:office="urn:o" xmlns:text="urn:t">'
                    "<text:p>耐候性要求</text:p><text:p>企业标准</text:p>"
                    "</office:document-content>"
                )
            }
        )
    )

    assert "耐候性要求\n企业标准" in extract_searchable_text(path)


def test_declares_all_supported_enterprise_document_extensions() -> None:
    assert {
        "md",
        "txt",
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "odt",
        "odp",
        "ods",
    } <= SEARCHABLE_EXTENSIONS
