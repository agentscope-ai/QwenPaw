# -*- coding: utf-8 -*-
"""Downscale oversized images on request copies.

History and memory keep the original bytes; only the copy that is about to be
sent to a provider is rescaled, so the user can still ask for the original
media later. Two properties matter more than shrinking:

* animation is never touched — Pillow would silently keep only the first frame;
* the source format is kept when it can carry transparency, because converting
  a transparent WebP to PNG can grow the payload past the byte limit.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from agentscope.message import Base64Source, DataBlock
from PIL import Image, ImageOps, UnidentifiedImageError

from ...providers.capping_formatter import MAX_INLINE_MEDIA_BYTES

# Longest side accepted by downstream vision endpoints.
MAX_IMAGE_SIDE = 8192
_RESCALABLE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"},
)
_QUALITY_STEPS = (85, 70, 55)
_MAX_REDUCTIONS = 3


def _encode(
    image: Image.Image,
    media_type: str,
    has_alpha: bool,
    quality: int,
) -> bytes:
    """Encode *image* in *media_type*, keeping transparency when present."""
    output = BytesIO()
    if media_type == "image/jpeg":
        image.convert("RGB").save(
            output,
            format="JPEG",
            quality=quality,
            progressive=True,
        )
    elif media_type == "image/webp":
        image.convert("RGBA" if has_alpha else "RGB").save(
            output,
            format="WEBP",
            quality=quality,
            method=4,
        )
    else:
        image.convert("RGBA" if has_alpha else "RGB").save(
            output,
            format="PNG",
            optimize=True,
        )
    return output.getvalue()


def downscale_image_bytes(
    image_bytes: bytes,
    media_type: str,
    *,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
) -> tuple[bytes, str]:
    """Return request-sized bytes for one image.

    Images inside the limits, animated images and anything the encoder cannot
    handle are returned unchanged: this can only improve the odds of a
    successful request, never make the payload worse.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            if getattr(opened, "n_frames", 1) > 1:
                return image_bytes, media_type
            if max(opened.size) <= MAX_IMAGE_SIDE:
                return image_bytes, media_type
            opened.load()
            oriented = ImageOps.exif_transpose(opened) or opened
            has_alpha = (
                "A" in oriented.getbands() or "transparency" in oriented.info
            )
            target = (
                media_type
                if media_type in _RESCALABLE_MEDIA_TYPES
                else "image/png"
            )
            oriented.thumbnail(
                (MAX_IMAGE_SIDE, MAX_IMAGE_SIDE),
                Image.Resampling.LANCZOS,
            )
            candidate = oriented
            for _ in range(_MAX_REDUCTIONS):
                for quality in _QUALITY_STEPS:
                    encoded = _encode(candidate, target, has_alpha, quality)
                    if encoded and len(encoded) <= max_bytes:
                        return encoded, target
                candidate = candidate.resize(
                    (
                        max(1, candidate.width // 2),
                        max(1, candidate.height // 2),
                    ),
                    Image.Resampling.LANCZOS,
                )
    except (
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ):
        return image_bytes, media_type
    return image_bytes, media_type


def _rescale_source(source_data: str, media_type: str) -> str | None:
    """Rescale one base64 payload; ``None`` means "leave it alone"."""
    if not source_data or not media_type.startswith("image/"):
        return None
    try:
        raw = base64.b64decode(source_data, validate=True)
    except (ValueError, TypeError):
        return None
    scaled, _ = downscale_image_bytes(raw, media_type)
    if scaled == raw:
        return None
    return base64.b64encode(scaled).decode("ascii")


def _rescale_block(block: Any) -> int:
    """Rescale one base64 image block in place. Returns 1 when changed."""
    if isinstance(block, dict):
        if block.get("type") not in ("data", "image"):
            return 0
        source = block.get("source")
        if not isinstance(source, dict) or source.get("type") != "base64":
            return 0
        replaced = _rescale_source(
            str(source.get("data") or ""),
            str(source.get("media_type") or ""),
        )
        if replaced is None:
            return 0
        source["data"] = replaced
        return 1

    if isinstance(block, DataBlock):
        source = block.source
        if not isinstance(source, Base64Source):
            return 0
        replaced = _rescale_source(
            str(source.data or ""),
            str(source.media_type or ""),
        )
        if replaced is None:
            return 0
        block.source = Base64Source(
            data=replaced,
            media_type=source.media_type,
        )
        return 1
    return 0


def _rescale_value(value: Any) -> int:
    """Recursively rescale base64 images in messages and tool results."""
    changed = _rescale_block(value)
    if changed:
        return changed

    if isinstance(value, list):
        return sum(_rescale_value(item) for item in value)

    if isinstance(value, dict):
        return sum(
            _rescale_value(value.get(key)) for key in ("content", "output")
        )

    total = 0
    for attribute in ("content", "output"):
        nested = getattr(value, attribute, None)
        if isinstance(nested, list):
            total += _rescale_value(nested)
    return total


def downscale_oversized_images(msgs: Any) -> int:
    """Rescale oversized images on a request copy. Returns the count changed."""
    return _rescale_value(msgs)


__all__ = [
    "MAX_IMAGE_SIDE",
    "downscale_image_bytes",
    "downscale_oversized_images",
]
