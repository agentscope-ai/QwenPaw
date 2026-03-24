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


def _current_model_supports_multimodal() -> bool:
    """Check if the active model supports multimodal input."""
    try:
        from copaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        active = manager.get_active_model()
        if not active:
            return False
        provider = manager.get_provider(active.provider_id)
        if not provider:
            return False
        for model in provider.models + provider.extra_models:
            if model.id == active.model:
                return bool(model.supports_multimodal)
        return False
    except Exception:
        # If we can't determine, allow the image through (safe default)
        return True


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
    # Check if the current model supports multimodal input
    if not _current_model_supports_multimodal():
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: The current model is text-only and cannot "
                        "process images. Please ask the user to switch to a "
                        "multimodal model (e.g. qwen3.5-plus) to view images."
                    ),
                ),
            ],
        )
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
