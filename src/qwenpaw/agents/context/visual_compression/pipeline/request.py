# -*- coding: utf-8 -*-
"""Provider-independent context planning and request transformation.

The transformer works on deep copies of ``Msg`` objects. Images remain
AgentScope ``DataBlock`` instances until the active formatter builds the wire.
Only host-owned conversation messages are eligible for replacement.
"""

from __future__ import annotations

from agentscope.message import Msg

from ..config import (
    MAX_IMAGES_PER_REQUEST,
    EffortPreset,
)
from .receipt import CompressionReceipt
from .history import compress_history
from .budget import RequestBudget
from .messages import MediaInventory, inspect_media


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
    *,
    context_message_ids: frozenset[str],
    effort_preset: EffortPreset,
) -> tuple[list[Msg], CompressionReceipt]:
    """Apply the provider-independent production compression pipeline."""
    receipt = CompressionReceipt()
    cloned = [
        Msg.model_validate(msg.model_dump(mode="json")) for msg in messages
    ]
    # Native images are correctness-owned by QwenPaw's normal formatter. They
    # are never removed to make room for synthetic pages; an already-oversized
    # request therefore receives no additional visual-compression images.
    media = inspect_media(cloned)
    request_budget = RequestBudget.from_image_count(
        MAX_IMAGES_PER_REQUEST,
        images=media.images,
    )
    cloned, _ = compress_history(
        cloned,
        receipt,
        request_budget.generated_images,
        effort_preset,
        context_message_ids=context_message_ids,
    )
    _validate_media_invariants(cloned, media, request_budget)
    return cloned, receipt


__all__ = ["transform_model_request"]
