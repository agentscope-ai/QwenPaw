# -*- coding: utf-8 -*-
"""Convert standard Markdown to Telegram-compatible HTML.

Telegram Bot API supports a subset of HTML tags:
  <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>, <blockquote>

Standard Markdown (as produced by LLMs) uses **bold**, *italic*, `code`,
```code blocks```, [links](url), > blockquotes, etc.

This module bridges the gap.
"""
from __future__ import annotations

import html
import re


def _escape_html(text: str) -> str:
    """Escape the three HTML-significant characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_PLACEHOLDER_RE = re.compile(r"\x00PH(\d+)\x00")


def _split_table_row(line: str) -> list[str]:
    """Split a Markdown table row, honoring escaped pipes."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char == "\\" and index + 1 < len(stripped):
            next_char = stripped[index + 1]
            if next_char == "|":
                current.append("|")
                index += 2
                continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def _parse_table_delimiter(line: str) -> list[str] | None:
    """Return per-column alignment for a Markdown delimiter row."""
    cells = _split_table_row(line)
    if not cells:
        return None
    aligns: list[str] = []
    for cell in cells:
        if not _TABLE_DELIMITER_CELL_RE.fullmatch(cell):
            return None
        left = cell.startswith(":")
        right = cell.endswith(":")
        aligns.append(
            "center" if left and right else "right" if right else "left",
        )
    return aligns


def _mask_inline_table_content(line: str) -> str:
    """Hide inline code and links while checking table structure."""
    line = re.sub(r"`[^`\n]*`", "CODE", line)
    return re.sub(r"\[[^\]]+\]\([^)]+\)", "LINK", line)


def _parse_table_at(
    lines: list[str],
    start: int,
    *,
    mask_inline: bool = False,
) -> tuple[int, list[str], list[str], list[list[str]]] | None:
    """Parse a table beginning at ``start`` and return its end and rows."""
    if start + 1 >= len(lines):
        return None
    header_line = lines[start]
    delimiter_line = lines[start + 1]
    structure_header = (
        _mask_inline_table_content(header_line) if mask_inline else header_line
    )
    structure_delimiter = (
        _mask_inline_table_content(delimiter_line)
        if mask_inline
        else delimiter_line
    )
    if "|" not in structure_header or "|" not in structure_delimiter:
        return None
    header = _split_table_row(structure_header)
    aligns = _parse_table_delimiter(structure_delimiter)
    if aligns is None or len(header) != len(aligns):
        return None

    body: list[list[str]] = []
    index = start + 2
    while index < len(lines):
        line = lines[index]
        structure_line = (
            _mask_inline_table_content(line) if mask_inline else line
        )
        if not structure_line.strip() or "|" not in structure_line:
            break
        structure_cells = _split_table_row(structure_line)
        if len(structure_cells) != len(header):
            break
        if _parse_table_delimiter(structure_line) is not None:
            break
        body.append(_split_table_row(line))
        index += 1
    if not body:
        return None
    return index, header, aligns, body


def has_markdown_table(text: str) -> bool:
    """Return whether text contains a GFM-style table outside code fences."""
    lines = text.split("\n")
    in_fence = False
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if not in_fence:
            table = _parse_table_at(lines, index, mask_inline=True)
            if table is not None:
                return True
        index += 1
    return False


def markdown_table_column_count(text: str) -> int:
    """Return the largest column count of tables outside code fences."""
    lines = text.split("\n")
    in_fence = False
    largest = 0
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("```"):
            in_fence = not in_fence
            index += 1
            continue
        if not in_fence:
            table = _parse_table_at(lines, index, mask_inline=True)
            if table is not None:
                largest = max(largest, len(table[1]))
                index = table[0]
                continue
        index += 1
    return largest


def _flatten_table_cell(cell: str, placeholders: list[str]) -> str:
    """Resolve protected markup and return plain text for a table cell."""

    def _inner(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if not 0 <= index < len(placeholders):
            return match.group(0)
        fragment = re.sub(r"<[^>]*>", "", placeholders[index])
        fragment = html.unescape(fragment)
        return _PLACEHOLDER_RE.sub(_inner, fragment)

    plain = _PLACEHOLDER_RE.sub(_inner, cell)
    return strip_markdown(plain)


def _render_table_block(
    header: list[str],
    body: list[list[str]],
    placeholders: list[str],
) -> str:
    """Render a compact escaped table for the legacy HTML API."""
    rows = [header, *body]
    rendered = [
        " | ".join(_flatten_table_cell(cell, placeholders) for cell in row)
        for row in rows
    ]
    html_block = f"<pre>{_escape_html(chr(10).join(rendered))}</pre>"
    token_index = len(placeholders)
    placeholders.append(html_block)
    return f"\x00PH{token_index}\x00"


def _extract_table_blocks(text: str, placeholders: list[str]) -> str:
    """Replace Markdown table blocks with compact HTML placeholders."""
    lines = text.split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        table = _parse_table_at(lines, index)
        if table is None:
            output.append(lines[index])
            index += 1
            continue
        end, header, _aligns, body = table
        output.append(_render_table_block(header, body, placeholders))
        index = end
    return "\n".join(output)


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown text to Telegram Bot API HTML.

    The function handles:
    - Fenced code blocks (``` ```)
    - Inline code (` `)
    - Links [text](url)
    - Headers (# … ######) → bold
    - Horizontal rules (---, ***, ___) → ———
    - Blockquotes (> …) → <blockquote>
    - Unordered lists (* / - ) → •
    - Spoilers (||text||) → <tg-spoiler>
    - Bold (**text**), Italic (*text*), Bold+Italic (***text***)
    - Strikethrough (~~text~~)
    """
    if not text:
        return text

    placeholders: list[str] = []

    def _ph(html_fragment: str) -> str:
        idx = len(placeholders)
        placeholders.append(html_fragment)
        return f"\x00PH{idx}\x00"

    # ── Phase 1: extract protected regions ──────────────────────────────

    # Fenced code blocks  ```lang\n…\n```
    def _code_block(m: re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = _escape_html(m.group(2))
        if lang:
            return _ph(
                f'<pre><code class="language-{_escape_html(lang)}">'
                f"{code}</code></pre>",
            )
        return _ph(f"<pre>{code}</pre>")

    text = re.sub(
        r"```(\w*)\n?(.*?)```",
        _code_block,
        text,
        flags=re.DOTALL,
    )

    # Inline code `…`
    def _inline_code(m: re.Match) -> str:
        return _ph(f"<code>{_escape_html(m.group(1))}</code>")

    text = re.sub(r"`([^`\n]+)`", _inline_code, text)

    # Links [text](url) — protect URLs from escaping
    def _link(m: re.Match) -> str:
        link_text = _escape_html(m.group(1))
        url = m.group(2)  # URL should not have its & double-escaped
        # Only escape < and > in URL, keep & as-is for query params
        url = url.replace("<", "%3C").replace(">", "%3E")
        return _ph(f'<a href="{url}">{link_text}</a>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)

    # Tables are rendered compactly only for the legacy HTML API fallback.
    text = _extract_table_blocks(text, placeholders)

    # ── Phase 2: escape HTML in remaining text ─────────────────────────
    text = _escape_html(text)

    # ── Phase 3: structural (block-level) elements ─────────────────────

    # Horizontal rules  (*** / --- / ___ on their own line)
    text = re.sub(r"^[\*\-_]{3,}\s*$", "———", text, flags=re.MULTILINE)

    # Headers  # … ###### → <b>text</b>
    text = re.sub(
        r"^#{1,6}\s+(.+?)$",
        r"<b>\1</b>",
        text,
        flags=re.MULTILINE,
    )

    # Blockquotes: consecutive lines starting with ">"
    # After _escape_html, the ">" became "&gt;"
    lines = text.split("\n")
    result_lines: list[str] = []
    quote_buf: list[str] = []

    def _flush_quote() -> None:
        if quote_buf:
            inner = "\n".join(quote_buf)
            result_lines.append(f"<blockquote>{inner}</blockquote>")
            quote_buf.clear()

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("&gt; "):
            quote_buf.append(stripped[5:])
        elif stripped == "&gt;":
            quote_buf.append("")
        else:
            _flush_quote()
            result_lines.append(line)
    _flush_quote()
    text = "\n".join(result_lines)

    # Unordered list markers:  * / - at line start → •
    text = re.sub(
        r"^(\s*)[\*\-]\s+",
        r"\1• ",
        text,
        flags=re.MULTILINE,
    )

    # ── Phase 4: inline formatting ─────────────────────────────────────

    # Spoilers  ||text||
    text = re.sub(
        r"\|\|(.+?)\|\|",
        r"<tg-spoiler>\1</tg-spoiler>",
        text,
    )

    # Bold + Italic  ***text***
    text = re.sub(r"\*{3}(.+?)\*{3}", r"<b><i>\1</i></b>", text)

    # Bold  **text**
    text = re.sub(r"\*{2}(.+?)\*{2}", r"<b>\1</b>", text)

    # Bold  __text__  (Markdown alternate)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic  *text*  (not at word boundary to avoid false positives)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)

    # Italic  _text_
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough  ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # ── Phase 5: restore placeholders ──────────────────────────────────
    for idx, content in enumerate(placeholders):
        text = text.replace(f"\x00PH{idx}\x00", content)

    return text


def strip_markdown(text: str) -> str:
    """Strip Markdown formatting, returning clean plain text for fallback.

    Used when both HTML and MarkdownV2 sending fail.
    """
    if not text:
        return text
    # Remove fenced code block markers (keep content)
    text = re.sub(r"```\w*\n?", "", text)
    # Remove inline code backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove header markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Horizontal rules → visual separator
    text = re.sub(r"^[\*\-_]{3,}\s*$", "———", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    # Remove strikethrough markers
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Remove spoiler markers
    text = re.sub(r"\|\|(.+?)\|\|", r"\1", text)
    # Links → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    # Remove blockquote markers
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # Convert unordered list markers
    text = re.sub(r"^(\s*)[\*\-]\s+", r"\1• ", text, flags=re.MULTILINE)
    return text
