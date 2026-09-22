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
