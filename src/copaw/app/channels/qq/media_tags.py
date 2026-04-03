# -*- coding: utf-8 -*-
"""Utilities for parsing QQ media tags from outbound text.

This module ports the media-tag splitting behavior from the TypeScript
``media-send.ts`` implementation used by ``openclaw-qqbot``.

The parser recognizes QQ-specific tags such as ``<qqimg>`` and
``<qqvoice>`` as well as the generic ``<img>`` tag. It converts an input
string into an ordered queue of text and media items so the caller can
send plain text and attachments in sequence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MEDIA_TAG_REGEX = re.compile(
    r"<(?P<tag>qqimg|qqvoice|qqvideo|qqfile|qqmedia|img)\b"
    r"(?P<attrs>[^>]*?)"
    r"(?:/>|>(?P<body>.*?)</(?P=tag)\s*>)",
    re.IGNORECASE | re.DOTALL,
)
"""Compiled pattern that matches supported media tags.

Supported tags are ``<qqimg>``, ``<qqvoice>``, ``<qqvideo>``,
``<qqfile>``, ``<qqmedia>``, and ``<img>``. The pattern accepts both
self-closing tags and explicit opening/closing tag pairs.
"""

_ATTR_REGEX = re.compile(
    r"(?P<name>[\w:-]+)\s*=\s*"
    r"(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)

_MEDIA_TYPE_BY_TAG: dict[str, str] = {
    "qqimg": "image",
    "img": "image",
    "qqvoice": "voice",
    "qqvideo": "video",
    "qqfile": "file",
    "qqmedia": "media",
}

_PREFERRED_ATTRS = (
    "src",
    "path",
    "file",
    "url",
    "content",
    "value",
)

_MOJIBAKE_MARKERS = ("Ã", "Â", "Å", "Æ", "Ð", "Ñ", "Ø", "â", "€", "™")


@dataclass(slots=True)
class SendQueueItem:
    """Represents a single outbound send item.

    Attributes:
        type: The logical item kind. ``text`` items contain literal text
            from the original message. Media items map supported QQ tags
            to one of ``image``, ``voice``, ``video``, ``file``, or
            ``media``.
        content: The payload associated with the item. For ``text`` this
            is the text fragment; for media items this is the extracted
            path, URL, or opaque media reference.
    """

    type: Literal["text", "image", "voice", "video", "file", "media"]
    content: str


def fix_path_encoding(path: str) -> str:
    """Normalize common path escaping and mojibake issues.

    The TypeScript implementation this module mirrors has to deal with
    paths embedded in plain text, where callers may send Windows-style
    paths with doubled backslashes or strings that were decoded with the
    wrong character encoding.

    This helper performs three conservative repairs:

    1. Trim surrounding whitespace and matching quotes.
    2. Collapse doubled backslashes while preserving a UNC ``\\\\`` prefix.
    3. Attempt to repair UTF-8 text that was decoded as Latin-1 or
       Windows-1252, but only when the input looks like mojibake.

    Args:
        path: Raw media path or URL extracted from a media tag.

    Returns:
        A normalized string that is safer to pass to downstream QQ media
        send logic.
    """

    normalized = path.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1]:
        if normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1].strip()

    if not normalized:
        return normalized

    unc_prefix = ""
    if normalized.startswith("\\\\"):
        unc_prefix = "\\\\"
        normalized = normalized[2:]

    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")

    normalized = unc_prefix + normalized

    if any(marker in normalized for marker in _MOJIBAKE_MARKERS):
        for source_encoding in ("latin-1", "cp1252"):
            try:
                repaired = normalized.encode(source_encoding).decode("utf-8")
            except UnicodeError:
                continue
            if repaired and repaired != normalized:
                normalized = repaired
                break

    return normalized


def parse_media_tags(text: str) -> list[SendQueueItem]:
    """Split text containing QQ media tags into ordered send items.

    The function walks the input string from left to right, preserving the
    exact order of text fragments and media tags. Each recognized tag is
    converted into a :class:`SendQueueItem`. Text between tags is emitted
    as ``type="text"`` items.

    Supported tag formats include both attribute-based and body-based
    variants, for example::

        <qqimg src="C:\\media\\cat.png" />
        <qqvoice>voice.ogg</qqvoice>
        <img src="https://example.com/pic.jpg" />

    If a supported tag is malformed or does not contain a usable payload,
    the original matched text is preserved as a plain text item instead of
    being discarded.

    Args:
        text: The outbound message text to parse.

    Returns:
        A list of :class:`SendQueueItem` values in send order. The list is
        empty when the input is empty.
    """

    if not text:
        return []

    items: list[SendQueueItem] = []
    last_end = 0

    for match in MEDIA_TAG_REGEX.finditer(text):
        if match.start() > last_end:
            _append_text_item(items, text[last_end : match.start()])

        item = _build_media_item(match)
        if item is None:
            _append_text_item(items, match.group(0))
        else:
            items.append(item)

        last_end = match.end()

    if last_end < len(text):
        _append_text_item(items, text[last_end:])

    return items


def _append_text_item(items: list[SendQueueItem], content: str) -> None:
    """Append a text item when the content is not empty."""

    if content:
        items.append(SendQueueItem(type="text", content=content))


def _build_media_item(match: re.Match[str]) -> SendQueueItem | None:
    """Convert a regex match into a media queue item.

    Args:
        match: A match produced by :data:`MEDIA_TAG_REGEX`.

    Returns:
        A populated media item, or ``None`` when no usable payload can be
        extracted from the tag.
    """

    tag_name = match.group("tag").lower()
    media_type = _MEDIA_TYPE_BY_TAG[tag_name]
    attrs = _parse_attributes(match.group("attrs") or "")
    body = (match.group("body") or "").strip()

    content = _extract_media_content(attrs, body)
    if not content:
        return None

    return SendQueueItem(type=media_type, content=fix_path_encoding(content))


def _parse_attributes(attrs: str) -> dict[str, str]:
    """Parse simple HTML-like attributes from a tag body."""

    parsed: dict[str, str] = {}
    for attr_match in _ATTR_REGEX.finditer(attrs):
        name = attr_match.group("name").lower()
        value = attr_match.group("value").strip()
        parsed[name] = value
    return parsed


def _extract_media_content(attrs: dict[str, str], body: str) -> str:
    """Extract the media payload from tag attributes or inner text."""

    for attr_name in _PREFERRED_ATTRS:
        value = attrs.get(attr_name)
        if value:
            return value

    for value in attrs.values():
        if value:
            return value

    return body


__all__ = ["MEDIA_TAG_REGEX", "SendQueueItem", "fix_path_encoding", "parse_media_tags"]
