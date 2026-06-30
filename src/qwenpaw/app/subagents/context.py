# -*- coding: utf-8 -*-
"""Request-local context used by ``spawn_subagent``.

Tools are registered as plain functions, so they cannot receive a Workspace
dependency through their signature.  A ContextVar keeps that dependency
request-scoped and follows AgentScope's async tool execution tasks naturally.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubagentSpawnContext:
    """Identity and routing information inherited by a child task."""

    manager: Any
    agent_id: str
    session_id: str
    root_session_id: str
    user_id: str
    channel: str
    channel_meta: dict[str, Any] = field(default_factory=dict)
    is_subagent: bool = False


_CURRENT: ContextVar[SubagentSpawnContext | None] = ContextVar(
    "qwenpaw_subagent_spawn_context",
    default=None,
)


def set_subagent_spawn_context(
    value: SubagentSpawnContext,
) -> Token[SubagentSpawnContext | None]:
    """Bind *value* and return a token for deterministic cleanup."""
    return _CURRENT.set(value)


def reset_subagent_spawn_context(
    token: Token[SubagentSpawnContext | None],
) -> None:
    """Restore the ContextVar value that preceded *token*."""
    _CURRENT.reset(token)


def get_subagent_spawn_context() -> SubagentSpawnContext | None:
    """Return the request-local spawn context, if execution is in Runtime."""
    return _CURRENT.get()


__all__ = [
    "SubagentSpawnContext",
    "get_subagent_spawn_context",
    "reset_subagent_spawn_context",
    "set_subagent_spawn_context",
]
