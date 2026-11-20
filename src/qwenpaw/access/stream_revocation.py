"""Notify active response streams after a local authorization change commits."""

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from uuid import UUID


@dataclass(frozen=True, eq=False)
class _Subscription:
    user_id: UUID
    session_id: UUID
    agent_key: str | None
    plugin_id: str | None
    loop: asyncio.AbstractEventLoop
    close: Callable[[], None]


_listeners: set[_Subscription] = set()
_lock = Lock()


@contextmanager
def listen(
    user_id: UUID,
    session_id: UUID,
    agent_key: str | None,
    close: Callable[[], None],
    *,
    plugin_id: str | None = None,
):
    subscription = _Subscription(
        user_id, session_id, agent_key, plugin_id, asyncio.get_running_loop(), close
    )
    with _lock:
        _listeners.add(subscription)
    try:
        yield
    finally:
        with _lock:
            _listeners.discard(subscription)


def revoke_streams(
    *,
    user_id: UUID | None = None,
    session_id: UUID | None = None,
    agent_key: str | None = None,
    plugin_id: str | None = None,
    keep_user_ids: frozenset[UUID] = frozenset(),
) -> None:
    if user_id is None and session_id is None and agent_key is None and plugin_id is None:
        raise ValueError("Revocation requires a scope")
    current_loop = asyncio.get_running_loop()
    with _lock:
        listeners = tuple(_listeners)
    for item in listeners:
        if (
            (user_id is not None and item.user_id != user_id)
            or (session_id is not None and item.session_id != session_id)
            or (agent_key is not None and item.agent_key != agent_key)
            or (plugin_id is not None and item.plugin_id != plugin_id)
            or item.user_id in keep_user_ids
        ):
            continue
        if item.loop is current_loop:
            item.close()
        elif not item.loop.is_closed():
            item.loop.call_soon_threadsafe(item.close)
