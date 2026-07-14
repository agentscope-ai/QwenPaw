# -*- coding: utf-8 -*-
"""Outbound text routing — parse LLM text for image/sticker/voice actions.

When the LLM only emits plain ``TextContent`` (the common case), we still
want to give it the ability to send image / sticker / voice. We do that
by scanning the text for explicit or implicit rich-content markers and
turning each match into an :class:`Action` that the dispatch layer can
route to the right Zalo API method.

Supported markers (extracted in this order):

1. **Magic tokens** — explicit intent, highest priority:
   - ``[IMAGE: url]``
   - ``[STICKER: id]``
   - ``[VOICE: url]``
   - ``[FILE: /absolute/path]``

2. **Markdown image syntax** — ``![alt](https://.../pic.png)``
   (only when the URL ends in a known image extension).

3. **Bare image URLs** — any ``https?://...`` whose path ends in
   ``.png|.jpg|.jpeg|.gif|.webp|.bmp`` (optional query string).

Everything that matches is pulled out of the text and returned as an
ordered list. The remaining text (``leftover``) is sent via
``send_message``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Known image extensions (case-insensitive, optional query string).
_IMAGE_EXT_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|bmp)(?:\?[^\s]*)?$",
    re.IGNORECASE,
)

# Any http(s) URL — used to spot bare image links.
_URL_RE = re.compile(r"https?://[^\s<>()\[\]]+", re.IGNORECASE)

# Markdown image syntax: ![alt](url)
_MD_IMG_RE = re.compile(
    r"!\[[^\]]*\]\((https?://[^)\s]+)\)",
    re.IGNORECASE,
)

# Explicit magic tokens (deliberate intent).
_MAGIC_IMAGE_RE = re.compile(r"\[IMAGE:\s*(https?://[^\]]+)\]", re.IGNORECASE)
_MAGIC_STICKER_RE = re.compile(r"\[STICKER:\s*([^\]]+)\]", re.IGNORECASE)
_MAGIC_VOICE_RE = re.compile(r"\[VOICE:\s*(https?://[^\]]+)\]", re.IGNORECASE)
_MAGIC_FILE_RE = re.compile(r"\[FILE:\s*([^\]]+)\]", re.IGNORECASE)

# Trailing punctuation that may accidentally cling to a URL.
_URL_TRIM_CHARS = ".,;:!?\"')]}"


# ---------------------------------------------------------------------------
# Action dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    """A single rich-content action parsed from a text blob.

    Attributes:
        kind: One of ``"photo"``, ``"sticker"``, ``"voice"``, ``"local_file"``.
        payload: URL (for photo / voice), sticker id, or local file path
            (for local_file).
    """

    kind: str
    payload: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _extract_actions(text: str) -> Tuple[List[Action], str]:
    """Parse *text* for rich-content markers.

    Returns ``(actions, leftover_text)`` — *actions* preserves source
    order, *leftover_text* is the cleaned-up remainder ready to send
    as a plain message (3+ blank lines collapsed, whitespace stripped).
    """
    actions: List[Action] = []
    working = text

    # 1. Magic tokens first (explicit intent).
    for pat, kind in (
        (_MAGIC_IMAGE_RE, "photo"),
        (_MAGIC_STICKER_RE, "sticker"),
        (_MAGIC_VOICE_RE, "voice"),
        (_MAGIC_FILE_RE, "local_file"),
    ):
        for m in pat.finditer(working):
            actions.append(Action(kind=kind, payload=m.group(1)))
        working = pat.sub("", working)

    # 2. Markdown images (only URLs ending in a known image extension).
    for m in _MD_IMG_RE.finditer(working):
        url = m.group(1)
        if _IMAGE_EXT_RE.search(url):
            actions.append(Action(kind="photo", payload=url))
    working = _MD_IMG_RE.sub("", working)

    # 3. Bare image URLs. Strip trailing punctuation that may have stuck
    #    to the URL from the surrounding sentence.
    bare_image_actions: List[Action] = []
    for m in _URL_RE.finditer(working):
        url = m.group(0).rstrip(_URL_TRIM_CHARS)
        if _IMAGE_EXT_RE.search(url):
            bare_image_actions.append(Action(kind="photo", payload=url))
    actions.extend(bare_image_actions)
    for act in bare_image_actions:
        # Only replace once, in case the same URL appears twice.
        working = working.replace(act.payload, "", 1)

    # Collapse multiple blank lines and strip outer whitespace.
    leftover = re.sub(r"\n{3,}", "\n\n", working).strip()
    return actions, leftover
