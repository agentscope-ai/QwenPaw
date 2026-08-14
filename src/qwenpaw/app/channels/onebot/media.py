# -*- coding: utf-8 -*-
"""Inbound media localization for the OneBot channel."""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiofiles
import aiohttp

from ....schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)
from ..utils import file_url_to_local_path

logger = logging.getLogger(__name__)

DEFAULT_MEDIA_DOWNLOAD_MAX_MB = 50
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_MAX_CONCURRENT_DOWNLOADS = 4
_MAX_FILENAME_STEM_BYTES = 100
_PLACEHOLDER_SUFFIXES = {".bin", ".file", ".part", ".tmp"}
_SAFE_SUFFIX_RE = re.compile(r"\.[a-zA-Z0-9]{1,10}\Z")
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')

_MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "audio/amr": ".amr",
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/avi": ".avi",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
}
_GENERIC_MEDIA_TYPES = {
    "application/octet-stream",
    "binary/octet-stream",
}
_KIND_SUFFIXES = {
    "image": {".gif", ".heic", ".jpg", ".png", ".webp"},
    "audio": {".amr", ".flac", ".m4a", ".mp3", ".ogg", ".wav"},
    "video": {".avi", ".mov", ".mp4", ".webm"},
}

CallApi = Callable[
    [str, dict[str, Any]],
    Awaitable[dict[str, Any]],
]


def _media_kind(part: Any) -> str | None:
    part_type = getattr(part, "type", None)
    if hasattr(part_type, "value"):
        part_type = part_type.value
    if part_type == ContentType.IMAGE.value:
        return "image"
    if part_type == ContentType.AUDIO.value:
        return "audio"
    if part_type == ContentType.VIDEO.value:
        return "video"
    if part_type == ContentType.FILE.value:
        return "file"
    return None


def _part_media_ref(part: Any, kind: str) -> str:
    if kind == "image":
        return str(getattr(part, "image_url", "") or "")
    if kind == "audio":
        return str(getattr(part, "data", "") or "")
    if kind == "video":
        return str(getattr(part, "video_url", "") or "")
    return str(getattr(part, "file_url", "") or "")


def _local_media_path_sync(ref: str) -> str | None:
    path_text = file_url_to_local_path(ref)
    if not path_text:
        return None
    try:
        path = Path(path_text).expanduser()
        if path.is_file():
            return str(path.resolve())
    except OSError:
        return None
    return None


def _is_remote_url(ref: str) -> bool:
    return urllib.parse.urlparse(ref).scheme.lower() in {"http", "https"}


def _suffix_from_bytes(data: bytes) -> str | None:
    signatures = (
        (b"\xff\xd8\xff", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"ID3", ".mp3"),
        (b"#!AMR\n", ".amr"),
        (b"OggS", ".ogg"),
        (b"fLaC", ".flac"),
        (b"%PDF", ".pdf"),
        (b"PK\x03\x04", ".zip"),
    )
    for prefix, suffix in signatures:
        if data.startswith(prefix):
            return suffix

    if data.startswith(b"RIFF") and len(data) >= 12:
        return {
            b"WAVE": ".wav",
            b"WEBP": ".webp",
            b"AVI ": ".avi",
        }.get(data[8:12])

    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"heic", b"heix", b"hevc", b"hevx"}:
            return ".heic"
        return {
            b"qt  ": ".mov",
            b"M4A ": ".m4a",
            b"M4B ": ".m4a",
        }.get(brand, ".mp4")
    return None


def _safe_suffix(value: str) -> str | None:
    suffix = value.lower()
    if _SAFE_SUFFIX_RE.fullmatch(suffix):
        return suffix
    return None


def _suffix_from_media_type(media_type: str) -> str | None:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if not normalized or normalized in _GENERIC_MEDIA_TYPES:
        return None
    known = _MIME_SUFFIXES.get(normalized)
    if known:
        return known
    guessed = mimetypes.guess_extension(normalized, strict=False)
    return _safe_suffix(guessed or "")


def _filename_basename(filename: str) -> str:
    decoded = urllib.parse.unquote((filename or "").strip())
    return decoded.replace("\\", "/").rsplit("/", 1)[-1]


def _hint_suffix(filename: str, kind: str) -> str | None:
    if kind != "file":
        return None
    suffix = _safe_suffix(Path(_filename_basename(filename)).suffix)
    if suffix in _PLACEHOLDER_SUFFIXES:
        return None
    return suffix


def _default_suffix(kind: str) -> str:
    return {
        "image": ".jpg",
        "audio": ".mp3",
        "video": ".mp4",
        "file": ".bin",
    }.get(kind, ".bin")


def _download_suffix(
    media_type: str,
    sniff: bytes,
    filename_hint: str,
    kind: str,
) -> str:
    return (
        _suffix_from_bytes(sniff)
        or _suffix_from_media_type(media_type)
        or _hint_suffix(filename_hint, kind)
        or _default_suffix(kind)
    )


def _media_type_matches_kind(
    media_type: str,
    sniff: bytes,
    kind: str,
) -> bool:
    if kind == "file":
        return True
    normalized = media_type.split(";", 1)[0].strip().lower()
    if not normalized or normalized in _GENERIC_MEDIA_TYPES:
        return True
    if normalized.startswith(f"{kind}/"):
        return True
    return _suffix_from_bytes(sniff) in _KIND_SUFFIXES.get(kind, set())


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _safe_filename_stem(filename: str, kind: str) -> str:
    basename = _filename_basename(filename)
    suffix = Path(basename).suffix
    stem = basename[: -len(suffix)] if suffix else basename
    safe = "".join(
        "_"
        if char in _WINDOWS_INVALID_FILENAME_CHARS or ord(char) < 32
        else char
        for char in stem
    ).strip(" .")
    safe = _truncate_utf8(safe or kind, _MAX_FILENAME_STEM_BYTES)
    return safe.rstrip(" .") or kind


def _content_part_for_local_media(
    part: Any,
    kind: str,
    local_path: str,
) -> Any:
    if kind == "image":
        return ImageContent(
            type=ContentType.IMAGE,
            image_url=local_path,
        )
    if kind == "audio":
        return AudioContent(
            type=ContentType.AUDIO,
            data=local_path,
            format=getattr(part, "format", None),
        )
    if kind == "video":
        return VideoContent(
            type=ContentType.VIDEO,
            video_url=local_path,
        )
    return FileContent(
        type=ContentType.FILE,
        file_url=local_path,
        filename=getattr(part, "filename", None),
    )


class OneBotInboundMedia:
    """Resolve OneBot media references and store remote content locally."""

    def __init__(
        self,
        *,
        media_dir: Path,
        max_download_bytes: int,
        call_api: CallApi,
    ) -> None:
        self._media_dir = media_dir
        self._max_download_bytes = max_download_bytes
        self._call_api = call_api
        self._download_semaphore = asyncio.Semaphore(
            _MAX_CONCURRENT_DOWNLOADS,
        )
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                trust_env=True,
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def resolve(
        self,
        content_parts: list[Any],
        media_segments: list[dict[str, Any]],
        message_type: str,
        event_data: dict[str, Any],
    ) -> list[Any]:
        """Replace inbound media references with managed local paths."""
        source_index = 0
        resolved: list[Any] = []
        for part in content_parts:
            kind = _media_kind(part)
            if kind is None:
                resolved.append(part)
                continue

            segment = (
                media_segments[source_index]
                if source_index < len(media_segments)
                else {}
            )
            source_index += 1
            local_path = await self._localize_part(
                part,
                kind,
                segment,
                source_index - 1,
                message_type,
                event_data,
            )
            if local_path:
                resolved.append(
                    _content_part_for_local_media(
                        part,
                        kind,
                        local_path,
                    ),
                )
            else:
                resolved.append(
                    TextContent(
                        type=ContentType.TEXT,
                        text=f"[{kind}: download failed]",
                    ),
                )
        return resolved

    async def _localize_part(
        self,
        part: Any,
        kind: str,
        segment: dict,
        segment_index: int,
        message_type: str,
        event_data: dict[str, Any],
    ) -> str | None:
        segment_data = (
            segment.get("data", {}) if isinstance(segment, dict) else {}
        )
        ref = _part_media_ref(part, kind)

        local_path = await asyncio.to_thread(_local_media_path_sync, ref)
        if local_path:
            return local_path

        if not _is_remote_url(ref):
            api_ref = await self._resolve_from_api(
                kind,
                segment_data,
                message_type,
                event_data,
            )
            if api_ref:
                ref = api_ref
                local_path = await asyncio.to_thread(
                    _local_media_path_sync,
                    ref,
                )
                if local_path:
                    return local_path

        if not _is_remote_url(ref):
            return None

        parsed_path = urllib.parse.urlparse(ref).path
        filename_hint = (
            segment_data.get("name")
            or segment_data.get("filename")
            or segment_data.get("file")
            or Path(parsed_path).name
            or kind
        )
        return await self.download(
            ref,
            kind,
            segment_index,
            str(filename_hint),
        )

    async def _resolve_from_api(
        self,
        kind: str,
        segment_data: dict[str, Any],
        message_type: str,
        event_data: dict[str, Any],
    ) -> str | None:
        action = ""
        params: dict[str, Any] = {}
        if kind == "file":
            file_id = str(segment_data.get("file_id") or "")
            if message_type == "group" and file_id:
                try:
                    group_id = int(event_data.get("group_id", ""))
                except (TypeError, ValueError):
                    return None
                action = "get_group_file_url"
                params = {
                    "group_id": group_id,
                    "file_id": file_id,
                }
            elif file_id:
                action = "get_private_file_url"
                params = {"file_id": file_id}
        elif kind in {"image", "audio"}:
            file_ref = str(segment_data.get("file") or "")
            if file_ref:
                action = "get_image" if kind == "image" else "get_record"
                params = {"file": file_ref}
                if kind == "audio":
                    params["out_format"] = "mp3"

        if not action:
            return None

        try:
            result = await self._call_api(action, params)
        except Exception:
            logger.warning(
                "onebot: failed to resolve %s media URL",
                kind,
                exc_info=True,
            )
            return None

        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict):
            return str(data.get("url") or data.get("file") or "") or None
        return None

    async def download(
        self,
        url: str,
        kind: str,
        segment_index: int,
        filename_hint: str,
    ) -> str | None:
        """Stream one remote media URL into the configured directory."""
        async with self._download_semaphore:
            await self.start()
            session = self._session
            assert session is not None

            temp_path: Path | None = None
            try:
                async with session.get(
                    url,
                    allow_redirects=True,
                    max_redirects=3,
                ) as response:
                    response.raise_for_status()
                    content_length = response.content_length
                    if (
                        content_length is not None
                        and content_length > self._max_download_bytes
                    ):
                        logger.warning(
                            "onebot: remote %s exceeds media limit: %s "
                            "bytes",
                            kind,
                            content_length,
                        )
                        return None

                    await asyncio.to_thread(
                        self._media_dir.mkdir,
                        parents=True,
                        exist_ok=True,
                    )
                    temp_path = self._media_dir / (f".{uuid.uuid4().hex}.part")
                    sniff = b""
                    total = 0
                    async with aiofiles.open(temp_path, "xb") as temp_file:
                        async for chunk in response.content.iter_chunked(
                            _DOWNLOAD_CHUNK_SIZE,
                        ):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > self._max_download_bytes:
                                logger.warning(
                                    "onebot: remote %s download exceeded "
                                    "media limit",
                                    kind,
                                )
                                return None
                            if len(sniff) < 32:
                                sniff += chunk[: 32 - len(sniff)]
                            await temp_file.write(chunk)

                    if total == 0:
                        return None

                    media_type = response.headers.get("Content-Type", "")
                    if not _media_type_matches_kind(
                        media_type,
                        sniff,
                        kind,
                    ):
                        logger.warning(
                            "onebot: remote %s returned unexpected content "
                            "type %s",
                            kind,
                            media_type,
                        )
                        return None

                    final_path = await asyncio.to_thread(
                        self._finalize_download,
                        temp_path,
                        sniff,
                        media_type,
                        kind,
                        segment_index,
                        filename_hint,
                    )
                    temp_path = None
                    return final_path
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ValueError,
                OSError,
            ):
                logger.warning(
                    "onebot: failed to download remote %s %s",
                    kind,
                    url,
                    exc_info=True,
                )
                return None
            finally:
                if temp_path is not None:
                    try:
                        await asyncio.to_thread(temp_path.unlink)
                    except OSError:
                        pass

    def _finalize_download(
        self,
        temp_path: Path,
        sniff: bytes,
        media_type: str,
        kind: str,
        segment_index: int,
        filename_hint: str,
    ) -> str:
        suffix = _download_suffix(
            media_type,
            sniff,
            filename_hint,
            kind,
        )
        stem = _safe_filename_stem(filename_hint, kind)
        filename = f"{uuid.uuid4().hex}_{segment_index}_{stem}{suffix}"
        final_path = (self._media_dir / filename).resolve()
        os.replace(temp_path, final_path)
        return str(final_path)
