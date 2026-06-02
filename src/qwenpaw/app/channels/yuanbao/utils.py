# -*- coding: utf-8 -*-
"""Yuanbao channel utilities for file handling and media operations."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Optional

import aiohttp

from .constants import MEDIA_MAX_BYTES

logger = logging.getLogger(__name__)


async def download_media(
    url: str,
    media_dir: Path,
    filename: str = "",
    headers: Optional[dict] = None,
) -> Optional[str]:
    """Download a media file from URL to local media directory.

    Args:
        url: Remote URL of the media file.
        media_dir: Local directory to save the file.
        filename: Optional filename hint.
        headers: Optional HTTP headers (e.g. auth headers for Yuanbao CDN).

    Returns:
        Local file path on success, None on failure.
    """
    media_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "yuanbao: download failed status=%s url=%s",
                        resp.status,
                        url,
                    )
                    return None

                content_length = resp.content_length or 0
                if content_length > MEDIA_MAX_BYTES:
                    logger.warning(
                        "yuanbao: file too large (%s bytes), skipping",
                        content_length,
                    )
                    return None

                data = await resp.read()
                if len(data) > MEDIA_MAX_BYTES:
                    logger.warning(
                        "yuanbao: downloaded data too large (%s bytes)",
                        len(data),
                    )
                    return None

                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )

                extension = _resolve_extension(content_type, filename)
                safe_name = _build_safe_filename(filename, extension)
                local_path = media_dir / safe_name

                local_path.write_bytes(data)
                logger.debug("yuanbao: downloaded %s -> %s", url, local_path)
                return str(local_path)

    except aiohttp.ClientError as exc:
        logger.error("yuanbao: download error: %s", exc)
        return None
    except Exception as exc:
        logger.error("yuanbao: unexpected download error: %s", exc)
        return None


def resolve_local_path(file_url: str) -> Optional[str]:
    """Resolve a file:// URL or local path to an absolute path.

    Returns None for remote URLs or if the local file does not exist.
    """
    if file_url.startswith(("http://", "https://")):
        return None
    if file_url.startswith("file://"):
        path_str = file_url[7:]
    else:
        path_str = file_url

    path = Path(path_str).expanduser().resolve()
    if path.is_file():
        return str(path)
    return None


def guess_mime_type(file_path: str) -> str:
    """Guess MIME type from file path, defaulting to octet-stream."""
    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/octet-stream"


def _resolve_extension(content_type: str, filename: str) -> str:
    """Determine file extension from content type or filename."""
    if content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ext
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    return ".bin"


def _build_safe_filename(filename: str, extension: str) -> str:
    """Build a safe, unique filename for local storage."""
    uid = uuid.uuid4().hex[:12]
    if filename:
        stem = Path(filename).stem
        safe_stem = "".join(c for c in stem if c.isalnum() or c in "-_")
        if safe_stem:
            return f"{safe_stem}_{uid}{extension}"
    return f"yuanbao_{uid}{extension}"
