# -*- coding: utf-8 -*-
"""Helpers for sanitizing process standard streams."""

from __future__ import annotations

import atexit
import os
import sys
from typing import TextIO, cast

_FALLBACK_STREAMS: list[TextIO] = []
_FALLBACK_STREAMS_BY_ENCODING: dict[str, TextIO] = {}
_FALLBACK_CLEANUP_REGISTERED = False


def ensure_standard_streams() -> None:
    """Replace unusable stdout/stderr streams with safe fallbacks."""
    sys.stdout = _ensure_text_stream(sys.stdout)
    sys.stderr = _ensure_text_stream(sys.stderr)


def _ensure_text_stream(stream: TextIO | None) -> TextIO:
    if _is_stream_usable(stream):
        return cast(TextIO, stream)

    return _get_fallback_stream(stream)


def _get_fallback_stream(stream: TextIO | None) -> TextIO:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    fallback = _FALLBACK_STREAMS_BY_ENCODING.get(encoding)
    if _is_stream_usable(fallback):
        return fallback  # type: ignore[return-value]

    fallback = _open_fallback_stream(encoding)
    _FALLBACK_STREAMS_BY_ENCODING[encoding] = fallback
    _FALLBACK_STREAMS.append(fallback)
    _register_fallback_cleanup()
    return fallback


def _is_stream_usable(stream: TextIO | None) -> bool:
    if stream is None:
        return False

    try:
        stream.flush()
    except (AttributeError, OSError, ValueError):
        return False

    try:
        stream.write("")
    except (AttributeError, OSError, ValueError):
        return False

    return True


def _register_fallback_cleanup() -> None:
    global _FALLBACK_CLEANUP_REGISTERED

    if _FALLBACK_CLEANUP_REGISTERED:
        return

    atexit.register(_close_fallback_streams)
    _FALLBACK_CLEANUP_REGISTERED = True


def _close_fallback_streams() -> None:
    while _FALLBACK_STREAMS:
        fallback = _FALLBACK_STREAMS.pop()
        try:
            fallback.close()
        except OSError:
            pass

    _FALLBACK_STREAMS_BY_ENCODING.clear()


def _open_fallback_stream(encoding: str) -> TextIO:
    return open(
        os.devnull,
        "a",
        encoding=encoding,
        buffering=1,
        errors="replace",
    )
