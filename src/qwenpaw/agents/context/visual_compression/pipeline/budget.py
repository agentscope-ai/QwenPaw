# -*- coding: utf-8 -*-
"""Token counting and visual-versus-text request budget policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import (
    CANVAS_MAX_HEIGHT,
    CANVAS_PADDING,
    CHARS_PER_TEXT_TOKEN_FALLBACK,
    IMAGE_COST_SAFETY_MARGIN,
    IMAGE_PATCH_SIZE,
    MAX_VISUAL_COST_RATIO,
    EffortPreset,
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
    baseline_text: str,
    rendered_text: str,
    columns: int,
    preset: EffortPreset,
    baseline_text_tokens: int | None = None,
    image_count_cap: int | None = None,
    replacement_text: str = "",
    estimated_pages: list["RenderedPage"] | None = None,
) -> bool:
    """Accept only replacements that reduce estimated request tokens."""
    text_tokens = (
        int(baseline_text_tokens)
        if baseline_text_tokens is not None
        else count_text_tokens(
            baseline_text,
            CHARS_PER_TEXT_TOKEN_FALLBACK,
        )
    )
    if estimated_pages is None:
        cols = max(1, int(columns))
        rows = 0
        for line in rendered_text.split("\n"):
            line_length = len(line)
            rows += 1 if line_length == 0 else math.ceil(line_length / cols)
        hard_rows = max(
            1,
            (CANVAS_MAX_HEIGHT - 2 * CANVAS_PADDING) // preset.line_height,
        )
        readable_rows = max(
            1,
            (preset.readable_chars_per_image + 1) // (cols + 1),
        )
        rows_per_image = min(hard_rows, readable_rows)
        image_count = max(1, math.ceil(rows / rows_per_image))
        if image_count_cap is not None and image_count_cap > 0:
            image_count = min(image_count, int(image_count_cap))
        full_images = max(0, image_count - 1)
        rows_in_last = min(
            rows_per_image,
            max(1, rows - full_images * rows_per_image),
        )
        width = 2 * CANVAS_PADDING + cols * preset.cell_width
        full_height = 2 * CANVAS_PADDING + rows_per_image * preset.line_height
        last_height = 2 * CANVAS_PADDING + rows_in_last * preset.line_height
        dimensions = [
            *((width, full_height) for _ in range(full_images)),
            (width, last_height),
        ]
    else:
        dimensions = [(page.width, page.height) for page in estimated_pages]

    image_tokens = _estimate_image_tokens_from_dimensions(dimensions)
    replacement_tokens = count_text_tokens(
        replacement_text,
        CHARS_PER_TEXT_TOKEN_FALLBACK,
    )
    replacement_tokens += image_tokens
    accepted = replacement_tokens < text_tokens * max(
        0.5,
        MAX_VISUAL_COST_RATIO,
    )
    return accepted


__all__ = [
    "RequestBudget",
    "count_text_tokens",
    "estimate_image_tokens",
    "estimate_visual_replacement_tokens",
    "profitable",
]
