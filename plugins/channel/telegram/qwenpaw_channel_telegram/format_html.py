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
