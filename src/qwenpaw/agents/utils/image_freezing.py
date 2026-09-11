# -*- coding: utf-8 -*-
"""Freeze local image references into immutable message content."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from agentscope.message import (
    Base64Source,
    DataBlock,
    TextBlock,
)
from PIL import Image, UnidentifiedImageError

from ...providers.capping_formatter import MAX_INLINE_MEDIA_BYTES
from ...utils.io_utils import run_sync_io

_NATIVE_IMAGE_MEDIA_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    },
)
_PNG_CONVERTIBLE_IMAGE_FORMATS = frozenset({"BMP", "TIFF"})


def validate_image_bytes(
    image_bytes: bytes,
    display_name: str,
) -> tuple[str | None, str | None]:
    """Validate image bytes and return their detected media type."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            normalized_format = (image.format or "").upper()
            media_type = Image.MIME.get(normalized_format)
            if (
                media_type not in _NATIVE_IMAGE_MEDIA_TYPES
                and normalized_format not in _PNG_CONVERTIBLE_IMAGE_FORMATS
            ):
                detected = media_type or image.format or "unknown"
                return (
                    None,
                    f"Error: {display_name} uses unsupported image "
                    f"format {detected}.",
                )
            image.verify()
    except (
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        return None, f"Error: {display_name} is not a valid image: {exc}"

    return media_type, None


def _local_path_from_url(url: str) -> Path | None:
    """Resolve a local URL or path without treating remote URLs as local."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        if (
            len(parsed.netloc) == 2
            and parsed.netloc[0].isalpha()
            and parsed.netloc[1] == ":"
        ):
            raw_path = f"{parsed.netloc}{parsed.path}"
        elif parsed.netloc and parsed.netloc.lower() != "localhost":
            raw_path = f"//{parsed.netloc}{parsed.path}"
        else:
            raw_path = parsed.path
        return Path(url2pathname(unquote(raw_path)))
    if parsed.scheme == "":
        return Path(unquote(url)).expanduser()
    if len(parsed.scheme) == 1 and parsed.scheme.isalpha():
        return Path(unquote(url))
    return None


def freeze_image_bytes(
    image_bytes: bytes,
    display_name: str,
) -> tuple[DataBlock | None, str | None]:
    """Validate image bytes and freeze them as immutable base64 content."""
    if len(image_bytes) > MAX_INLINE_MEDIA_BYTES:
        return (
            None,
            f"Error: {display_name} exceeds the "
            f"{MAX_INLINE_MEDIA_BYTES}-byte image limit.",
        )

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            normalized_format = (image.format or "").upper()
            media_type = Image.MIME.get(normalized_format)
            if media_type in _NATIVE_IMAGE_MEDIA_TYPES:
                image.verify()
                frozen_bytes = image_bytes
            elif normalized_format in _PNG_CONVERTIBLE_IMAGE_FORMATS:
                image.seek(0)
                image.load()
                has_alpha = (
                    "A" in image.getbands() or "transparency" in image.info
                )
                target_mode = "RGBA" if has_alpha else "RGB"
                with image.convert(target_mode) as converted:
                    output = BytesIO()
                    converted.save(output, format="PNG")
                    frozen_bytes = output.getvalue()
                media_type = "image/png"
            else:
                detected = media_type or image.format or "unknown"
                return (
                    None,
                    f"Error: {display_name} uses unsupported image "
                    f"format {detected}.",
                )
    except (
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        return None, f"Error: {display_name} is not a valid image: {exc}"

    if len(frozen_bytes) > MAX_INLINE_MEDIA_BYTES:
        return (
            None,
            f"Error: converted {display_name} is "
            f"{len(frozen_bytes)} bytes and exceeds the "
            f"{MAX_INLINE_MEDIA_BYTES}-byte image limit.",
        )

    encoded = base64.b64encode(frozen_bytes).decode("ascii")
    return (
        DataBlock(
            source=Base64Source(
                data=encoded,
                media_type=media_type,
            ),
        ),
        None,
    )


def freeze_local_image(
    image_path: Path,
) -> tuple[DataBlock | None, str | None]:
    """Read, validate, and freeze one local image as immutable content."""
    try:
        file_size = image_path.stat().st_size
        if file_size > MAX_INLINE_MEDIA_BYTES:
            return (
                None,
                f"Error: {image_path.name} is {file_size} bytes and "
                f"exceeds the {MAX_INLINE_MEDIA_BYTES}-byte image limit.",
            )
        with image_path.open("rb") as image_file:
            image_bytes = image_file.read(MAX_INLINE_MEDIA_BYTES + 1)
    except OSError as exc:
        return None, f"Error: {image_path.name} is not a valid image: {exc}"

    return freeze_image_bytes(image_bytes, image_path.name)


def _replacement_text(value: Any, error: str) -> Any:
    """Build a text replacement matching the original representation."""
    text = f"[Image unavailable: {error}]"
    if isinstance(value, dict):
        return {"type": "text", "text": text}
    return TextBlock(text=text)


# pylint: disable-next=too-many-return-statements
def _freeze_data_block(value: Any) -> tuple[Any, int]:
    """Freeze one local image data block when applicable."""
    if isinstance(value, dict):
        block_type = value.get("type")
        source = value.get("source")
        if block_type not in ("data", "image") or not isinstance(
            source,
            dict,
        ):
            return value, 0
        media_type = str(source.get("media_type", "") or "")
        url = source.get("url") if source.get("type") == "url" else None
    elif isinstance(value, DataBlock):
        source = value.source
        media_type = str(getattr(source, "media_type", "") or "")
        url = getattr(source, "url", None)
    else:
        return value, 0

    if not media_type.startswith("image/") or url is None:
        return value, 0
    local_path = _local_path_from_url(str(url))
    if local_path is None:
        return value, 0

    frozen, error = freeze_local_image(local_path)
    if frozen is None or error is not None:
        return _replacement_text(value, error or "failed to load image"), 1

    if isinstance(value, dict):
        result = dict(value)
        result["type"] = block_type
        result["source"] = frozen.source.model_dump(mode="json")
        return result, 1
    frozen.name = getattr(value, "name", None)
    return frozen, 1


def _freeze_value(value: Any) -> tuple[Any, int]:
    """Recursively freeze local images in messages and tool results."""
    replacement, count = _freeze_data_block(value)
    if count:
        return replacement, count

    if isinstance(value, list):
        total = 0
        for index, item in enumerate(value):
            value[index], frozen = _freeze_value(item)
            total += frozen
        return value, total

    if isinstance(value, dict):
        total = 0
        for key in ("content", "output"):
            nested = value.get(key)
            if isinstance(nested, list):
                value[key], frozen = _freeze_value(nested)
                total += frozen
        return value, total

    total = 0
    for attribute in ("content", "output"):
        nested = getattr(value, attribute, None)
        if isinstance(nested, list):
            nested, frozen = _freeze_value(nested)
            setattr(value, attribute, nested)
            total += frozen
    return value, total


def freeze_local_images(value: Any) -> int:
    """Freeze all local image references reachable from *value*."""
    _, count = _freeze_value(value)
    return count


async def freeze_local_images_async(value: Any) -> int:
    """Freeze local images in a worker thread."""
    return await run_sync_io(freeze_local_images, value)


__all__ = [
    "freeze_image_bytes",
    "freeze_local_image",
    "freeze_local_images",
    "freeze_local_images_async",
    "validate_image_bytes",
]
