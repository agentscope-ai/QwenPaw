# -*- coding: utf-8 -*-
"""统一提取个人资料库文档中的可检索文本。"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


TEXT_EXTENSIONS = frozenset(
    {
        "md",
        "markdown",
        "txt",
        "csv",
        "tsv",
        "json",
        "jsonl",
        "yaml",
        "yml",
        "toml",
        "xml",
        "html",
        "htm",
        "log",
        "rst",
        "ini",
    }
)
OPEN_XML_EXTENSIONS = frozenset({"docx", "pptx", "xlsx"})
OPEN_DOCUMENT_EXTENSIONS = frozenset({"odt", "odp", "ods"})
SEARCHABLE_EXTENSIONS = frozenset(
    {*TEXT_EXTENSIONS, *OPEN_XML_EXTENSIONS, *OPEN_DOCUMENT_EXTENSIONS, "pdf"}
)

_MAX_XML_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_EXTRACTED_CHARS = 5_000_000


class DocumentExtractionError(ValueError):
    """文档存在但无法安全提取可检索文本。"""


def extract_searchable_text(path: Path) -> str:
    """按扩展名提取正文，原始资料文件不会被修改。"""
    extension = path.suffix.casefold().lstrip(".")
    if extension not in SEARCHABLE_EXTENSIONS:
        raise DocumentExtractionError("unsupported_library_document_type")
    try:
        if extension in TEXT_EXTENSIONS:
            content = _decode_text(path.read_bytes())
        elif extension == "pdf":
            content = _extract_pdf(path)
        elif extension == "docx":
            content = _extract_docx(path)
        elif extension == "pptx":
            content = _extract_pptx(path)
        elif extension == "xlsx":
            content = _extract_xlsx(path)
        else:
            content = _extract_open_document(path)
    except DocumentExtractionError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, ValueError) as exc:
        raise DocumentExtractionError("invalid_library_document") from exc
    return content[:_MAX_EXTRACTED_CHARS]


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages: list[str] = []
        total = 0
        for index, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            value = f"[第 {index} 页]\n{text}"
            pages.append(value)
            total += len(value)
            if total >= _MAX_EXTRACTED_CHARS:
                break
        return "\n\n".join(pages)
    except Exception as exc:  # pypdf may expose parser-specific exception types
        raise DocumentExtractionError("invalid_pdf_document") from exc


def _archive_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise DocumentExtractionError("missing_document_content") from exc
    if info.file_size > _MAX_XML_MEMBER_BYTES:
        raise DocumentExtractionError("document_content_too_large")
    return archive.read(info)


def _xml_root(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    return ElementTree.fromstring(_archive_member(archive, name))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _node_text(root: ElementTree.Element, tag_name: str = "t") -> str:
    return "".join(
        node.text or "" for node in root.iter() if _local_name(node.tag) == tag_name
    )


def _natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _extract_docx(path: Path) -> str:
    sections: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = ["word/document.xml"]
        names.extend(
            sorted(
                (
                    name
                    for name in archive.namelist()
                    if re.fullmatch(
                        r"word/(?:header|footer)\d+\.xml|word/(?:footnotes|endnotes|comments)\.xml",
                        name,
                    )
                ),
                key=_natural_key,
            )
        )
        for name in names:
            root = _xml_root(archive, name)
            paragraphs = []
            for paragraph in root.iter():
                if _local_name(paragraph.tag) != "p":
                    continue
                text = _node_text(paragraph).strip()
                if text:
                    paragraphs.append(text)
            if paragraphs:
                sections.append("\n".join(paragraphs))
    return "\n\n".join(sections)


def _extract_pptx(path: Path) -> str:
    sections: list[str] = []
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=_natural_key,
        )
        note_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
            ),
            key=_natural_key,
        )
        for index, name in enumerate(slide_names, 1):
            texts = [
                (node.text or "").strip()
                for node in _xml_root(archive, name).iter()
                if _local_name(node.tag) == "t" and (node.text or "").strip()
            ]
            if texts:
                sections.append(f"[第 {index} 页]\n" + "\n".join(texts))
        for index, name in enumerate(note_names, 1):
            text = _node_text(_xml_root(archive, name)).strip()
            if text:
                sections.append(f"[第 {index} 页备注]\n{text}")
    return "\n\n".join(sections)


def _extract_xlsx(path: Path) -> str:
    sections: list[str] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = _xml_root(archive, "xl/sharedStrings.xml")
            for item in root.iter():
                if _local_name(item.tag) == "si":
                    shared_strings.append(_node_text(item))

        sheet_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            ),
            key=_natural_key,
        )
        for sheet_index, name in enumerate(sheet_names, 1):
            rows: list[str] = []
            root = _xml_root(archive, name)
            for row in root.iter():
                if _local_name(row.tag) != "row":
                    continue
                values: list[str] = []
                for cell in row:
                    if _local_name(cell.tag) != "c":
                        continue
                    cell_type = cell.attrib.get("t", "")
                    value_node = next(
                        (child for child in cell if _local_name(child.tag) == "v"),
                        None,
                    )
                    if cell_type == "inlineStr":
                        value = _node_text(cell)
                    elif value_node is None or value_node.text is None:
                        value = ""
                    elif cell_type == "s":
                        try:
                            value = shared_strings[int(value_node.text)]
                        except (ValueError, IndexError):
                            value = value_node.text
                    elif cell_type == "b":
                        value = "TRUE" if value_node.text == "1" else "FALSE"
                    else:
                        value = value_node.text
                    values.append(value.strip())
                if any(values):
                    rows.append("\t".join(values))
            if rows:
                sections.append(f"[工作表 {sheet_index}]\n" + "\n".join(rows))
    return "\n\n".join(sections)


def _extract_open_document(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        root = _xml_root(archive, "content.xml")
    paragraphs: list[str] = []
    for node in root.iter():
        if _local_name(node.tag) not in {"p", "h"}:
            continue
        text = "".join(node.itertext()).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)
