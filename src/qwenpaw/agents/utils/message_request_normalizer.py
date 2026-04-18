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

from ...constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from .tool_message_utils import _sanitize_tool_messages

_MEDIA_BLOCK_TYPES = {"image", "audio", "video"}

# Fields that are provider-specific and should not leak across families.
# Gemini: extra_content carries thought_signature.
# AgentScope internal: raw_input is a stream-parsing artefact.
_PROVIDER_ONLY_TOOL_USE_FIELDS = frozenset({"extra_content", "raw_input"})

# The subset that is preserved when the target is its native family.
_GEMINI_NATIVE_FIELDS = frozenset({"extra_content"})


def _clean_provider_specific_fields(
    msgs: list[Msg],
    target_family: str,
) -> None:
    """Remove provider-specific fields that may leak from a previous provider.

    Operates **in-place** on already-cloned messages so the stored
    conversation history is never mutated.

    Current rules
    ~~~~~~~~~~~~~
    * ``extra_content`` – Gemini-specific (``thought_signature``).
      Kept only when *target_family* is ``"gemini"``.
    * ``raw_input`` – AgentScope stream-parsing artefact.
      Stripped unconditionally; some providers reject unknown fields.
    """
    preserve = (
        _GEMINI_NATIVE_FIELDS if target_family == "gemini" else frozenset()
    )
    strip_fields = _PROVIDER_ONLY_TOOL_USE_FIELDS - preserve

    if not strip_fields:
        return

    for msg in msgs:
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            for field in strip_fields:
                block.pop(field, None)


def _clone_msg(msg: Msg) -> Msg:
    """Return a deep copy of an AgentScope message."""
    return Msg.from_dict(deepcopy(msg.to_dict()))


def _clone_messages(msgs: list[Msg]) -> list[Msg]:
    """Return deep-copied messages suitable for request-time normalization."""
    return [_clone_msg(msg) for msg in msgs]


def _strip_media_blocks_in_place(msgs: list[Msg]) -> int:
    """Strip media blocks from copied messages only.

    Mirrors the fallback logic in ``QwenPawAgent`` but operates on normalized
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
                    block["output"] = MEDIA_UNSUPPORTED_PLACEHOLDER

            new_content.append(block)

        if not new_content and stripped_this_message > 0:
            new_content.append(
                {"type": "text", "text": MEDIA_UNSUPPORTED_PLACEHOLDER},
            )

        msg.content = new_content

    return total_stripped


def normalize_messages_for_model_request(
    msgs: list[Msg],
    *,
    supports_multimodal: bool,
    target_family: str = "openai",
) -> list[Msg]:
    """Return a normalized copy for provider request formatting.

    Args:
        msgs: Source messages (will **not** be mutated).
        supports_multimodal: Whether the target model handles media.
        target_family: Provider family of the *current* model
            (``"openai"`` | ``"anthropic"`` | ``"gemini"``).
            Used to strip fields that belong to other providers.
    """
    normalized = _clone_messages(msgs)
    # Sanitize first: _repair_empty_tool_inputs needs raw_input to fix
    # empty input fields.  _clean_provider_specific_fields runs after so
    # that raw_input (and other provider artefacts) are stripped only once
    # the repair has had its chance.
    normalized = _sanitize_tool_messages(normalized)
    _clean_provider_specific_fields(normalized, target_family)
    if not supports_multimodal:
        _strip_media_blocks_in_place(normalized)
    return normalized


__all__ = [
    "normalize_messages_for_model_request",
]
