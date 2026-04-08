# -*- coding: utf-8 -*-
"""Markdown parser for knowledge import."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import ParsedDocument


class MarkdownParser:
    """Parser for markdown files."""

    supported_suffixes = (".md", ".markdown")

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8")
        title = _extract_markdown_title(text) or path.stem
        return ParsedDocument(
            title=title,
            source_path=str(path),
            source_type="md",
            raw_text=text,
            metadata={"line_count": len(text.splitlines())},
        )


def _extract_markdown_title(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^#\s+(.+)$", stripped)
        if match:
            return match.group(1).strip()
    return None
