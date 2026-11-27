# -*- coding: utf-8 -*-
"""Recognize the channel quote-context prefix convention.

When a user replies to a message in a chat channel (Feishu, QQ, WeChat,
WeCom, DingTalk, OneBot, Yuanbao, ...), the inbound adapter prepends the
quoted (replied-to) message to the user's own text as a
``[quoted <kind>: <content>]`` block — for example
``"[quoted message: quarterly report]\\n/stop"``.

Command classification, queue priority, and slash-command dispatch must
look at the user's own text, so they share this one recognizer instead of
parsing the prefix in every consumer. The quoted content itself is never
modified; it still reaches the model as part of the message.
"""

from __future__ import annotations

import re

# Matches one leading "[quoted ...]" context block, optionally followed
# by whitespace/newlines before the user's own text. "[^]]*" keeps the
# match simple: if the quoted content itself contains "]", the match
# ends early and the remaining text simply no longer starts with the
# prefix, which is the safe outcome for classification.
_QUOTE_CONTEXT_PREFIX_RE = re.compile(r"^\[quoted [^\]]*\]\s*")


def strip_quote_context_prefix(text: str | None) -> str:
    """Remove leading ``[quoted ...]`` context blocks from *text*.

    Some channels prepend more than one block (e.g.
    ``"[quoted media: download failed]"`` in front of
    ``"[quoted message: ...]"``), so stripping repeats until the text no
    longer starts with the prefix.

    Args:
        text: Extracted inbound text, or ``None``.

    Returns:
        The text after any leading quote-context blocks, without leading
        whitespace. A ``None`` input returns ``""``.
    """
    if not text:
        return ""
    stripped = text
    while True:
        match = _QUOTE_CONTEXT_PREFIX_RE.match(stripped)
        if match is None:
            break
        end = match.end()
        stripped = stripped[end:]
    return stripped
