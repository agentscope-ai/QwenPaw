# -*- coding: utf-8 -*-
"""Slack mrkdwn formatting, escaping, and text chunking.

Slack uses a superset of Markdown called "mrkdwn". This module handles:
- Escaping unsafe characters while preserving Slack angle-bracket tokens
- Converting generic Markdown to Slack mrkdwn
- Splitting long messages at paragraph boundaries (SLACK_TEXT_LIMIT)
"""

from __future__ import annotations

import re

from .constants import SLACK_TEXT_LIMIT

# ── Slack angle-bracket token patterns ──

_SLACK_ANGLE_TOKEN_RE = re.compile(r"<[^>\n]+>")

# Fenced code block pattern (lazy match to avoid spanning blocks).
_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)

# Inline code pattern.
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# Markdown link: [text](url)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\n]+)\)")

# Markdown formatting markers (apply only outside code blocks).
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_STRIKETHROUGH_RE = re.compile(r"~~(.+?)~~")

# Heading: ## Title
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


# ── Angle-bracket token helpers ──


def _is_slack_angle_token(token: str) -> bool:
    """Return *True* if *token* is a valid Slack angle-bracket token."""
    if not token.startswith("<") or not token.endswith(">"):
        return False
    inner = token[1:-1]
    return bool(
        inner.startswith("@")
        or inner.startswith("#")
        or inner.startswith("!")
        or inner.startswith("mailto:")
        or inner.startswith("tel:")
        or inner.startswith("http://")
        or inner.startswith("https://")
        or inner.startswith("slack://"),
    )


def escape_slack_mrkdwn(text: str) -> str:
    """Escape ``&`` ``<`` ``>``, preserving Slack angle-bracket tokens."""
    if not text:
        return ""
    if "&" not in text and "<" not in text and ">" not in text:
        return text

    def _escape(seg: str) -> str:
        return (
            seg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    parts: list[str] = []
    last = 0
    for m in _SLACK_ANGLE_TOKEN_RE.finditer(text):
        parts.append(_escape(text[last : m.start()]))
        token = m.group(0)
        parts.append(token if _is_slack_angle_token(token) else _escape(token))
        last = m.end()
    parts.append(_escape(text[last:]))
    return "".join(parts)


# ── Markdown → mrkdwn ──


# pylint: disable=too-many-branches,too-many-nested-blocks
def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn.

    Strategy
    --------
    1. Stash fenced code blocks and inline code (protect from escaping).
    2. Escape bare ``&`` ``<`` ``>`` in the remaining text.
    3. Apply formatting conversions (bold, italic, strikethrough, links,
       headings).
    4. Restore stashed code blocks.
    """
    if not text:
        return ""

    stash: dict[str, str] = {}
    _counter = 0

    def _stash(m: re.Match) -> str:
        nonlocal _counter
        key = f"\x00SLACK{_counter}\x00"
        _counter += 1
        stash[key] = m.group(0)
        return key

    # Stash code blocks and inline code.
    work = _CODE_BLOCK_RE.sub(_stash, text)
    work = _INLINE_CODE_RE.sub(_stash, work)

    # Escape bare special characters.
    work = escape_slack_mrkdwn(work)

    # Convert formatting markers.
    work = _ITALIC_RE.sub(r"_\1_", work)
    work = _BOLD_RE.sub(r"*\1*", work)
    work = _STRIKETHROUGH_RE.sub(r"~\1~", work)

    # Convert links: [text](url) → <url|text>
    work = _MD_LINK_RE.sub(_convert_link, work)

    # Convert headings: ## Title → *Title*
    work = _HEADING_RE.sub(r"*\1*", work)

    # Restore stashed code.
    for key, block in stash.items():
        work = work.replace(key, block)

    return work


def _convert_link(m: re.Match) -> str:
    """Convert a Markdown link to Slack mrkdwn ``<url|text>``."""
    text = m.group(1).strip()
    href = m.group(2).strip()
    if text == href:
        return f"<{href}>"
    return f"<{href}|{text}>"


# ── Text chunking ──


def chunk_slack_text(text: str, limit: int = SLACK_TEXT_LIMIT) -> list[str]:
    """Split *text* into chunks each not exceeding *limit* characters.

    Splitting prefers paragraph boundaries (double newline).  Falls back
    to line boundaries and finally hard truncation.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        para = para.rstrip()
        if not para:
            continue

        # Try to append to last chunk as a new paragraph
        if chunks and len(chunks[-1]) + len(para) + 2 <= limit:
            chunks[-1] = chunks[-1] + "\n\n" + para
            continue

        # Try to split paragraph into lines
        lines = para.split("\n")
        current_line_group: list[str] = []
        current_len = 0

        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            if (
                current_len + len(line) + (1 if current_line_group else 0)
                <= limit
            ):
                current_line_group.append(line)
                current_len += len(line) + (1 if current_line_group else 0)
            else:
                # Flush current group
                if current_line_group:
                    chunks.append("\n".join(current_line_group))
                current_line_group = [line]
                current_len = len(line)

                # If single line still exceeds limit, force truncate
                if len(line) > limit:
                    for i in range(0, len(line), limit):
                        chunks.append(line[i : i + limit])
                    current_line_group = []
                    current_len = 0

        if current_line_group:
            chunks.append("\n".join(current_line_group))

    return chunks


# ── thread_ts validation ──

_THREAD_TS_RE = re.compile(r"^\d+\.\d{6}$")


def normalize_slack_thread_ts(value: str | None) -> str | None:
    """Validate and normalise a Slack ``thread_ts``."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    return value if _THREAD_TS_RE.match(value) else None
