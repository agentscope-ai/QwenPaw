# -*- coding: utf-8 -*-
"""WeCom channel utilities."""
from __future__ import annotations

import re
from typing import List


def format_markdown_tables(text: str) -> str:
    """Format GFM markdown tables for WeCom compatibility.

    WeCom requires table columns to be properly aligned.
    This function normalizes table formatting.

    Args:
        text: Input markdown text possibly containing tables.

    Returns:
        Text with formatted tables.
    """
    lines = text.split("\n")
    result: List[str] = []
    i = 0
    in_code_fence = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Track fenced code blocks (```), pass through inside lines unchanged.
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            result.append(line)
            i += 1
            continue
        if in_code_fence:
            result.append(line)
            i += 1
            continue
        # Detect table start (line with |) when not inside a code fence
        if "|" in line:
            # Collect table lines
            table_lines: List[str] = []
            while (
                i < len(lines)
                and "|" in lines[i]
                and not lines[i].strip().startswith("```")
            ):
                table_lines.append(lines[i])
                i += 1
            # Format and add table
            if table_lines:
                result.extend(_format_table(table_lines))
            continue
        result.append(line)
        i += 1
    return "\n".join(result)


def _format_table(lines: List[str]) -> List[str]:
    """Format a single markdown table."""
    if not lines:
        return lines

    # Check if second row is separator (contains only -, :, |, spaces)
    sep_pattern = re.compile(r"^[\s\-:|]+$")
    has_separator = len(lines) >= 2 and sep_pattern.match(lines[1]) is not None

    # Parse cells, skipping the separator row (it will be rebuilt)
    rows: List[List[str]] = []
    for idx, line in enumerate(lines):
        if has_separator and idx == 1:
            continue  # Skip separator row; rebuild it from column widths
        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last cells from leading/trailing |
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        if cells:
            rows.append(cells)

    if not rows:
        return lines

    # Calculate column widths
    col_count = max(len(r) for r in rows)
    widths: List[int] = [0] * col_count
    for row in rows:
        for j in range(col_count):
            cell = row[j] if j < len(row) else ""
            widths[j] = max(widths[j], len(cell))

    # Format rows with proper padding, inserting separator after header
    formatted: List[str] = []
    for idx, row in enumerate(rows):
        padded = [
            (row[j] if j < len(row) else "").ljust(widths[j])
            for j in range(col_count)
        ]
        formatted.append("| " + " | ".join(padded) + " |")
        if idx == 0:
            sep = (
                "| "
                + " | ".join("-" * max(3, widths[j]) for j in range(col_count))
                + " |"
            )
            formatted.append(sep)

    return formatted
