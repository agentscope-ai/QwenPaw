# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: src/shared/image.py (budget_to_pixels, smart_resize)
#   with resolution constants inlined from src/shared/env.py.
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Resolution-budget math shared by document reading and render review.

This module is the canonical vendored copy shared across Creator worktrees;
keep its content byte-identical when re-vendoring on another branch.
"""

from __future__ import annotations

import logging
import math

# Patch-grid unit of Qwen-VL style models (pixels per token side).
TOKEN_SIZE = 32
DEFAULT_BUDGET = "normal"
IMAGE_BUDGET_TOKENS = {"small": 256, "normal": 1024, "large": 2048}
IMAGE_MIN_PIXELS = min(IMAGE_BUDGET_TOKENS.values()) * TOKEN_SIZE * TOKEN_SIZE

# Render-review (WT4) addition: per-frame video budgets inlined verbatim from
# upstream src/shared/env.py. A pure additive block on top of the canonical
# copy so cross-worktree re-vendoring stays a mechanical union.
VIDEO_BUDGET_TOKENS = {"small": 80, "normal": 256, "large": 1024}
VIDEO_MIN_PIXELS = min(VIDEO_BUDGET_TOKENS.values()) * TOKEN_SIZE * TOKEN_SIZE


def budget_to_pixels(budget: str, tokens_map: dict[str, int]) -> int:
    """Map a resolution preset ('small'/'normal'/'large') to a pixel budget via its token count."""
    tokens = tokens_map.get(budget, tokens_map[DEFAULT_BUDGET])
    return tokens * TOKEN_SIZE * TOKEN_SIZE


def smart_resize(
    height: int,
    width: int,
    min_pixels: int,
    max_pixels: int,
    factor: int = TOKEN_SIZE,
) -> tuple[int, int]:
    """Resize (h, w) into [min_pixels, max_pixels], snapped to a multiple of `factor` (the patch grid).

    Creator modification: the upstream copy rounded to the patch grid after
    scaling, which can overshoot max_pixels by up to one row/column of
    patches. This version floors the over-budget branch (matching the
    canonical qwen_vl_utils smart_resize) so the result never exceeds the
    budget.
    """
    if min_pixels > max_pixels:
        logging.warning(
            "min_pixels (%d) > max_pixels (%d), clamping max_pixels to min_pixels",
            min_pixels,
            max_pixels,
        )
        max_pixels = min_pixels

    height = max(factor, round(height / factor) * factor)
    width = max(factor, round(width / factor) * factor)

    def _floor_into_budget(h: int, w: int) -> tuple[int, int]:
        beta = math.sqrt((h * w) / max_pixels)
        h = max(factor, math.floor(h / beta / factor) * factor)
        w = max(factor, math.floor(w / beta / factor) * factor)
        # Clamping an extreme-aspect short side back up to one patch can
        # re-exceed the budget; shrink the long side to compensate.
        if h * w > max_pixels:
            if h >= w:
                h = max(factor, max_pixels // w // factor * factor)
            else:
                w = max(factor, max_pixels // h // factor * factor)
        return h, w

    if height * width > max_pixels:
        height, width = _floor_into_budget(height, width)
    elif height * width < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        height = math.ceil(height * beta / factor) * factor
        width = math.ceil(width * beta / factor) * factor
        if height * width > max_pixels:
            # min and max budgets can coincide (the small preset); the hard
            # max budget wins over the soft minimum.
            height, width = _floor_into_budget(height, width)
    return height, width
