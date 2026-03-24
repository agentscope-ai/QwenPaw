# -*- coding: utf-8 -*-
"""Load an image file into the LLM context for visual analysis."""

import logging
import mimetypes
import os
import unicodedata
from pathlib import Path

from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse

from .file_io import _is_cloud_mode

_logger = logging.getLogger(__name__)

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


async def view_image(image_path: str) -> ToolResponse:
    """Load an image file into the LLM context so the model can see it.

    Use this after desktop_screenshot, browser_use, or any tool that
    produces an image file path.

    Args:
        image_path (`str`):
            Path to the image file to view.

    Returns:
        `ToolResponse`:
            An ImageBlock the model can inspect, or an error message.
    """
    image_path = unicodedata.normalize(
        "NFC",
        os.path.expanduser(image_path),
    )

    # In cloud mode, download the image from sandbox first
    if _is_cloud_mode():
        try:
            from .send_file import _download_from_sandbox
            local_path = await _download_from_sandbox(image_path)
            resolved = Path(local_path).resolve()
        except Exception as e:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=f"Error: Failed to download image from sandbox: {e}",
                    ),
                ],
            )
    else:
        resolved = Path(image_path).resolve()

    if not resolved.exists() or not resolved.is_file():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {image_path} does not exist or "
                    "is not a file.",
                ),
            ],
        )

    ext = resolved.suffix.lower()
    mime, _ = mimetypes.guess_type(str(resolved))
    if ext not in _IMAGE_EXTENSIONS and (
        not mime or not mime.startswith("image/")
    ):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {resolved.name} is not a supported "
                    "image format.",
                ),
            ],
        )

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
