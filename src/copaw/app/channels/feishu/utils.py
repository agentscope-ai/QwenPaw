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

    # Build column definitions with auto width.
    columns = [
        {
            "name": col_keys[i],
            "display_name": headers[i],
            "width": "auto",
            "horizontal_align": "left",
        }
        for i in range(len(headers))
    ]
    rows = []
    for line in lines[sep_idx + 1 :]:
        cells = split_row(line)
        row: Dict[str, Any] = {}
        for i, key in enumerate(col_keys):
            cell_text = cells[i] if i < len(cells) else ""
            # Strip Markdown bold/italic markers; table cells are plain strings.
            cell_text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", cell_text)
            row[key] = cell_text
        rows.append(row)
    if not rows:
        return None
    return {
        "tag": "table",
        "page_size": max(len(rows), 10),
        "columns": columns,
        "rows": rows,
    }


def _convert_md_headings_to_bold(text: str) -> str:
    """Convert Markdown headings (##, ###, etc.) to bold text."""
    return re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", text, flags=re.MULTILINE)


def build_interactive_content(text: str) -> str:
    """Build an interactive card JSON with mixed markdown + native table."""
    lines = text.split("\n")
    elements: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^\s*\|", line):
            # Collect the full table block
            table_block: List[str] = []
            while i < len(lines) and re.match(r"^\s*\|", lines[i]):
                table_block.append(lines[i])
                i += 1
            table_elem = _parse_md_table(table_block)
            if table_elem:
                elements.append(table_elem)
            else:
                # Fallback: render as plain markdown text
                fallback = _convert_md_headings_to_bold("\n".join(table_block))
                elements.append({"tag": "markdown", "content": fallback})
        else:
            # Collect non-table lines
            text_block: List[str] = []
            while i < len(lines) and not re.match(r"^\s*\|", lines[i]):
                text_block.append(lines[i])
                i += 1
            content = "\n".join(text_block).strip()
            if content:
                # Convert headings to bold for interactive card markdown
                content = _convert_md_headings_to_bold(content)
                elements.append({"tag": "markdown", "content": content})
    if not elements:
        elements = [
            {"tag": "markdown", "content": _convert_md_headings_to_bold(text)},
        ]
    card = {"elements": elements}
    return json.dumps(card, ensure_ascii=False)
