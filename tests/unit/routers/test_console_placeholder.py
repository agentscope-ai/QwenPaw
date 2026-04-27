# -*- coding: utf-8 -*-
"""Unit tests for ``console._extract_placeholder_name``.

The console handler picks an immediate placeholder name for a new chat
from the first content part. Shapes match the agentscope content-block
formats (``{"type": "text", "text": "..."}`` dicts, ``TextBlock``-like
objects with ``.text``, raw strings, and non-text/media blocks). These
tests pin that mapping so a future shape change cannot silently produce
labels like ``{"type": ...`` in the session drawer (regression for PR #3).
"""
from __future__ import annotations

from qwenpaw.app.routers.console import _extract_placeholder_name


class _TextBlock:
    """Stand-in for an agentscope ``TextBlock`` (object with ``.text``)."""

    def __init__(self, text: str) -> None:
        self.text = text


def test_no_content_parts_returns_new_chat() -> None:
    name, first_text = _extract_placeholder_name([])
    assert name == "New Chat"
    assert first_text == ""


def test_string_content_part() -> None:
    name, first_text = _extract_placeholder_name(["Hello, world!"])
    assert name == "Hello, wor"
    assert first_text == "Hello, world!"


def test_dict_text_block() -> None:
    """``{"type": "text", "text": "..."}`` is the agentscope text block.

    Without the dict-aware branch this would fall through to
    ``str(content)`` and produce a placeholder like ``{'type': ...``.
    """
    parts = [{"type": "text", "text": "What's the weather today?"}]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "What's the"
    assert first_text == "What's the weather today?"


def test_dict_without_text_key_is_treated_as_media() -> None:
    """Image/audio dict blocks lack a ``text`` field and should not produce
    JSON-shaped placeholders."""
    parts = [{"type": "image", "image": {"url": "x.png"}}]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "Media Message"
    assert first_text == ""


def test_dict_with_non_string_text_is_treated_as_media() -> None:
    parts = [{"type": "text", "text": 123}]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "Media Message"
    assert first_text == ""


def test_object_with_text_attribute() -> None:
    parts = [_TextBlock("Plan a trip to Tokyo next week")]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "Plan a tri"
    assert first_text == "Plan a trip to Tokyo next week"


def test_object_with_empty_text_attribute_is_media() -> None:
    parts = [_TextBlock("")]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "Media Message"
    assert first_text == ""


def test_unknown_shape_is_treated_as_media() -> None:
    """Unknown blocks must NOT be ``str(...)``-coerced into a placeholder."""
    parts = [object()]
    name, first_text = _extract_placeholder_name(parts)
    assert name == "Media Message"
    assert first_text == ""


def test_falsy_first_part_is_media() -> None:
    name, first_text = _extract_placeholder_name([None])
    assert name == "Media Message"
    assert first_text == ""
