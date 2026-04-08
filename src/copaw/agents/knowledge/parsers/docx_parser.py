# -*- coding: utf-8 -*-
"""DOCX parser for knowledge import."""

from __future__ import annotations

from pathlib import Path

from ..exceptions import EmptyParsedContentError, KnowledgeError
from ..models import ParsedDocument

_WORD_MAIN_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TAG_P = f"{{{_WORD_MAIN_NS}}}p"
_TAG_TBL = f"{{{_WORD_MAIN_NS}}}tbl"
_TAG_TR = f"{{{_WORD_MAIN_NS}}}tr"
_TAG_TC = f"{{{_WORD_MAIN_NS}}}tc"
_TAG_T = f"{{{_WORD_MAIN_NS}}}t"


class DocxParser:
    """Parser for DOCX files."""

    supported_suffixes = (".docx",)

    def parse(self, path: Path) -> ParsedDocument:
        try:
            from docx import (
                Document,
            )  # lazy import to avoid hard import cost
        except ImportError as exc:
            raise KnowledgeError(
                "python-docx is required for DOCX knowledge import support",
            ) from exc

        document = Document(str(path))
        blocks: list[str] = []
        title = path.stem
        seen_nonempty_paragraph = False
        paragraph_count = 0
        table_count = 0

        for child in document.element.body.iterchildren():
            if child.tag == _TAG_P:
                paragraph_text = _extract_paragraph_text(child)
                if paragraph_text:
                    if not seen_nonempty_paragraph:
                        title = paragraph_text
                        seen_nonempty_paragraph = True
                    blocks.append(paragraph_text)
                    paragraph_count += 1
                continue

            if child.tag == _TAG_TBL:
                table_lines = _extract_table_lines(child)
                if table_lines:
                    blocks.extend(table_lines)
                    table_count += 1

        raw_text = "\n\n".join(blocks).strip()
        if not raw_text:
            raise EmptyParsedContentError(
                "DOCX contains no extractable text content",
            )

        return ParsedDocument(
            title=title,
            source_path=str(path),
            source_type="docx",
            raw_text=raw_text,
            metadata={
                "paragraph_count": paragraph_count,
                "table_count": table_count,
                "line_count": len(raw_text.splitlines()),
            },
        )


def _extract_paragraph_text(paragraph_element) -> str:
    return "".join(
        (node.text or "") for node in paragraph_element.iter(_TAG_T)
    ).strip()


def _extract_table_lines(table_element) -> list[str]:
    lines: list[str] = []
    for row in table_element.findall(f"./{_TAG_TR}"):
        cells: list[str] = []
        for cell in row.findall(f"./{_TAG_TC}"):
            cell_text = "".join(
                (node.text or "") for node in cell.iter(_TAG_T)
            ).strip()
            cells.append(cell_text)
        if any(cell for cell in cells):
            lines.append(" | ".join(cells).strip())
    return lines
