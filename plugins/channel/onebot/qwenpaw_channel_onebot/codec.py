# -*- coding: utf-8 -*-
"""Pure OneBot CQ parsing, quote markers and native text/media policies."""

from __future__ import annotations
import asyncio
import base64
import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from qwenpaw.app.channels.utils import file_url_to_local_path

logger = logging.getLogger(__name__)


async def _run_in_thread(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def session_id(user_id, meta, share_session_in_group=False):
    if meta.get("is_group"):
        group = str(meta.get("group_id") or "")
        return (
            f"onebot:g:{group}"
            if share_session_in_group
            else f"onebot:{group}:{user_id}"
        )
    return f"onebot:{user_id}"


def parse_segments(segments, self_id):
    parts, media_segments, mentioned = [], [], False
    for segment in segments:
        kind = segment.get("type")
        data = segment.get("data")
        data = data if isinstance(data, dict) else {}
        if kind == "text":
            text = str(data.get("text") or "").strip()
            if text:
                parts.append({"type": "text", "text": text})
        elif kind in {"image", "record", "video", "file"}:
            locator = data.get("url") or data.get("file") or ""
            name = data.get("name") or data.get("file") or "file"
            if locator or (kind == "file" and data.get("file_id")):
                content_type = "audio" if kind == "record" else kind
                field = (
                    "data"
                    if content_type == "audio"
                    else content_type + "_url"
                )
                part = {"type": content_type, field: str(locator or name)}
                if kind == "file":
                    part["filename"] = str(name)
                parts.append(part)
                media_segments.append(segment)
        elif (
            kind == "at"
            and self_id is not None
            and str(data.get("qq")) == str(self_id)
        ):
            mentioned = True
    return parts, mentioned, media_segments


_CODE_FENCE_RE = re.compile(r"^[ \t]{0,3}(?P<mark>`{3,}|~{3,})")


_MARKDOWN_LINK_RE = re.compile(
    r"\[(?P<label>[^\]\n]+)\]"
    r"\((?P<url>https?://(?:[^\s()]|\([^\s()]*\))+)\)",
)


_WRAPPED_URL_RE = re.compile(
    r"(?P<mark>\*\*|__)(?P<url>https?://\S+?)(?P=mark)",
)


_CQ_UNESCAPE_REPLACEMENTS = (
    ("&#44;", ","),
    ("&#91;", "["),
    ("&#93;", "]"),
    ("&#38;", "&"),
    ("&amp;", "&"),
)


def _unescape_cq_value(value: str) -> str:
    """Decode OneBot CQ-code escaping without applying generic HTML rules."""
    for escaped, decoded in _CQ_UNESCAPE_REPLACEMENTS:
        value = value.replace(escaped, decoded)
    return value


def _clean_links(text: str) -> str:
    """Convert supported Markdown links to readable plain text."""
    text = _MARKDOWN_LINK_RE.sub(
        lambda match: f"{match.group('label')}: {match.group('url')}",
        text,
    )
    return _WRAPPED_URL_RE.sub(lambda match: match.group("url"), text)


def _clean_inline_text(text: str) -> str:
    """Clean links outside inline code spans."""
    result: list[str] = []
    cursor = 0
    while cursor < len(text):
        opening = text.find("`", cursor)
        if opening < 0:
            result.append(_clean_links(text[cursor:]))
            break

        result.append(_clean_links(text[cursor:opening]))
        run_end = opening
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        marker = text[opening:run_end]
        closing = text.find(marker, run_end)
        if closing < 0:
            result.append(text[opening:])
            break

        closing_end = closing + len(marker)
        result.append(text[opening:closing_end])
        cursor = closing_end
    return "".join(result)


def _clean_onebot_plain_text(text: str) -> str:
    """Clean link formatting for OneBot/QQ plain-text delivery.

    OneBot text segments are rendered by QQ as plain text. Keep links as bare
    URLs so the client can auto-link them without changing non-link markup.
    """
    if not text:
        return text

    result: list[str] = []
    outside_fence: list[str] = []
    fence_mark = ""

    def _flush_outside_fence() -> None:
        if outside_fence:
            result.append(_clean_inline_text("".join(outside_fence)))
            outside_fence.clear()

    for line in text.splitlines(keepends=True):
        match = _CODE_FENCE_RE.match(line)
        if fence_mark:
            result.append(line)
            if (
                match
                and match.group("mark")[0] == fence_mark[0]
                and len(
                    match.group("mark"),
                )
                >= len(fence_mark)
            ):
                fence_mark = ""
            continue
        if match:
            _flush_outside_fence()
            fence_mark = match.group("mark")
            result.append(line)
            continue
        outside_fence.append(line)

    _flush_outside_fence()
    return "".join(result)


def _local_path_from_media_ref(ref: str) -> Path | None:
    """Resolve a local filesystem path from a media reference if possible."""
    path_text = file_url_to_local_path(ref)
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        if path.is_file():
            return path
    except OSError:
        return None
    return None


def _local_media_base64_ref(
    ref: str,
    path: Path,
    media_base64_max_bytes: int,
) -> str:
    """Convert a local OneBot media file to base64 when safe."""
    try:
        size = path.stat().st_size
        if size > media_base64_max_bytes:
            logger.warning(
                "onebot: local media file %s is %s bytes, exceeds "
                "media_base64_max_bytes=%s; sending path instead",
                path,
                size,
                media_base64_max_bytes,
            )
            return ref
        data = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        logger.warning("onebot: failed to read local media file %s", path)
        return ref
    return "base64://" + data


def _normalize_media_ref_sync(
    ref: str,
    *,
    media_base64: bool = False,
    media_base64_max_bytes: int,
) -> str:
    """Normalize media references for OneBot clients."""
    if not ref or ref.startswith("base64://"):
        return ref
    if ref.startswith("data:") and ";base64," in ref:
        return "base64://" + ref.split(";base64,", 1)[1]

    path = _local_path_from_media_ref(ref) if media_base64 else None
    if path is None:
        return ref
    return _local_media_base64_ref(ref, path, media_base64_max_bytes)


async def _normalize_media_ref(
    ref: str,
    *,
    media_base64: bool = False,
    media_base64_max_bytes: int,
) -> str:
    """Normalize a media reference without blocking the event loop."""
    if not media_base64 or ref.startswith(("base64://", "data:")):
        return _normalize_media_ref_sync(
            ref,
            media_base64=media_base64,
            media_base64_max_bytes=media_base64_max_bytes,
        )
    return await _run_in_thread(
        _normalize_media_ref_sync,
        ref,
        media_base64=media_base64,
        media_base64_max_bytes=media_base64_max_bytes,
    )


def _normalize_segments(value: object) -> list[dict[str, Any]]:
    """Normalize array or CQ-code messages into native segments."""
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    if not isinstance(value, str):
        return []
    segments: list[dict[str, Any]] = []
    cursor = 0
    for match in re.finditer(r"\[CQ:(?P<type>\w+),(?P<data>[^\]]*)\]", value):
        if match.start() > cursor:
            text = value[cursor : match.start()].strip()
            if text:
                segments.append({"type": "text", "data": {"text": text}})
        data: dict[str, str] = {}
        for item in match.group("data").split(","):
            key, separator, raw = item.partition("=")
            if separator and key:
                data[key] = _unescape_cq_value(raw)
        segments.append({"type": match.group("type"), "data": data})
        cursor = match.end()
    if cursor < len(value):
        text = value[cursor:].strip()
        if text:
            segments.append({"type": "text", "data": {"text": text}})
    if not segments and value.strip():
        segments.append({"type": "text", "data": {"text": value.strip()}})
    return segments


def _reply_message_id(segments: list[dict[str, Any]]) -> str | None:
    """Return the directly quoted OneBot message identifier."""
    for segment in segments:
        if segment.get("type") != "reply":
            continue
        data = segment.get("data", {})
        mapping = data if isinstance(data, Mapping) else {}
        message_id = mapping.get("id")
        if message_id is not None and str(message_id):
            return str(message_id)
    return None


def _segment_types(segments: list[dict[str, Any]]) -> list[str]:
    return [str(segment.get("type") or "") for segment in segments]


def _with_quoted_context(
    quoted: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve the legacy quoted-content marker format."""
    if not quoted:
        return current
    quoted_text = _all_text(quoted)
    current_text = _all_text(current)
    if quoted_text is not None and current_text is not None:
        quoted_content = chr(10).join(quoted_text)
        text = f"[Quoted message]\n{quoted_content}"
        if current_text:
            current_content = chr(10).join(current_text)
            text = f"{text}\n\n[Current message]\n{current_content}"
        return [{"type": "text", "text": text}]
    merged: list[dict[str, Any]] = [
        {"type": "text", "text": "[Quoted message]"},
    ]
    for part in quoted:
        annotation = _quoted_annotation(part)
        if annotation:
            merged.append({"type": "text", "text": annotation})
        merged.append(part)
    if current:
        merged.append({"type": "text", "text": "[Current message]"})
        merged.extend(current)
    return merged


def _all_text(parts: list[dict[str, Any]]) -> list[str] | None:
    """Return text values only when every part is textual."""
    texts: list[str] = []
    for part in parts:
        if part.get("type") != "text":
            return None
        text = str(part.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _quoted_annotation(part: Mapping[str, Any]) -> str | None:
    """Return the existing marker for a quoted media locator."""
    content_type = part.get("type")
    if content_type == "image":
        return "[Quoted image message]"
    if content_type == "audio":
        return "[Quoted voice message]"
    if content_type == "video":
        return "[Quoted video message]"
    if content_type == "file":
        filename = str(part.get("filename") or "file")
        return f"[Quoted file message: {filename}]"
    return None
