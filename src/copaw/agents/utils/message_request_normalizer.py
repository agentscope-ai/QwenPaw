# -*- coding: utf-8 -*-
"""Normalization helpers for provider chat payloads.

The persisted session history remains AgentScope ``Msg`` objects. For
provider requests we build a normalized copy before formatting so
request-time repair and multimodal downgrade logic does not mutate the
stored conversation state.
"""

from __future__ import annotations

from copy import deepcopy

from agentscope.message import Msg

from .tool_message_utils import _sanitize_tool_messages

_MEDIA_BLOCK_TYPES = {"image", "audio", "video"}
_MEDIA_PLACEHOLDER = (
    "[Media content removed - model does not support this media type]"
)


def _clone_msg(msg: Msg) -> Msg:
    """Return a deep copy of an AgentScope message."""
    return Msg.from_dict(deepcopy(msg.to_dict()))


def _clone_messages(msgs: list[Msg]) -> list[Msg]:
    """Return deep-copied messages suitable for request-time normalization."""
    return [_clone_msg(msg) for msg in msgs]


def _strip_media_blocks_in_place(msgs: list[Msg]) -> int:
    """Strip media blocks from copied messages only.

    Mirrors the fallback logic in ``CoPawAgent`` but operates on normalized
    copies so the stored memory remains untouched.
    """
    total_stripped = 0

    for msg in msgs:
        if not isinstance(msg.content, list):
            continue

        new_content = []
        stripped_this_message = 0
        for block in msg.content:
            if (
                isinstance(block, dict)
                and block.get("type") in _MEDIA_BLOCK_TYPES
            ):
                total_stripped += 1
                stripped_this_message += 1
                continue

            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and isinstance(block.get("output"), list)
            ):
                original_len = len(block["output"])
                block["output"] = [
                    item
                    for item in block["output"]
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in _MEDIA_BLOCK_TYPES
                    )
                ]
                stripped_count = original_len - len(block["output"])
                total_stripped += stripped_count
                stripped_this_message += stripped_count
                if stripped_count > 0 and not block["output"]:
                    block["output"] = _MEDIA_PLACEHOLDER

            new_content.append(block)

        if not new_content and stripped_this_message > 0:
            new_content.append(
                {"type": "text", "text": _MEDIA_PLACEHOLDER},
            )

        msg.content = new_content

    return total_stripped


def normalize_messages_for_model_request(
    msgs: list[Msg],
    *,
    supports_multimodal: bool,
) -> list[Msg]:
    """Return a normalized copy for provider request formatting."""
    normalized = _clone_messages(msgs)
    normalized = _sanitize_tool_messages(normalized)
    if not supports_multimodal:
        _strip_media_blocks_in_place(normalized)
    return normalized


def normalize_messages_for_openai_compatible(
    msgs: list[Msg],
    *,
    supports_multimodal: bool,
) -> list[Msg]:
    """Backward-compatible alias kept for older OpenAI-specific callers."""
    return normalize_messages_for_model_request(
        msgs,
        supports_multimodal=supports_multimodal,
    )


__all__ = [
    "normalize_messages_for_model_request",
    "normalize_messages_for_openai_compatible",
]
