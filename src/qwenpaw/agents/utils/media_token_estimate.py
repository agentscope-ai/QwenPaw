# -*- coding: utf-8 -*-
"""Context-ring token estimates for inlined media payloads.

Local heuristic only — not a billing formula. Never treats base64 bytes
as text tokens (``len(data) // 4``).
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import re
import wave

EMPTY_MEDIA_TOKENS = 10
IMAGE_FALLBACK_TOKENS = 2048
AUDIO_FALLBACK_TOKENS = 2048
AUDIO_TOKENS_PER_SECOND = 10
AUDIO_MAX_TOKENS = 100_000
VIDEO_FALLBACK_TOKENS = 4096
FILE_FALLBACK_TOKENS = 2048
# Image geometry uses Qwen-VL 28px patches, not OpenAI 32px.
IMAGE_PATCH_SIZE = 28
IMAGE_COST_SAFETY_MARGIN = 1.10
IMAGE_MAX_TOKENS = 16_384

_CACHE_MAX = 128
_cache: dict[tuple, int] = {}

_DATA_URL_RE = re.compile(
    r"data:([^;,]+)(?:;[^,]*)?;base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)


def estimate_inline_media_tokens(media_type: str, data: str) -> int:
    """Estimate context tokens for one inlined base64 payload."""
    if not data:
        return EMPTY_MEDIA_TOKENS
    key = _cache_key(media_type, data)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    value = _estimate_uncached(media_type, data)
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = value
    return value


def estimate_data_url_tokens(url: str) -> int | None:
    """Estimate tokens if ``url`` is a whole-string base64 data URL."""
    stripped = (url or "").strip()
    if not stripped.lower().startswith("data:"):
        return None
    match = _DATA_URL_RE.fullmatch(stripped)
    if match is None:
        return None
    return estimate_inline_media_tokens(match.group(1), match.group(2))


def iter_data_url_spans(
    text: str,
) -> list[tuple[int, int, str, str]]:
    """Return ``(start, end, media_type, payload)`` for data URLs in text."""
    lowered = text.lower()
    if "data:" not in lowered or ";base64," not in lowered:
        return []
    return [
        (m.start(), m.end(), m.group(1), m.group(2))
        for m in _DATA_URL_RE.finditer(text)
    ]


def _cache_key(media_type: str, data: str) -> tuple:
    digest = hashlib.sha256()
    digest.update(data[:4096].encode("ascii", errors="ignore"))
    if len(data) > 256:
        digest.update(data[-256:].encode("ascii", errors="ignore"))
    return (media_type, len(data), digest.digest())


def _kind(media_type: str) -> str:
    mt = (media_type or "").lower().strip()
    if mt.startswith("image/"):
        return "image"
    if mt.startswith("audio/"):
        return "audio"
    if mt.startswith("video/"):
        return "video"
    if mt.startswith("text/") or mt in (
        "application/json",
        "application/xml",
        "application/javascript",
    ):
        return "text"
    return "file"


def _fallback(kind: str) -> int:
    if kind == "image":
        return IMAGE_FALLBACK_TOKENS
    if kind == "audio":
        return AUDIO_FALLBACK_TOKENS
    if kind == "video":
        return VIDEO_FALLBACK_TOKENS
    return FILE_FALLBACK_TOKENS


def _b64decode(data: str) -> bytes:
    compact = "".join(data.split())
    pad = (-len(compact)) % 4
    if pad:
        compact += "=" * pad
    return base64.b64decode(compact, validate=False)


def _text_tokens(raw: bytes) -> int:
    try:
        text = raw.decode("utf-8")
    except Exception:
        return FILE_FALLBACK_TOKENS
    if not text:
        return 0
    return int(len(raw) / 4 + 0.5)


def _audio_tokens(raw: bytes) -> int:
    # WAV headers only; other audio containers use AUDIO_FALLBACK_TOKENS.
    duration = _wav_duration(raw)
    if duration is None or duration <= 0:
        return AUDIO_FALLBACK_TOKENS
    return min(
        AUDIO_MAX_TOKENS,
        max(1, math.ceil(duration * AUDIO_TOKENS_PER_SECOND)),
    )


def _estimate_uncached(media_type: str, data: str) -> int:
    kind = _kind(media_type)
    try:
        raw = _b64decode(data)
    except Exception:
        return _fallback(kind)
    if kind == "text":
        return _text_tokens(raw)
    if kind == "image":
        return _image_tokens(raw)
    if kind == "audio":
        return _audio_tokens(raw)
    return _fallback(kind)


def _image_tokens(raw: bytes) -> int:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
    except Exception:
        return IMAGE_FALLBACK_TOKENS
    if width <= 0 or height <= 0:
        return IMAGE_FALLBACK_TOKENS
    patches = math.ceil(width / IMAGE_PATCH_SIZE) * math.ceil(
        height / IMAGE_PATCH_SIZE,
    )
    return min(
        IMAGE_MAX_TOKENS,
        max(1, math.ceil(patches * IMAGE_COST_SAFETY_MARGIN)),
    )


def _wav_duration(raw: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(raw), "rb") as handle:
            rate = handle.getframerate()
            if rate <= 0:
                return None
            return handle.getnframes() / float(rate)
    except Exception:
        return None
