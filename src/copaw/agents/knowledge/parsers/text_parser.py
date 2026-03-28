# -*- coding: utf-8 -*-
"""Text parser for knowledge import."""

from __future__ import annotations

from pathlib import Path

from ..models import ParsedDocument


class TextParser:
    """Parser for plain text files."""

    supported_suffixes = (".txt", ".text")

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8")
        return ParsedDocument(
            title=path.stem,
            source_path=str(path),
            source_type="txt",
            raw_text=text,
            metadata={"line_count": len(text.splitlines())},
        )
