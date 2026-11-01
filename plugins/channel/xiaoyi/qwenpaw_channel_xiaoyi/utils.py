# -*- coding: utf-8 -*-
"""XiaoYi text splitting and bounded-workspace file downloads."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import aiohttp

from .constants import TEXT_CHUNK_LIMIT


def chunk_text(text: str) -> list[str]:
    """Retain the native 4000-character, newline-first splitting algorithm."""
    if len(text) <= TEXT_CHUNK_LIMIT:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(line) > TEXT_CHUNK_LIMIT:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            chunks.extend(
                line[index : index + TEXT_CHUNK_LIMIT]
                for index in range(0, len(line), TEXT_CHUNK_LIMIT)
            )
        else:
            combined = current + "\n" + line if current else line
            if len(combined) > TEXT_CHUNK_LIMIT:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = combined
    if current:
        chunks.append(current)
    return chunks


async def download_file(url, media_dir: Path, filename, *, session=None):
    """Use an owned HTTP session when supplied; failure remains a placeholder."""
    owned = session is None
    if owned:
        session = aiohttp.ClientSession()
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        async with session.get(url) as response:
            if response.status >= 400:
                return None
            data = await response.read()
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].strip()
            )
            extension = mimetypes.guess_extension(content_type) or ""
            extension = extension or Path(filename).suffix or ".bin"
            safe_name = "".join(
                char for char in filename if char.isalnum() or char in "-_."
            )
            if not safe_name or safe_name in {".", ".."}:
                safe_name = "file"
            if not Path(safe_name).suffix:
                safe_name = f"{Path(safe_name).stem}{extension}"
            path = media_dir / safe_name
            if not path.resolve().is_relative_to(media_dir.resolve()):
                return None
            path.write_bytes(data)
            return str(path)
    except Exception:
        return None
    finally:
        if owned:
            await session.close()
