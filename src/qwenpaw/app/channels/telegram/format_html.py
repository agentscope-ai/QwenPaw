# -*- coding: utf-8 -*-
"""Convert standard Markdown to Telegram-compatible HTML.

Telegram Bot API supports a subset of HTML tags:
  <b>, <i>, <u>, <s>, <code>, <pre>, <a>, <tg-spoiler>, <blockquote>

Standard Markdown (as produced by LLMs) uses **bold**, *italic*, `code`,
```code blocks```, [links](url), > blockquotes, etc.

This module bridges the gap.
"""
from __future__ import annotations

import re


def _escape_html(text: str) -> str:
    """Escape the three HTML-significant characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Markdown table cell: at least 3 dashes with optional alignment colons.
_TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _split_table_row(line: str) -> list[str]:
    """Split a Markdown table row into cells (outer pipes optional)."""
    stripped = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in stripped.split("|")]


def _parse_table_delimiter(line: str) -> list[str] | None:
    """Return per-column alignment if the line is a table delimiter row."""
    cells = _split_table_row(line)
    aligns: list[str] = []
    for cell in cells:
        if not _TABLE_DELIMITER_CELL_RE.match(cell):
            return None
        left = cell.startswith(":")
        right = cell.endswith(":")
        if left and right:
            aligns.append("center")
        elif right:
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def _flatten_table_cell(cell: str, placeholders: list[str]) -> str:
    """Replace code/link placeholder tokens in a cell with plain text.

    Table cells stay plain text so no nested tags (unsafe in Telegram
    ``<pre>``) and no raw tokens ever leak into the rendered block.
    """

    def _inner(m: re.Match) -> str:
        idx = int(m.group(1))
        if 0 <= idx < len(placeholders):
            return re.sub(r"<[^>]*>", "", placeholders[idx])
        return m.group(0)

    return re.sub(r"\x00PH(\d+)\x00", _inner, cell)


def _render_table_block(
    header: list[str],
    aligns: list[str],
    body: list[list[str]],
    placeholders: list[str],
) -> str:
    """Render header/aligns/body rows as a padded ``<pre>`` HTML block."""
    header = [_flatten_table_cell(c, placeholders) for c in header]
    body = [
        [_flatten_table_cell(c, placeholders) for c in row] for row in body
    ]
    widths = [0] * len(header)
    for row in [header, *body]:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _fmt(cell: str, idx: int) -> str:
        align = aligns[idx] if idx < len(aligns) else "left"
        if align == "right":
            return cell.rjust(widths[idx])
        if align == "center":
            return cell.center(widths[idx])
        return cell.ljust(widths[idx])

    rendered = [" | ".join(_fmt(c, i) for i, c in enumerate(header))]
    rendered.append("-+-".join("-" * w for w in widths))
    for row in body:
        rendered.append(" | ".join(_fmt(c, i) for i, c in enumerate(row)))
    html = f"<pre>{_escape_html(chr(10).join(rendered))}</pre>"
    token_idx = len(placeholders)
    placeholders.append(html)
    return f"\x00PH{token_idx}\x00"


def _extract_table_blocks(text: str, placeholders: list[str]) -> str:
    """Replace Markdown table blocks with ``<pre>`` placeholder tokens.

    A table requires a header line containing ``|``, a delimiter line
    containing ``|`` whose cells all match ``:?-{3,}:?``, matching column
    counts, and at least one body row. Spoilers, code blocks, lone pipes
    and malformed delimiters never qualify.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        header_line = lines[i]
        delim_line = lines[i + 1] if i + 1 < len(lines) else ""
        if (
            "|" in header_line
            and "|" in delim_line
            and (aligns := _parse_table_delimiter(delim_line)) is not None
            and len(header := _split_table_row(header_line)) == len(aligns)
        ):
            body_rows: list[list[str]] = []
            j = i + 2
            while j < len(lines):
                body_line = lines[j]
                if body_line.strip() == "" or "|" not in body_line:
                    break
                cells = _split_table_row(body_line)
                if len(cells) != len(header):
                    break
                # A second delimiter-looking row ends the table.
                if _parse_table_delimiter(body_line) is not None:
                    break
                body_rows.append(cells)
                j += 1
            if body_rows:
                out.append(
                    _render_table_block(
                        header,
                        aligns,
                        body_rows,
                        placeholders,
                    ),
                )
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


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
    - Markdown tables → <pre> (monospace block)
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

    # Markdown tables → <pre> (Telegram HTML has no <table>).
    # Runs on raw text (sees "|" and delimiter row), after fenced/inline
    # code and links are placeholder-protected, and before HTML escaping
    # so cell content is still escaped exactly once during rendering.
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
