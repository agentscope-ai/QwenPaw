# -*- coding: utf-8 -*-
"""Text normalization for knowledge import pipeline."""

from __future__ import annotations


def normalize_document_text(raw_text: str) -> str:
    """Normalize parser text into stable markdown-friendly content."""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace(
        "\x00",
        "",
    )
    lines = [line.rstrip() for line in text.split("\n")]

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    normalized_lines: list[str] = []
    blank_streak = 0
    for line in lines:
        if line.strip():
            blank_streak = 0
            normalized_lines.append(line)
            continue

        blank_streak += 1
        # Keep at most one blank line in a row for better chunk stability.
        if blank_streak == 1:
            normalized_lines.append("")

    return "\n".join(normalized_lines).strip()
