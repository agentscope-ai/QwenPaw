# -*- coding: utf-8 -*-
"""Load an image file into the LLM context for visual analysis."""

import mimetypes
import os
import unicodedata
from pathlib import Path

from agentscope.message import ImageBlock, TextBlock
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
