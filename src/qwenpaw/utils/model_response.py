# -*- coding: utf-8 -*-
"""Read text out of a chat-model response, defensively.

``agentscope.model.ChatResponse`` extends ``dict`` with
``__getattr__ = dict.__getitem__``, so ``getattr(resp, "text", None)`` raises
``KeyError`` instead of defaulting — and providers differ over whether a reply
is a single response or a stream of chunks. Every call site that reads a model
reply needs the same handling, so it lives here once.
"""
from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

_REASONING_BLOCK_TYPES = frozenset(
    {
        "analysis",
        "reasoning",
        "reasoning_content",
        "thinking",
    },
)


def safe_attr(obj: Any, name: str) -> Any:
    """``getattr(obj, name, None)`` that also returns ``None`` for dict-like
    objects whose ``__getattr__`` raises ``KeyError`` (e.g. ``ChatResponse``,
    whose ``__getattr__`` is ``dict.__getitem__``)."""
    if isinstance(obj, dict):
        return obj.get(name)
    try:
        return getattr(obj, name, None)
    except (AttributeError, KeyError, TypeError):
        return None


def _first_text_in_list(items: list) -> str:
    """First answer text from block content, excluding reasoning blocks."""
    for item in items:
        block_type = safe_attr(item, "type")
        if (
            isinstance(block_type, str)
            and block_type.lower() in _REASONING_BLOCK_TYPES
        ):
            continue
        got = (
            item.get("text")
            if isinstance(item, dict)
            else safe_attr(item, "text")
        )
        if isinstance(got, str):
            return got
    return ""


def extract_response_text(response: Any) -> str:
    """Pull text out of a ``ChatResponse``-like object or a stream chunk.

    Handles the ``.text`` scalar, a ``.content`` string, and the
    list-of-text-blocks shape some providers return. A non-empty structured
    ``content`` list is authoritative over an aggregate ``.text`` value.
    Explicit reasoning and thinking blocks are never treated as answer text,
    including non-standard compatible-provider blocks that store their
    payload under ``text``.
    """
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    content = safe_attr(response, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        # A non-empty structured response is authoritative. Falling back to
        # an aggregate ``.text`` value when it contains only thinking blocks
        # can re-introduce the reasoning text that was deliberately skipped.
        return _first_text_in_list(content)
    text = safe_attr(response, "text")
    if isinstance(text, str) and text:
        return text
    return ""


async def consume_model_response(
    model: Any,
    messages: list,
    **call_kwargs: Any,
) -> str:
    """Await ``model(messages, **call_kwargs)`` and return its text, streaming
    or not.

    Some providers stream (an ``async_generator`` whose chunks carry the
    cumulative text — the last non-empty wins); others return one response.
    """
    response = await model(messages, **call_kwargs)
    if not isinstance(response, AsyncIterable):
        return extract_response_text(response)
    text = ""
    async for chunk in response:
        text = extract_response_text(chunk) or text
    return text
