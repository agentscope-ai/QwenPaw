# -*- coding: utf-8 -*-
"""Provider-independent context planning and request transformation.

The transformer works on deep copies of ``Msg`` objects. Images remain
AgentScope ``DataBlock`` instances until the active formatter builds the wire.
Tool documentation follows one provider-independent QwenPaw-native policy.
"""

from __future__ import annotations

import json

from agentscope.message import Msg, TextBlock

from .....constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

from ..config import (
    MAX_IMAGES_PER_REQUEST,
    EffortPreset,
)
from .receipt import CompressionReceipt
from .history import compress_history
from .budget import RequestBudget
from .messages import MediaInventory, inspect_media
from .static_context import compress_static_context, wrap_env_tail
from .tool_results import compress_tool_results


def _is_external_user(message: Msg) -> bool:
    """Whether one canonical message is the live external user request."""
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    return (
        message.role == "user"
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        == EXTERNAL_USER_QUERY_MESSAGE_TAG
    )


def _append_env_tail(messages: list[Msg], env_tail: str) -> None:
    """Append the complete dynamic env block to the real external user."""
    if not env_tail.strip():
        return
    wrapped = wrap_env_tail(env_tail)
    for message in reversed(messages):
        if _is_external_user(message):
            message.content.append(TextBlock(text=wrapped))
            return

    # A very long same-turn tool loop may have pushed the external user into a
    # frozen history chunk. Never drop host context: restore it to native
    # system authority instead of manufacturing a new user message.
    for message in messages:
        if message.role == "system":
            message.content.append(TextBlock(text=env_tail.strip()))
            return


def _validate_media_invariants(
    messages: list[Msg],
    original: MediaInventory,
    budget: RequestBudget,
) -> None:
    """Fail open at middleware level if a transform loses native media."""
    final = inspect_media(messages)
    if (
        final.audio != original.audio
        or final.video != original.video
        or final.files != original.files
        or final.unknown != original.unknown
        or final.images < original.images
    ):
        raise RuntimeError("visual compression changed original media")
    if final.images - original.images > budget.generated_images:
        raise RuntimeError("visual compression exceeded image allowance")


def transform_model_request(
    messages: list[Msg],
    tools: list[dict] | None,
    *,
    effort_preset: EffortPreset,
) -> tuple[list[Msg], list[dict] | None, CompressionReceipt]:
    """Apply the provider-independent production compression pipeline."""
    receipt = CompressionReceipt()
    cloned = [
        Msg.model_validate(msg.model_dump(mode="json")) for msg in messages
    ]
    copied_tools = (
        json.loads(json.dumps(tools, ensure_ascii=False))
        if tools is not None
        else None
    )
    # Native images are correctness-owned by QwenPaw's normal formatter. They
    # are never removed to make room for synthetic pages; an already-oversized
    # request therefore receives no additional visual-compression images.
    media = inspect_media(cloned)
    request_budget = RequestBudget.from_image_count(
        MAX_IMAGES_PER_REQUEST,
        images=media.images,
    )
    pages_left = request_budget.generated_images
    can_relocate_env_tail = any(_is_external_user(msg) for msg in cloned)
    (
        cloned,
        copied_tools,
        pages_left,
        env_tail,
    ) = compress_static_context(
        cloned,
        copied_tools,
        receipt,
        pages_left,
        effort_preset,
        relocate_env_tail=can_relocate_env_tail,
    )
    # Freeze history from untouched canonical tool results first. This makes
    # history the stable cache prefix and prevents an intermediate tool-result
    # image from being serialized as ``[image]`` and discarded.
    history_budget = min(pages_left, MAX_IMAGES_PER_REQUEST)
    cloned, history_pages_left = compress_history(
        cloned,
        receipt,
        history_budget,
        effort_preset,
    )
    pages_left -= history_budget - history_pages_left
    pages_left = compress_tool_results(
        cloned,
        receipt,
        pages_left,
        effort_preset,
    )
    _append_env_tail(cloned, env_tail)
    _validate_media_invariants(cloned, media, request_budget)
    return cloned, copied_tools, receipt


__all__ = ["transform_model_request"]
