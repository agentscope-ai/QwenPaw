# -*- coding: utf-8 -*-
"""Helpers for filtering user-facing chat messages."""

from __future__ import annotations

from typing import Any


def _message_type_name(message: Any) -> str:
    """Normalize runtime message type values to lowercase strings."""
    message_type = getattr(message, "type", None)
    return str(getattr(message_type, "value", message_type)).lower()


def filter_runtime_messages(
    messages: list[Any],
    *,
    filter_thinking: bool = False,
) -> list[Any]:
    """Filter runtime messages for user-facing history rendering."""
    if not filter_thinking:
        return messages

    return [
        message for message in messages if _message_type_name(message) != "reasoning"
    ]
