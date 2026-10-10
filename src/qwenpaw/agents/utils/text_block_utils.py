# -*- coding: utf-8 -*-
"""Text block sanitization utilities.

A model turn that spends all of its completion tokens on reasoning can
finish with an empty text part.  The provider layer turns that part into
a ``TextBlock(text="")`` and the agent persists it like any other block,
so every later request replays it as ``{"type": "output_text",
"text": ""}``.  Some providers reject that item outright — Volcengine Ark
answers ``400 MissingParameter: input.content.text`` — which makes a
single empty turn poison the whole session.

Dropping the block at persistence time keeps the context free of an item
that carries no information but breaks replay.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _block_attr(block: Any, key: str, default: Any = None) -> Any:
    """Read *key* from a dict block (1.x state) or a Pydantic block."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def is_empty_text_block(block: Any) -> bool:
    """Return ``True`` for a text block carrying an empty string.

    Whitespace-only text is kept: providers reject the empty string, not
    a block that happens to contain a newline, and preserving it avoids
    changing what the model sees in its own history.
    """
    if _block_attr(block, "type") != "text":
        return False
    return _block_attr(block, "text") == ""


def drop_empty_text_blocks(blocks: list) -> list:
    """Return *blocks* without the text blocks that carry no text."""
    kept = [b for b in blocks if not is_empty_text_block(b)]
    if len(kept) != len(blocks):
        logger.debug(
            "Dropped %d empty text block(s) before persisting",
            len(blocks) - len(kept),
        )
    return kept


def sanitize_empty_text_blocks(msgs: list) -> list:
    """Strip empty text blocks from already-persisted messages.

    Sessions written before this guard existed still carry the poisoned
    block on disk, so the same filter runs when a session is loaded.

    Messages left with no content are kept rather than removed: the
    surviving shell still carries the turn's token usage, and a message
    without content parts contributes no item to the provider request.
    """
    for msg in msgs:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        kept = drop_empty_text_blocks(content)
        if len(kept) != len(content):
            msg.content = kept
    return msgs
