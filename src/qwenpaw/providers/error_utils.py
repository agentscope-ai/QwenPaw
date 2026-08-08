# -*- coding: utf-8 -*-
"""Shared helpers for normalizing provider SDK exceptions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any


_STREAMING_ERROR_STATUS_RE = re.compile(
    r"\bStreaming response failed\s*:\s*\[\s*([1-5]\d{2})\s*\]",
    re.IGNORECASE,
)


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
    match = _STREAMING_ERROR_STATUS_RE.search(value)
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
