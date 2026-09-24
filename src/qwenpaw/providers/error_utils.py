# -*- coding: utf-8 -*-
"""Shared helpers for normalizing provider SDK exceptions."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from typing import Any

from .error_sanitizer import CONNECTION_MESSAGE_SCAN_LIMIT

_STREAMING_ERROR_STATUS_RE = re.compile(
    r"\bStreaming response failed\s*:\s*\[\s*([1-5]\d{2})\s*\]",
    re.IGNORECASE,
)

# The streaming-status fallback is a last-resort heuristic over provider
# error text. That text is remote-controlled and can be arbitrarily
# large, so the regex runs over a bounded prefix; when the marker is
# present it sits at the start of the message.
_STREAMING_STATUS_SCAN_LIMIT = 8_192


def _as_http_status(value: Any) -> int | None:
    """Return *value* as a valid HTTP status code, if possible."""
    if isinstance(value, bool):
        return None
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


def _status_from_streaming_error_message(value: Any) -> int | None:
    """Extract a status from the explicit gateway streaming-error format."""
    if not isinstance(value, str):
        return None
    match = _STREAMING_ERROR_STATUS_RE.search(
        value[:_STREAMING_STATUS_SCAN_LIMIT],
    )
    if match is None:
        return None
    return _as_http_status(match.group(1))


def _iter_streaming_error_messages(exc: Exception) -> Iterator[Any]:
    """Yield message fields that may contain an in-stream HTTP status."""
    yield getattr(exc, "message", None)
    yield str(exc)

    for payload in (
        getattr(exc, "body", None),
        getattr(exc, "details", None),
    ):
        if isinstance(payload, str):
            yield payload
            continue
        if not isinstance(payload, dict):
            continue
        for container in (payload, payload.get("error")):
            if isinstance(container, dict):
                yield container.get("message")


def materialized_error_text(exc: Exception) -> str:
    """Return the error text already held by the exception, bounded.

    Empty when nothing is materialized. Rendering is left to the caller
    because ``str(exc)`` may build the whole body on demand, and this
    runs on the event loop.
    """
    for name in ("message", "body", "details"):
        value = getattr(exc, name, None)
        if isinstance(value, str) and value:
            return value[:CONNECTION_MESSAGE_SCAN_LIMIT]
    response = getattr(exc, "response", None)
    try:
        content = getattr(response, "content", None)
    except Exception:  # pylint: disable=broad-exception-caught
        # A streaming response raises until it is read; an error path
        # must not turn that into another error.
        content = None
    if isinstance(content, (bytes, bytearray)) and content:
        text = bytes(content[:CONNECTION_MESSAGE_SCAN_LIMIT])
        return text.decode("utf-8", errors="replace")
    return ""


def _rendered_error_text(exc: Exception) -> str:
    """Render the exception, bounded, for callers that must have text."""
    rendered = str(exc) or exc.__class__.__name__
    return rendered[:CONNECTION_MESSAGE_SCAN_LIMIT]


def error_body_text(exc: Exception) -> str:
    """Return the provider error text, bounded.

    An attribute that is already materialized wins over ``str(exc)``:
    rendering may build the whole body on demand. Measured on a body of
    32 MB, reading ``body`` costs 0.04 ms where a concatenating
    ``__str__`` costs 50 ms and allocates a second copy.
    """
    return materialized_error_text(exc) or _rendered_error_text(exc)


async def bounded_error_text(exc: Exception) -> str:
    """Return the provider error text without blocking the event loop.

    Same result as :func:`error_body_text`, but a text that only exists
    behind a third-party ``__str__`` is built on a worker thread. That
    call is outside our control and can be arbitrarily expensive, and
    every caller here runs on the event loop.
    """
    text = materialized_error_text(exc)
    if text:
        return text
    return await asyncio.to_thread(_rendered_error_text, exc)


def extract_status_code(exc: Exception) -> int | None:
    """Best-effort HTTP status extraction across supported provider SDKs."""
    for value in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
    ):
        status = _as_http_status(value)
        if status is not None:
            return status

    response = getattr(exc, "response", None)
    for value in (
        getattr(response, "status_code", None),
        getattr(response, "status", None),
    ):
        status = _as_http_status(value)
        if status is not None:
            return status

    for payload in (
        getattr(exc, "body", None),
        getattr(exc, "details", None),
    ):
        if not isinstance(payload, dict):
            continue
        for container in (payload, payload.get("error")):
            if not isinstance(container, dict):
                continue
            for key in ("status_code", "code"):
                status = _as_http_status(container.get(key))
                if status is not None:
                    return status

    # Some OpenAI-compatible gateways return HTTP 200 and report the real
    # failure inside the SSE stream.  The OpenAI SDK raises a base APIError
    # for that event, with no status_code; certain gateways retain the status
    # only in a message such as "Streaming response failed: [503] ...".
    # Keep this fallback deliberately narrow to avoid treating unrelated
    # three-digit numbers in provider messages as HTTP status codes.
    for message in _iter_streaming_error_messages(exc):
        status = _status_from_streaming_error_message(message)
        if status is not None:
            return status

    return None
