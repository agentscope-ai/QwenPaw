# -*- coding: utf-8 -*-
"""Request-time image resizing controlled by an environment variable."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
import math
import os
import re

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_PIXELS_ENV = "QWENPAW_MAX_IMAGE_PIXELS"

_PROVIDER_MAX_PIXELS_PATTERNS = (
    re.compile(
        r"maximum allowed(?: total)?(?: pixels)?\s*[:=]?\s*"
        r"([0-9][0-9_,]*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"max(?:imum)?(?: total)? pixels\s*[:=]?\s*([0-9][0-9_,]*)",
        re.IGNORECASE,
    ),
)


def get_max_image_pixels() -> int:
    """Return the configured request-time image pixel limit.

    An unset, empty, or zero value disables resizing. Invalid and negative
    values raise a user-actionable configuration error.
    """
    raw = os.environ.get(MAX_IMAGE_PIXELS_ENV, "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{MAX_IMAGE_PIXELS_ENV} must be zero or a positive integer, "
            f"got {raw!r}.",
        ) from exc
    if value < 0:
        raise ValueError(
            f"{MAX_IMAGE_PIXELS_ENV} must be zero or a positive integer, "
            f"got {raw!r}.",
        )
    return value


def _resized_dimensions(
    width: int,
    height: int,
    max_pixels: int,
) -> tuple[int, int]:
    """Return proportional dimensions within the configured pixel limit."""
    scale = math.sqrt(max_pixels / (width * height))
    resized_width = max(1, math.floor(width * scale))
    resized_height = max(1, math.floor(height * scale))
    while resized_width * resized_height > max_pixels:
        if resized_width >= resized_height:
            resized_width -= 1
        else:
            resized_height -= 1
    return resized_width, resized_height


def _image_save_options(image: Image.Image) -> dict[str, object]:
    """Return safe metadata to retain in a request-local resized image."""
    options: dict[str, object] = {}
    icc_profile = image.info.get("icc_profile")
    if icc_profile:
        options["icc_profile"] = icc_profile
    return options


def resize_base64_image(
    data: str,
    max_pixels: int,
) -> tuple[str, bool]:
    """Resize one base64 image when it exceeds ``max_pixels``.

    Returns the encoded image and whether a resize occurred. The source data
    is never changed when resizing is disabled or unnecessary.
    """
    if max_pixels <= 0:
        return data, False

    try:
        image_bytes = base64.b64decode(data)
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            if width * height <= max_pixels:
                return data, False
            if getattr(image, "is_animated", False):
                raise ValueError(
                    "Automatic resizing does not support animated images.",
                )

            image_format = (image.format or "").upper()
            if image_format not in ("GIF", "JPEG", "PNG", "WEBP"):
                raise ValueError(
                    f"Automatic resizing does not support image format "
                    f"{image_format or 'unknown'}.",
                )

            resized_size = _resized_dimensions(
                width,
                height,
                max_pixels,
            )
            image.load()
            save_options = _image_save_options(image)
            resized = image.resize(resized_size, Image.Resampling.LANCZOS)
            try:
                if image_format == "JPEG" and resized.mode not in (
                    "L",
                    "RGB",
                ):
                    converted = resized.convert("RGB")
                    resized.close()
                    resized = converted
                output = BytesIO()
                resized.save(output, format=image_format, **save_options)
            finally:
                resized.close()
    except (
        binascii.Error,
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
    ) as exc:
        raise ValueError(
            f"Failed to resize image using {MAX_IMAGE_PIXELS_ENV}: {exc}",
        ) from exc

    return base64.b64encode(output.getvalue()).decode("ascii"), True


def _provider_max_pixels(error_text: str) -> int | None:
    """Extract a provider-reported maximum pixel count when available."""
    for pattern in _PROVIDER_MAX_PIXELS_PATTERNS:
        match = pattern.search(error_text)
        if match is None:
            continue
        try:
            return int(match.group(1).replace(",", "").replace("_", ""))
        except ValueError:
            continue
    return None


# pylint: disable-next=too-many-return-statements
def image_pixel_limit_hint(exc: Exception) -> str | None:
    """Return an actionable environment hint for image pixel-limit errors."""
    error_text = " ".join(str(exc).split())
    normalized = error_text.lower()
    if "image" not in normalized or "pixel" not in normalized:
        return None
    if not any(
        marker in normalized
        for marker in (
            "exceeds",
            "maximum allowed",
            "max pixels",
            "too many pixels",
        )
    ):
        return None

    provider_limit = _provider_max_pixels(error_text)
    try:
        configured_limit = get_max_image_pixels()
    except ValueError as exc_config:
        return str(exc_config)

    if provider_limit is None:
        return (
            f"Set {MAX_IMAGE_PIXELS_ENV} to the provider's documented "
            f"maximum pixel count and restart QwenPaw to enable "
            f"request-time image resizing."
        )

    setting = f"{MAX_IMAGE_PIXELS_ENV}={provider_limit}"
    if configured_limit <= 0:
        return (
            f"Set {setting} and restart QwenPaw to resize oversized images "
            f"before model requests."
        )
    if configured_limit > provider_limit:
        return (
            f"{MAX_IMAGE_PIXELS_ENV} is currently {configured_limit}; "
            f"lower it to {provider_limit} and restart QwenPaw."
        )
    return (
        f"{MAX_IMAGE_PIXELS_ENV} is currently {configured_limit}; reduce it "
        f"further and restart QwenPaw."
    )


__all__ = [
    "MAX_IMAGE_PIXELS_ENV",
    "get_max_image_pixels",
    "image_pixel_limit_hint",
    "resize_base64_image",
]
