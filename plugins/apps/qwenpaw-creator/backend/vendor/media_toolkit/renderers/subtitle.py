# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path:
#   src/capabilities/core/qwen_media_toolkit_core/renderers/subtitle.py
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Parse subtitle files (SRT, VTT, ASS) into text blocks.

Creator modifications: a minimal ``.ass`` dialogue parser is added and the
leading block is a meta block.
"""

from __future__ import annotations

import os
import re
from typing import Any


def render(path: str, **opts: Any) -> list[dict[str, Any]]:
    """Return subtitle content as text blocks."""
    del opts
    ext = os.path.splitext(path)[1].lower()

    from vendor.media_toolkit.renderers import meta_block

    with open(path, "r", errors="replace", encoding="utf-8") as f:
        text = f.read()

    if ext == ".vtt":
        entries = _parse_vtt(text)
    elif ext == ".ass":
        entries = _parse_ass(text)
    else:
        entries = _parse_srt(text)

    doc_format = ext.lstrip(".") or "srt"
    if not entries:
        return [
            meta_block(doc_format, 1, []),
            {"type": "text", "text": f"Subtitle: {path} (empty)"},
        ]

    lines = [f"Subtitle: {os.path.basename(path)} | {len(entries)} entries"]
    for ts, content in entries:
        lines.append(f"[{ts}] {content}")

    return [
        meta_block(doc_format, 1, []),
        {"type": "text", "text": "\n".join(lines)},
    ]


def _parse_srt(text: str) -> list[tuple[str, str]]:
    blocks = re.split(r"\n\s*\n", text.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        ts_line = None
        content_lines = []
        for line in lines:
            if "-->" in line:
                ts_line = line.strip()
            elif ts_line is not None:
                content_lines.append(line.strip())
        if ts_line and content_lines:
            entries.append((ts_line, " ".join(content_lines)))
    return entries


def _parse_vtt(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    entries = []
    i = 0
    while i < len(lines):
        if "-->" in lines[i]:
            ts = lines[i].strip()
            content_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                content_lines.append(lines[i].strip())
                i += 1
            if content_lines:
                entries.append((ts, " ".join(content_lines)))
        else:
            i += 1
    return entries


def _parse_ass(text: str) -> list[tuple[str, str]]:
    """Creator addition: extract Dialogue events from an ASS/SSA script."""
    entries = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.lower().startswith("dialogue:"):
            continue
        fields = stripped.split(":", 1)[1].split(",", 9)
        if len(fields) < 10:
            continue
        start, end = fields[1].strip(), fields[2].strip()
        content = re.sub(r"\{[^}]*\}", "", fields[9]).replace("\\N", " ")
        content = content.strip()
        if content:
            entries.append((f"{start} --> {end}", content))
    return entries
