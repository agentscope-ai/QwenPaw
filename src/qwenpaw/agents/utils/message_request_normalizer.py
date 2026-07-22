# -*- coding: utf-8 -*-
"""Normalization helpers for provider chat payloads.

The persisted session history remains AgentScope ``Msg`` objects. For
provider requests we build a normalized copy before formatting so
request-time repair and multimodal downgrade logic does not mutate the
stored conversation state.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agentscope.message import Msg, TextBlock

from ...constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from .tool_message_utils import _sanitize_tool_messages

# Block types stripped from copied messages during request-time
# normalization when the target model cannot accept them.  ``file`` is
# included so the OpenAI/Anthropic strip path matches the
# model-rejection fallback in QwenPawAgent.  Note:
# ``model_factory._fixup_media_list`` converts ``file`` blocks to text
# placeholders rather than stripping them — that path preserves
# user-facing history; this one prepares retryable requests.
_MEDIA_BLOCK_TYPES = {"image", "audio", "video", "file"}
_MEDIA_MIME_PREFIXES = ("image/", "audio/", "video/")

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
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if btype not in ("tool_use", "tool_call"):
                continue
            for field in strip_fields:
                if isinstance(block, dict):
                    block.pop(field, None)
                elif hasattr(block, field):
                    try:
                        delattr(block, field)
                    except (AttributeError, ValueError):
                        pass


def _strip_unsigned_thinking_for_anthropic(msgs: list[Msg]) -> None:
    """Drop thinking blocks that lack a non-empty ``signature``.

    Anthropic requires ``thinking.signature`` on every thinking block in the
    request. Blocks carried over from other providers (OpenAI/Qwen reasoning,
    Gemini thoughts, etc.) have no signature and would 400 the request. Native
    Claude thinking blocks always carry one, so they survive untouched.
    """
    for msg in msgs:
        if not isinstance(msg.content, list):
            continue

        def _is_unsigned_thinking(block: Any) -> bool:
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if btype != "thinking":
                return False
            sig = (
                block.get("signature")
                if isinstance(block, dict)
                else getattr(block, "signature", None)
            )
            return not sig

        msg.content = [b for b in msg.content if not _is_unsigned_thinking(b)]


def _clone_msg(msg: Msg) -> Msg:
    """Return a deep copy of an AgentScope message."""
    return Msg.model_validate(deepcopy(msg.model_dump(mode="json")))


def _clone_messages(msgs: list[Msg]) -> list[Msg]:
    """Return deep-copied messages suitable for request-time normalization."""
    return [_clone_msg(msg) for msg in msgs]


def _is_media_block(block: Any) -> bool:
    """Check if a block is a media block (dict or Pydantic DataBlock)."""
    if isinstance(block, dict):
        return block.get("type") in _MEDIA_BLOCK_TYPES
    btype = getattr(block, "type", None)
    if btype in _MEDIA_BLOCK_TYPES:
        return True
    # 2.0 DataBlock: type="data", media type in source.media_type
    if btype == "data":
        source = getattr(block, "source", None)
        mt = getattr(source, "media_type", "") or ""
        return mt.startswith(_MEDIA_MIME_PREFIXES)
    return False


def _strip_media_blocks_in_place(msgs: list[Msg]) -> int:
    """Strip media blocks from copied messages only.

    Handles both 1.x dict blocks and 2.0 Pydantic block objects.
    """
    total_stripped = 0

    for msg in msgs:
        if not isinstance(msg.content, list):
            continue

        new_content = []
        stripped_this_message = 0
        for block in msg.content:
            if _is_media_block(block):
                total_stripped += 1
                stripped_this_message += 1
                continue

            # Handle tool_result with nested media (dict format)
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            output = (
                block.get("output")
                if isinstance(block, dict)
                else getattr(block, "output", None)
            )
            if btype == "tool_result" and isinstance(output, list):
                original_len = len(output)
                filtered = [
                    item for item in output if not _is_media_block(item)
                ]
                stripped_count = original_len - len(filtered)
                total_stripped += stripped_count
                stripped_this_message += stripped_count
                if isinstance(block, dict):
                    block["output"] = (
                        filtered if filtered else MEDIA_UNSUPPORTED_PLACEHOLDER
                    )
                else:
                    block.output = (
                        filtered if filtered else MEDIA_UNSUPPORTED_PLACEHOLDER
                    )

            new_content.append(block)

        if not new_content and stripped_this_message > 0:
            new_content.append(
                TextBlock(type="text", text=MEDIA_UNSUPPORTED_PLACEHOLDER),
            )

        msg.content = new_content

    return total_stripped


def _collapse_consecutive_user_messages(msgs: list[Msg]) -> list[Msg]:
    """Merge runs of consecutive ``user`` messages into a single message.

    Why this exists: virtually every LLM API (Anthropic, OpenAI, DashScope's
    anthropic-compat, ...) requires strict ``user``/``assistant``
    alternation.  CoPaw's state can drift into broken shapes when a prior
    reply failed mid-stream (the user input was already appended to
    ``state.context`` but no assistant message followed); the next user
    message then sits next to the orphan, and the request 400s with
    ``"Request body format invalid"``.

    Strategy: for any run of ``N`` consecutive user messages, concat their
    text-block content into the first one and drop the rest.  Non-text
    blocks (images, etc.) on the later messages are preserved.  We **do
    not** drop information — duplicate "hello" runs become a single
    multi-line "hello\\nhello..." which is ugly but unblocks the chat
    instead of failing it.

    Only ``user`` is collapsed; assistant message runs are rarer and
    usually meaningful (different tool-call rounds), so they're left
    alone — if the API really rejects them, that surfaces a different
    upstream bug worth seeing.
    """
    if not msgs:
        return msgs

    collapsed: list[Msg] = []
    for msg in msgs:
        if collapsed and msg.role == "user" and collapsed[-1].role == "user":
            prev = collapsed[-1]
            prev_content = (
                list(prev.content) if isinstance(prev.content, list) else []
            )
            this_content = (
                list(msg.content) if isinstance(msg.content, list) else []
            )
            prev.content = prev_content + this_content
        else:
            collapsed.append(msg)
    return collapsed


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
    normalized = _collapse_consecutive_user_messages(normalized)
    _clean_provider_specific_fields(normalized, target_family)
    if target_family == "anthropic":
        _strip_unsigned_thinking_for_anthropic(normalized)
    if not supports_multimodal:
        _strip_media_blocks_in_place(normalized)
    return normalized


__all__ = [
    "normalize_messages_for_model_request",
]
