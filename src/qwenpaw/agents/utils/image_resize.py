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

from ...providers.capping_formatter import (
    MAX_IMAGE_SIDE,
    MAX_INLINE_MEDIA_BYTES,
)
from ...utils.io_utils import run_sync_io

_RESCALABLE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"},
)
_QUALITY_STEPS = (85, 70, 55)
_MAX_REDUCTIONS = 3


def _encode(
    image: Image.Image,
    media_type: str,
    has_alpha: bool,
    quality: int | None,
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
    max_side: int = MAX_IMAGE_SIDE,
    observed_sides: list[int] | None = None,
) -> tuple[bytes, str]:
    """Return request-sized bytes for one image.

    An image is re-encoded when *either* limit is exceeded — the longest
    side or the byte size — because providers reject on both independently
    and a small-pixel, high-byte PNG never trips the side check alone.

    ``max_side <= 0`` disables the side limit, matching the formatter field
    where 0 disables the cap; the byte limit still applies. Passing zero
    through to Pillow would reach ``thumbnail((0, 0))`` and raise
    ``ZeroDivisionError`` on an otherwise valid image.

    ``observed_sides`` collects the longest side of every image this call
    returns — the size the request will actually carry, not the source
    image's. A caller that has to pick a smaller rendition afterwards starts
    from the dimensions the provider really saw, so each round shrinks below
    the previous one instead of recomputing the same target from a source
    image that never changed.

    Images inside both limits, animated images, and anything the encoder
    cannot handle are returned unchanged: this can only improve the odds of
    a successful request, never make the payload worse.
    """

    def _emit(data: bytes, mtype: str) -> tuple[bytes, str]:
        """Record the longest side of what this request will carry.

        The width is read back from the bytes returned, not from the source
        image. After a resize the caller has to learn the size that was
        actually sent; recording the original dimensions made every later
        tighten recompute the same target from a 2000 px source, so the retry
        carried 1000 px over and over.
        """
        if observed_sides is not None:
            try:
                with Image.open(BytesIO(data)) as out:
                    observed_sides.append(max(out.size))
            except (
                Image.DecompressionBombError,
                OSError,
                UnidentifiedImageError,
                ValueError,
            ):
                pass
        return data, mtype

    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            if getattr(opened, "n_frames", 1) > 1:
                return _emit(image_bytes, media_type)
            # Both limits decide, not just the long side: a 2000x2000 PNG is
            # well inside the pixel limit and still several megabytes, and
            # the provider rejects it on bytes. Judging the side alone left
            # such images untouched and the request over its inline budget.
            # ``max_bytes <= 0`` means "no byte limit", matching the
            # formatter field where 0 disables the cap.
            within_bytes = max_bytes <= 0 or len(image_bytes) <= max_bytes
            side_limited = max_side > 0
            within_side = not side_limited or max(opened.size) <= max_side
            if within_side and within_bytes:
                return _emit(image_bytes, media_type)
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
            # A no-op when the side is already inside the limit, which is
            # the byte-only case this branch now also serves.
            if side_limited:
                oriented.thumbnail(
                    (max_side, max_side),
                    Image.Resampling.LANCZOS,
                )
            candidate = oriented
            # PNG has no quality knob, so every quality step would emit the
            # same bytes and pay another full deflate for it. Only reducing
            # the side shrinks a PNG.
            quality_steps: tuple[int | None, ...] = (
                (None,) if target == "image/png" else _QUALITY_STEPS
            )
            for _ in range(_MAX_REDUCTIONS):
                for quality in quality_steps:
                    encoded = _encode(candidate, target, has_alpha, quality)
                    if encoded and (
                        max_bytes <= 0 or len(encoded) <= max_bytes
                    ):
                        return _emit(encoded, target)
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
        # Do not call ``_emit`` here: it re-opens the same bytes, so a
        # ``DecompressionBombError`` (or any failure that survives the first
        # ``Image.open``) raises a second time and escapes. Returning the
        # original payload untouched also means no dimensions are recorded,
        # which is correct — this call never inspected the image.
        return image_bytes, media_type
    return _emit(image_bytes, media_type)


def _rescale_source(
    source_data: str,
    media_type: str,
    *,
    max_bytes: int,
    max_side: int,
    observed_sides: list[int] | None = None,
) -> tuple[str, str] | None:
    """Rescale one base64 payload.

    Returns ``(data, media_type)``, or ``None`` meaning "leave it alone".
    The media type belongs to the result because re-encoding can change the
    format: a static GIF is outside :data:`_RESCALABLE_MEDIA_TYPES`, so it is
    written out as PNG. Returning only the bytes would leave the block
    declaring ``image/gif`` for a PNG payload, and the provider would reject
    the request for a second time — for a MIME mismatch instead of a size
    overrun.
    """
    if not source_data or not media_type.startswith("image/"):
        return None
    try:
        raw = base64.b64decode(source_data, validate=True)
    except (ValueError, TypeError):
        return None
    scaled, scaled_type = downscale_image_bytes(
        raw,
        media_type,
        max_bytes=max_bytes,
        max_side=max_side,
        observed_sides=observed_sides,
    )
    if scaled == raw and scaled_type == media_type:
        return None
    return base64.b64encode(scaled).decode("ascii"), scaled_type


def _rescale_block(
    block: Any,
    *,
    max_bytes: int,
    max_side: int,
    observed_sides: list[int] | None = None,
) -> int:
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
            max_bytes=max_bytes,
            max_side=max_side,
            observed_sides=observed_sides,
        )
        if replaced is None:
            return 0
        source["data"], source["media_type"] = replaced
        return 1

    if isinstance(block, DataBlock):
        source = block.source
        if not isinstance(source, Base64Source):
            return 0
        replaced = _rescale_source(
            str(source.data or ""),
            str(source.media_type or ""),
            max_bytes=max_bytes,
            max_side=max_side,
            observed_sides=observed_sides,
        )
        if replaced is None:
            return 0
        data, new_media_type = replaced
        block.source = Base64Source(data=data, media_type=new_media_type)
        return 1
    return 0


def _rescale_value(
    value: Any,
    *,
    max_bytes: int,
    max_side: int,
    observed_sides: list[int] | None = None,
) -> int:
    """Recursively rescale base64 images in messages and tool results."""
    changed = _rescale_block(
        value,
        max_bytes=max_bytes,
        max_side=max_side,
        observed_sides=observed_sides,
    )
    if changed:
        return changed

    if isinstance(value, list):
        return sum(
            _rescale_value(
                item,
                max_bytes=max_bytes,
                max_side=max_side,
                observed_sides=observed_sides,
            )
            for item in value
        )

    if isinstance(value, dict):
        return sum(
            _rescale_value(
                value.get(key),
                max_bytes=max_bytes,
                max_side=max_side,
                observed_sides=observed_sides,
            )
            for key in ("content", "output")
        )

    total = 0
    for attribute in ("content", "output"):
        nested = getattr(value, attribute, None)
        if isinstance(nested, list):
            total += _rescale_value(
                nested,
                max_bytes=max_bytes,
                max_side=max_side,
                observed_sides=observed_sides,
            )
    return total


def downscale_oversized_images(
    msgs: Any,
    *,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
    max_side: int = MAX_IMAGE_SIDE,
    observed_sides: list[int] | None = None,
) -> int:
    """Rescale oversized images on a request copy. Returns the count changed.

    The two limits are passed in rather than read from module constants so a
    provisioned formatter and this pass cannot disagree about what fits.

    ``observed_sides`` collects the longest side of every image inspected,
    including the ones that already fit, so a caller that has to choose a
    smaller rendition afterwards knows what the provider was looking at.
    """
    return _rescale_value(
        msgs,
        max_bytes=max_bytes,
        max_side=max_side,
        observed_sides=observed_sides,
    )


async def downscale_oversized_images_async(
    msgs: Any,
    *,
    max_bytes: int = MAX_INLINE_MEDIA_BYTES,
    max_side: int = MAX_IMAGE_SIDE,
    observed_sides: list[int] | None = None,
) -> int:
    """Rescale a request copy without blocking the event loop.

    Decoding, resizing and re-encoding a single 13 MB PNG takes about a
    second, which is long enough to stall every other request served by the
    same loop. The work therefore runs in a worker thread, after the caller
    has already dropped the media this request will not send.
    """
    return await run_sync_io(
        downscale_oversized_images,
        msgs,
        max_bytes=max_bytes,
        max_side=max_side,
        observed_sides=observed_sides,
    )


__all__ = [
    "MAX_IMAGE_SIDE",
    "downscale_image_bytes",
    "downscale_oversized_images",
    "downscale_oversized_images_async",
]
