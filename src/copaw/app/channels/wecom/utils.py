# -*- coding: utf-8 -*-
"""WeCom channel utility functions."""

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

from ..base import ContentType, ImageContent

logger = logging.getLogger(__name__)


def detect_image_suffix(data: bytes) -> Optional[str]:
    """Detect image format from magic bytes, return suffix (with dot)."""
    if len(data) < 12:
        return None

    checks = [
        (data[:8] == b"\x89PNG\r\n\x1a\n", ".png"),
        (data[:3] == b"\xff\xd8\xff", ".jpg"),
        (data[:4] in (b"GIF8", b"GIF9"), ".gif"),
        (data[:4] == b"RIFF" and data[8:12] == b"WEBP", ".webp"),
        (data[:2] == b"BM", ".bmp"),
    ]
    for match, suffix in checks:
        if match:
            return suffix
    return None


def save_image_to_dir(data: bytes, media_dir: Path) -> ImageContent:
    """Save raw image bytes to media directory, return ImageContent.

    Args:
        data: Raw image bytes.
        media_dir: Directory to save image files.

    Returns:
        ImageContent with local file path.
    """
    suffix = detect_image_suffix(data) or ".jpg"

    # Generate unique filename (suffix required by agentscope formatter)
    file_hash = hashlib.md5(data).hexdigest()[:12]
    ts = int(time.time() * 1000)
    filename = f"wecom_img_{ts}_{file_hash}{suffix}"
    save_path = media_dir / filename
    save_path.write_bytes(data)

    logger.info("[WeCom] Image saved: %s", save_path)
    return ImageContent(type=ContentType.IMAGE, image_url=str(save_path))
