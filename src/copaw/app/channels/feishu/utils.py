# -*- coding: utf-8 -*-
"""Feishu channel helpers (session id, sender display, markdown, table)."""

import json
import re
from typing import Any, Dict, List, Optional

from .constants import FEISHU_SESSION_ID_SUFFIX_LEN


def short_session_id_from_full_id(full_id: str) -> str:
    """Use last N chars of full_id (chat_id or open_id) as session_id."""
    n = FEISHU_SESSION_ID_SUFFIX_LEN
    return full_id[-n:] if len(full_id) >= n else full_id


def sender_display_string(
    nickname: Optional[str],
    sender_id: str,
) -> str:
    """Build sender display as nickname#last4(sender_id), like DingTalk."""
    nick = (nickname or "").strip() if isinstance(nickname, str) else ""
    sid = (sender_id or "").strip()
    suffix = sid[-4:] if len(sid) >= 4 else (sid or "????")
    return f"{(nick or 'unknown')}#{suffix}"


def extract_json_key(content: Optional[str], *keys: str) -> Optional[str]:
    """Parse JSON content and return first present key."""
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    for k in keys:
        v = data.get(k) or data.get(k.replace("_", "").lower())
        if v:
            return str(v).strip()
    return None


# Magic bytes mapping for common file formats
_MAGIC_BYTES_MAP = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF8", "gif"),
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),  # Also docx, xlsx, pptx
    (b"ID3", "mp3"),
    (b"\xff\xfb", "mp3"),
    (b"\xff\xfa", "mp3"),
    (b"OggS", "ogg"),
    (b"fLaC", "flac"),
    (b"\x1aE\xdf\xa3", "webm"),
]


def detect_file_ext(data: bytes, default: str = "bin") -> str:
    """Detect file extension from magic bytes."""
    if not data:
        return default
    # Check simple magic bytes
    for magic, ext in _MAGIC_BYTES_MAP:
        if data.startswith(magic):
            return ext
    # Special cases needing offset checks
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "webp"
    if len(data) > 8 and data[4:8] == b"ftyp":
        return "mp4"
    # JPEG: starts with FFD8FF
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return default


def extract_post_text(content: Optional[str]) -> Optional[str]:
    # pylint: disable=too-many-branches
    """Extract plain text from Feishu post message content."""
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    parts: list[str] = []

    # Extract title if present
    title = data.get("title")
    if title and isinstance(title, str) and title.strip():
        parts.append(title.strip())

    # Extract text from content blocks
    content_blocks = data.get("content") or []
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, dict):
                    continue
                tag = item.get("tag")
                # text, code_block, md tags have text field
                if tag in {"text", "code_block", "md"}:
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                # a tag: text + href as markdown link
                elif tag == "a":
                    text = item.get("text", "")
                    href = item.get("href", "")
                    if href:
                        parts.append(f"[{text}]({href})" if text else href)
                    elif text:
                        parts.append(text.strip())
                # at tag uses user_name
                elif tag == "at":
                    user_name = item.get("user_name") or item.get("user_id")
                    if isinstance(user_name, str) and user_name.strip():
                        parts.append(f"@{user_name.strip()}")

    return " ".join(parts) if parts else None


def _extract_post_keys(
    content: Optional[str],
    tag: str,
    key_name: str,
) -> list[str]:
    """Extract key_name values from items matching tag in post content."""
    if not content:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    keys: list[str] = []
    content_blocks = data.get("content") or []
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, list):
                continue
            for item in block:
                if not isinstance(item, dict):
                    continue
                if item.get("tag") == tag:
                    key = item.get(key_name)
                    if isinstance(key, str) and key.strip():
                        keys.append(key.strip())
    return keys


def extract_post_image_keys(content: Optional[str]) -> list[str]:
    """Extract image_key list from Feishu post message content."""
    return _extract_post_keys(content, "img", "image_key")


def extract_post_media_file_keys(content: Optional[str]) -> list[str]:
    """Extract file_key list from ``tag=media`` blocks in post content."""
    return _extract_post_keys(content, "media", "file_key")


def normalize_feishu_md(text: str) -> str:
    """
    Light markdown normalization for Feishu post (avoid broken rendering).
    """
    if not text or not text.strip():
        return text
    # Ensure newline before code fence so Feishu parses it
    text = re.sub(r"([^\n])(```)", r"\1\n\2", text)
    return text


def _parse_md_table(table_lines: List[str]) -> Optional[Dict[str, Any]]:
    """Parse GFM table lines into a Feishu native table component dict."""
    # Filter out empty lines kept in block
    lines = [ln for ln in table_lines if ln.strip()]
    if len(lines) < 2:
        return None
    # Row 0: header, Row 1: separator (---|---), Row 2+: data rows
    sep_idx = None
    for i, ln in enumerate(lines):
        # Separator row: only contains |, -, :, spaces
        if re.match(r"^\s*\|[\s\-\:\|]+\|\s*$", ln):
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return None

    def split_row(line: str) -> List[str]:
        # Strip leading/trailing | and split
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]

    headers = split_row(lines[0])
    if not headers:
        return None
    # Build column keys (safe ASCII slugs)
    col_keys = [f"col{i}" for i in range(len(headers))]

    # Parse alignment from separator line (e.g., |:---|:--:|---:|)
    def parse_alignment(sep_line: str) -> List[str]:
        cells = split_row(sep_line)
        alignments = []
        for cell in cells:
            stripped = cell.strip()
            if stripped.startswith(":") and stripped.endswith(":"):
                alignments.append("center")
            elif stripped.endswith(":"):
                alignments.append("right")
            else:
                alignments.append("left")
        return alignments

    alignments = (
        parse_alignment(lines[sep_idx])
        if sep_idx is not None
        else ["left"] * len(headers)
    )

    # Build column definitions with auto width and parsed alignment.
    columns = [
        {
            "name": col_keys[i],
            "display_name": headers[i],
            "width": "auto",
            "horizontal_align": (
                alignments[i] if i < len(alignments) else "left"
            ),
        }
        for i in range(len(headers))
    ]
    rows = []
    for line in lines[sep_idx + 1 :]:
        cells = split_row(line)
        row: Dict[str, Any] = {}
        for i, key in enumerate(col_keys):
            cell_text = cells[i] if i < len(cells) else ""
            # Strip Markdown emphasis; table cells are plain strings.
            cell_text = re.sub(r"[*_]{1,2}(.+?)[*_]{1,2}", r"\1", cell_text)
            row[key] = cell_text
        rows.append(row)
    if not rows:
        return None
    return {
        "tag": "table",
        "page_size": min(max(len(rows), 10), 50),
        "columns": columns,
        "rows": rows,
    }


def _convert_md_headings_to_bold(text: str) -> str:
    """Convert Markdown headings (##, ###, etc.) to bold text."""
    return re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", text, flags=re.MULTILINE)


_MAX_TABLES_PER_CARD = 5


def _build_elements(text: str) -> List[Dict[str, Any]]:
    """Parse text into a list of card elements (table or markdown)."""
    lines = text.split("\n")
    elements: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*\|", line):
            table_block: List[str] = []
            while i < len(lines) and re.match(
                r"^\s*\|",
                lines[i],
            ):
                table_block.append(lines[i])
                i += 1
            table_elem = _parse_md_table(table_block)
            if table_elem:
                elements.append(table_elem)
            else:
                fallback = _convert_md_headings_to_bold(
                    "\n".join(table_block),
                )
                elements.append(
                    {"tag": "markdown", "content": fallback},
                )
        else:
            text_block: List[str] = []
            while i < len(lines) and not re.match(
                r"^\s*\|",
                lines[i],
            ):
                text_block.append(lines[i])
                i += 1
            content = "\n".join(text_block).strip()
            if content:
                content = _convert_md_headings_to_bold(content)
                elements.append(
                    {"tag": "markdown", "content": content},
                )
    if not elements:
        elements = [
            {
                "tag": "markdown",
                "content": _convert_md_headings_to_bold(text),
            },
        ]
    return elements


def _split_elements(
    elements: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """Split elements into chunks, each with at most _MAX_TABLES_PER_CARD."""
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    # Non-table elements buffered until we know which chunk they belong to.
    pending: List[Dict[str, Any]] = []
    table_count = 0
    for elem in elements:
        if elem.get("tag") == "table":
            if table_count >= _MAX_TABLES_PER_CARD:
                # Flush current chunk; pending text belongs to next chunk.
                chunks.append(current)
                current = list(pending)
                table_count = 0
            else:
                current.extend(pending)
            pending = []
            current.append(elem)
            table_count += 1
        else:
            pending.append(elem)
    # Remaining pending text follows the last table chunk.
    current.extend(pending)
    if current:
        chunks.append(current)
    return chunks


def build_interactive_content(text: str) -> str:
    """Build an interactive card JSON with mixed markdown + native table."""
    elements = _build_elements(text)
    card = {"elements": elements}
    return json.dumps(card, ensure_ascii=False)


def build_interactive_content_chunks(text: str) -> List[str]:
    """Build card JSONs, split when table count exceeds the limit."""
    elements = _build_elements(text)
    chunks = _split_elements(elements)
    return [
        json.dumps({"elements": chunk}, ensure_ascii=False) for chunk in chunks
    ]
