# -*- coding: utf-8 -*-
"""Conversation-scoped routing without mutable shared client headers."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from typing import Iterator

_SESSION: ContextVar[str | None] = ContextVar(f"model_session", default=None)


@contextmanager
def model_session(context: dict, fallback: str) -> Iterator[None]:
    """Isolate stable session identity across concurrent conversations."""
    session = context.get(f"session_id") or fallback
    scope = context.get(f"agent_id", f"")
    tenant = context.get(f"runtime_id", f"")
    value = sha256(f"{tenant}:{scope}:{session}".encode()).hexdigest()
    token = _SESSION.set(value)
    try:
        yield
    finally:
        _SESSION.reset(token)


def session_header(fallback: str) -> str:
    """Use a stable model-instance ID for calls outside an agent turn."""
    return _SESSION.get() or fallback


def with_session_header(
    headers: dict,
    name: str | None,
    fallback: str,
) -> dict:
    """Add the provider's session header to SDK client default headers.

    ``prepare_request`` attaches it to inference calls, but connection
    tests and probes go through ``_client()`` and were left without it:
    OpenCode Go answers those with ``400 MissingSessionID``.  A user value
    wins only when it is non-blank; the endpoint rejects an empty header
    like a missing one.
    """
    if not name:
        return headers
    for key in [key for key in headers if key.lower() == name.lower()]:
        if not str(headers[key]).strip():
            del headers[key]
    if not any(key.lower() == name.lower() for key in headers):
        headers[name] = session_header(fallback)
    return headers
