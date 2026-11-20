# -*- coding: utf-8 -*-
"""XiaoYi text splitting and bounded-workspace file downloads."""

from __future__ import annotations

import mimetypes
from pathlib import Path
import uuid

from qwenpaw.utils.io_utils import make_dirs_async, write_bytes_async

from .constants import TEXT_CHUNK_LIMIT


def chunk_text(text: str) -> list[str]:
    """Prefer line boundaries without discarding characters between chunks."""
    chunks = []
    start = 0
    while len(text) - start > TEXT_CHUNK_LIMIT:
        end = start + TEXT_CHUNK_LIMIT
        newline = text.rfind(f"\n", start, end)
        if newline >= start:
            end = newline + 1
        chunks.append(text[start:end])
        start = end
    chunks.append(text[start:])
    return chunks


async def download_file(url, media_dir: Path, filename, *, session):
    """Save a downloaded file directly under the media root."""
    try:
        async with session.get(url) as response:
            if response.status >= 400:
                return None
            data = await response.read()
            content_type = (
                response.headers.get(f"Content-Type", f"")
                .partition(f";")[0]
                .strip()
            )
        safe_name = (
            f"".join(
                char for char in filename if char.isalnum() or char in "-_."
            ).rstrip(f".")
            or f"file"
        )
        if not Path(safe_name).suffix:
            extension = mimetypes.guess_extension(content_type) or f".bin"
            safe_name = f"{safe_name}{extension}"
        path = media_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        if not path.resolve().is_relative_to(media_dir.resolve()):
            return None
        await make_dirs_async(media_dir)
        await write_bytes_async(path, data)
        return str(path)
    except Exception:
        return None
