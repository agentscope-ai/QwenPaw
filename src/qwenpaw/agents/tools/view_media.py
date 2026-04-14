# -*- coding: utf-8 -*-
"""Load image or video files into the LLM context for analysis."""

import mimetypes
import os
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Optional

from agentscope.message import ImageBlock, TextBlock, VideoBlock
from agentscope.tool import ToolResponse

_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
}

_VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mpeg",
    ".mov",
    ".avi",
    ".mkv",
}


def _is_url(path: str) -> bool:
    """Return True if *path* looks like an HTTP(S) URL."""
    return path.startswith(("http://", "https://"))


def _validate_url_extension(
    url: str,
    allowed_extensions: set[str],
    mime_prefix: str,
) -> Optional[ToolResponse]:
    """Optionally validate that the URL path has an allowed extension.

    Returns an error ``ToolResponse`` when the extension is clearly
    unsupported, or ``None`` to let it through (including when the URL
    has no recognisable extension, e.g. dynamic endpoints).
    """
    url_path = urllib.parse.urlparse(url).path
    ext = Path(url_path).suffix.lower()
    if not ext:
        return None
    mime, _ = mimetypes.guess_type(url_path)
    if ext not in allowed_extensions and (
        not mime or not mime.startswith(f"{mime_prefix}/")
    ):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: URL does not point to a "
                    f"supported {mime_prefix} format: {url}",
                ),
            ],
        )
    return None


def _validate_media_path(
    file_path: str,
    allowed_extensions: set[str],
    mime_prefix: str,
) -> tuple[Path, Optional[ToolResponse]]:
    """Validate a local media file path.

    Returns ``(resolved_path, None)`` on success or
    ``(_, error_response)`` on failure.
    """
    file_path = unicodedata.normalize(
        "NFC",
        os.path.expanduser(file_path),
    )
    resolved = Path(file_path).resolve()

    if not resolved.exists() or not resolved.is_file():
        return resolved, ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {file_path} does not exist "
                    "or is not a file.",
                ),
            ],
        )

    ext = resolved.suffix.lower()
    mime, _ = mimetypes.guess_type(str(resolved))
    if ext not in allowed_extensions and (
        not mime or not mime.startswith(f"{mime_prefix}/")
    ):
        return resolved, ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {resolved.name} is not a "
                    f"supported {mime_prefix} format.",
                ),
            ],
        )

    return resolved, None


async def view_image(image_path: str) -> ToolResponse:
    """Load an image into the LLM context so the model can see it.

    Accepts a local file path **or** an HTTP(S) URL.  Online URLs are
    passed directly to the model without downloading.

    Args:
        image_path (`str`):
            Local path or HTTP(S) URL of the image to view.

    Returns:
        `ToolResponse`:
            An ImageBlock the model can inspect, or an error message.
    """
    if _is_url(image_path):
        err = _validate_url_extension(
            image_path,
            _IMAGE_EXTENSIONS,
            "image",
        )
        if err is not None:
            return err
        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={"type": "url", "url": image_path},
                ),
                TextBlock(
                    type="text",
                    text=f"Image loaded from URL: {image_path}",
                ),
            ],
        )

    resolved, err = _validate_media_path(
        image_path,
        _IMAGE_EXTENSIONS,
        "image",
    )
    if err is not None:
        return err

    return ToolResponse(
        content=[
            ImageBlock(
                type="image",
                source={"type": "url", "url": str(resolved)},
            ),
            TextBlock(
                type="text",
                text=f"Image loaded: {resolved.name}",
            ),
        ],
    )


async def view_video(video_path: str) -> ToolResponse:
    """Load a video into the LLM context so the model can see it.

    Accepts a local file path **or** an HTTP(S) URL.  Online URLs are
    passed directly to the model without downloading.

    Args:
        video_path (`str`):
            Local path or HTTP(S) URL of the video to view.

    Returns:
        `ToolResponse`:
            A VideoBlock the model can inspect, or an error message.
    """
    if _is_url(video_path):
        err = _validate_url_extension(
            video_path,
            _VIDEO_EXTENSIONS,
            "video",
        )
        if err is not None:
            return err
        return ToolResponse(
            content=[
                VideoBlock(
                    type="video",
                    source={"type": "url", "url": video_path},
                ),
                TextBlock(
                    type="text",
                    text=f"Video loaded from URL: {video_path}",
                ),
            ],
        )

    resolved, err = _validate_media_path(
        video_path,
        _VIDEO_EXTENSIONS,
        "video",
    )
    if err is not None:
        return err

    return ToolResponse(
        content=[
            VideoBlock(
                type="video",
                source={"type": "url", "url": str(resolved)},
            ),
            TextBlock(
                type="text",
                text=f"Video loaded: {resolved.name}",
            ),
        ],
    )
