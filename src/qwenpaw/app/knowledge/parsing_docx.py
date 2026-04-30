# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from fastapi import HTTPException

from .assets import save_asset_bytes


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {
    "w": WORD_NS,
    "a": DRAWING_NS,
    "r": REL_NS,
    "pr": PACKAGE_REL_NS,
}

STRUCTURAL_MARKERS = ("#", ">", "- ", "* ", "+ ", "1. ", "|")


def _normalize_blocks(blocks: list[str]) -> list[str]:
    normalized: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        joined = re.sub(r"\s+", " ", " ".join(line.strip() for line in paragraph_lines if line.strip())).strip()
        if joined:
            normalized.append(joined)
        paragraph_lines.clear()

    for raw_block in blocks:
        stripped = raw_block.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith(STRUCTURAL_MARKERS) or stripped.startswith("```"):
            flush_paragraph()
            normalized.append(stripped)
            continue
        paragraph_lines.extend(line for line in stripped.splitlines() if line.strip())

    flush_paragraph()
    return normalized


def _rels_path_for_part(part_name: str) -> str:
    part = PurePosixPath(part_name)
    return str(part.parent / "_rels" / f"{part.name}.rels")


def _resolve_part_target(part_name: str, target: str) -> str:
    return posixpath.normpath(str(PurePosixPath(part_name).parent / target))


def _load_relationships(archive: zipfile.ZipFile, part_name: str) -> dict[str, str]:
    try:
        rels_root = ElementTree.fromstring(archive.read(_rels_path_for_part(part_name)))
    except KeyError:
        return {}

    mapping: dict[str, str] = {}
    for rel in rels_root.findall("pr:Relationship", NS):
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rel_id or not target or rel.attrib.get("TargetMode") == "External":
            continue
        mapping[rel_id] = _resolve_part_target(part_name, target)
    return mapping


def _image_markdown(
    archive: zipfile.ZipFile,
    rels: dict[str, str],
    node: ElementTree.Element,
    *,
    knowledge_id: str,
    document_id: str,
    asset_cache: dict[str, dict[str, Any]],
) -> str:
    blip = node.find(".//a:blip", NS)
    if blip is None:
        return ""
    rel_id = blip.attrib.get(f"{{{REL_NS}}}embed") or blip.attrib.get(f"{{{REL_NS}}}link")
    if not rel_id:
        return ""
    target = rels.get(rel_id)
    if not target or not target.startswith("word/"):
        return ""

    asset = asset_cache.get(target)
    if asset is None:
        try:
            raw_asset = archive.read(target)
        except KeyError:
            return ""
        asset = save_asset_bytes(knowledge_id, document_id, Path(target).name, raw_asset)
        asset_cache[target] = asset

    alt_text = node.attrib.get("descr") or node.attrib.get("title") or asset["name"]
    return f"![{alt_text}]({asset['url']})"


def _render_node(
    archive: zipfile.ZipFile,
    rels: dict[str, str],
    node: ElementTree.Element,
    *,
    knowledge_id: str,
    document_id: str,
    asset_cache: dict[str, dict[str, Any]],
) -> str:
    tag = node.tag.rsplit("}", 1)[-1]
    if tag == "t":
        return node.text or ""
    if tag == "tab":
        return " "
    if tag in {"br", "cr"}:
        return "\n"
    if tag in {"drawing", "pict"}:
        return _image_markdown(
            archive,
            rels,
            node,
            knowledge_id=knowledge_id,
            document_id=document_id,
            asset_cache=asset_cache,
        )
    return "".join(
        _render_node(
            archive,
            rels,
            child,
            knowledge_id=knowledge_id,
            document_id=document_id,
            asset_cache=asset_cache,
        )
        for child in list(node)
    )


def _render_paragraph(
    archive: zipfile.ZipFile,
    rels: dict[str, str],
    paragraph: ElementTree.Element,
    *,
    knowledge_id: str,
    document_id: str,
    asset_cache: dict[str, dict[str, Any]],
) -> str:
    text = "".join(
        _render_node(
            archive,
            rels,
            child,
            knowledge_id=knowledge_id,
            document_id=document_id,
            asset_cache=asset_cache,
        )
        for child in list(paragraph)
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _render_container(
    archive: zipfile.ZipFile,
    rels: dict[str, str],
    container: ElementTree.Element,
    *,
    knowledge_id: str,
    document_id: str,
    asset_cache: dict[str, dict[str, Any]],
) -> list[str]:
    blocks: list[str] = []
    for child in list(container):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            rendered = _render_paragraph(
                archive,
                rels,
                child,
                knowledge_id=knowledge_id,
                document_id=document_id,
                asset_cache=asset_cache,
            )
            if rendered:
                blocks.append(rendered)
            continue
        if tag != "tbl":
            continue
        for row in child.findall("w:tr", NS):
            rendered_cells: list[str] = []
            for cell in row.findall("w:tc", NS):
                cell_blocks = _render_container(
                    archive,
                    rels,
                    cell,
                    knowledge_id=knowledge_id,
                    document_id=document_id,
                    asset_cache=asset_cache,
                )
                cell_text = " ".join(block for block in cell_blocks if block).strip()
                if cell_text:
                    rendered_cells.append(cell_text)
            if rendered_cells:
                blocks.append(" | ".join(rendered_cells))
    return _normalize_blocks(blocks)


def extract_docx_payload(raw_bytes: bytes, knowledge_id: str, document_id: str) -> dict[str, Any]:
    asset_cache: dict[str, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            try:
                document_root = ElementTree.fromstring(archive.read("word/document.xml"))
            except KeyError as exc:
                raise HTTPException(status_code=400, detail="Invalid DOCX file.") from exc

            body = document_root.find("w:body", NS)
            if body is None:
                raise HTTPException(status_code=400, detail="Invalid DOCX file: no body found.")

            blocks = _render_container(
                archive,
                _load_relationships(archive, "word/document.xml"),
                body,
                knowledge_id=knowledge_id,
                document_id=document_id,
                asset_cache=asset_cache,
            )

            for member in sorted(archive.namelist()):
                if not member.endswith(".xml"):
                    continue
                if not (member.startswith("word/header") or member.startswith("word/footer")):
                    continue
                blocks.extend(
                    _render_container(
                        archive,
                        _load_relationships(archive, member),
                        ElementTree.fromstring(archive.read(member)),
                        knowledge_id=knowledge_id,
                        document_id=document_id,
                        asset_cache=asset_cache,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid DOCX file.") from exc

    return {"content": "\n\n".join(blocks).strip(), "assets": list(asset_cache.values())}