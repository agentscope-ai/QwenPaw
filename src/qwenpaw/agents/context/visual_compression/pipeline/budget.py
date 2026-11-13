# -*- coding: utf-8 -*-
"""Token counting and visual-versus-text request budget policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import (
    CHARS_PER_TEXT_TOKEN_FALLBACK,
    IMAGE_COST_SAFETY_MARGIN,
    IMAGE_PATCH_SIZE,
    MAX_VISUAL_COST_RATIO,
)

if TYPE_CHECKING:
    from ..rendering import RenderedPage


@dataclass(frozen=True)
class RequestBudget:
    """Image envelope; opaque media token cost remains provider-owned."""

    max_total_images: int
    original_images: int
    generated_images: int

    @classmethod
    def from_image_count(
        cls,
        max_total_images: int,
        *,
        images: int,
    ) -> "RequestBudget":
        return cls(
            max_total_images=max_total_images,
            original_images=images,
            generated_images=max(0, max_total_images - images),
        )


def count_text_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Estimate tokens with the provider-independent UTF-8 byte convention."""
    if not text:
        return 0
    return max(
        1,
        int(
            len(text.encode("utf-8")) / max(1.0, float(chars_per_token)) + 0.5,
        ),
    )


def estimate_image_tokens(pages: list["RenderedPage"]) -> int:
    """Estimate provider image tokens from rendered page geometry."""
    return _estimate_image_tokens_from_dimensions(
        [(page.width, page.height) for page in pages],
    )


def _estimate_image_tokens_from_dimensions(
    dimensions: list[tuple[int, int]],
) -> int:
    """Estimate provider image tokens from width/height pairs."""
    patch_sum = sum(
        math.ceil(width / IMAGE_PATCH_SIZE)
        * math.ceil(height / IMAGE_PATCH_SIZE)
        for width, height in dimensions
    )
    return math.ceil(patch_sum * IMAGE_COST_SAFETY_MARGIN)


def estimate_visual_replacement_tokens(
    replacement_text: str,
    pages: list["RenderedPage"],
) -> int:
    """Estimate the native-text plus visual-page replacement cost."""
    return count_text_tokens(
        replacement_text,
        CHARS_PER_TEXT_TOKEN_FALLBACK,
    ) + estimate_image_tokens(pages)


def profitable(
    baseline_text_tokens: int,
    replacement_text: str,
    estimated_pages: list["RenderedPage"],
) -> bool:
    """Price the complete replacement using the renderer's actual layout."""
    replacement_tokens = estimate_visual_replacement_tokens(
        replacement_text,
        estimated_pages,
    )
    return replacement_tokens < baseline_text_tokens * max(
        0.5,
        MAX_VISUAL_COST_RATIO,
    )


__all__ = [
    "RequestBudget",
    "count_text_tokens",
    "estimate_image_tokens",
    "estimate_visual_replacement_tokens",
    "profitable",
]
