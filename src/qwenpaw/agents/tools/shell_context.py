# -*- coding: utf-8 -*-
"""Per-request shell subprocess context."""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Mapping, Optional


_SHELL_CONTEXT: ContextVar[dict[str, str]] = ContextVar(
    "qwenpaw_shell_context",
    default={},
)

_ENV_MAPPING = {
    "user_id": "QWENPAW_USER_ID",
    "session_id": "QWENPAW_SESSION_ID",
    "channel": "QWENPAW_CHANNEL",
    "room_id": "QWENPAW_ROOM_ID",
    "event_id": "QWENPAW_EVENT_ID",
}


def _normalize_shell_context(
    context: Optional[Mapping[str, object]],
) -> dict[str, str]:
    """Keep only non-empty context values that can be exported as env."""
    normalized: dict[str, str] = {}
    for key in _ENV_MAPPING:
        value = (context or {}).get(key)
        if value is None:
            continue
        text = str(value)
        if text:
            normalized[key] = text
    return normalized


def set_shell_command_context(
    context: Optional[Mapping[str, object]],
) -> Token[dict[str, str]]:
    """Set the current request context for shell subprocess env injection."""
    return _SHELL_CONTEXT.set(_normalize_shell_context(context))


def reset_shell_command_context(token: Token[dict[str, str]]) -> None:
    """Restore the previous shell subprocess context."""
    _SHELL_CONTEXT.reset(token)


def get_shell_command_context_env() -> dict[str, str]:
    """Return QwenPaw env vars for the current shell subprocess context."""
    context = _SHELL_CONTEXT.get()
    return {
        env_key: context[context_key]
        for context_key, env_key in _ENV_MAPPING.items()
        if context.get(context_key)
    }
