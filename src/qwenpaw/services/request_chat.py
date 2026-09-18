# -*- coding: utf-8 -*-
"""Reuse a trusted, entry-point chat snapshot within its runtime task."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_request_chat: ContextVar[tuple[Any, Any] | None] = ContextVar(
    "request_chat",
    default=None,
)


@contextmanager
def bind_request_chat(manager: Any, chat: Any) -> Iterator[None]:
    """Child tasks inherit this snapshot; the caller's context is restored."""
    token = _request_chat.set((manager, chat))
    try:
        yield
    finally:
        _request_chat.reset(token)


def get_request_chat(
    manager: Any,
    session_id: str,
    user_id: str | None,
    channel: str,
) -> Any | None:
    """Return only a snapshot belonging to this workspace and chat identity."""
    bound = _request_chat.get()
    if bound is None:
        return None
    owner, chat = bound
    if (
        owner is manager
        and chat.session_id == session_id
        and chat.channel == channel
        and (not user_id or chat.user_id == user_id)
    ):
        return chat
    return None
