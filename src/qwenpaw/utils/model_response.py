# -*- coding: utf-8 -*-
"""Read text out of a chat-model response, defensively.

``agentscope.model.ChatResponse`` extends ``dict`` with
``__getattr__ = dict.__getitem__``, so ``getattr(resp, "text", None)`` raises
``KeyError`` instead of defaulting — and providers differ over whether a reply
is a single response or a stream of chunks. Every call site that reads a model
reply needs the same handling, so it lives here once.
"""
from __future__ import annotations

from typing import Any


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
    """First text fragment from a list-of-blocks ``content``."""
    for item in items:
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
    list-of-text-blocks shape some providers return.
    """
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    text = safe_attr(response, "text")
    if isinstance(text, str) and text:
        return text
    content = safe_attr(response, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _first_text_in_list(content)
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
    if not hasattr(response, "__aiter__"):
        return extract_response_text(response)
    text = ""
    async for chunk in response:
        text = extract_response_text(chunk) or text
    return text
