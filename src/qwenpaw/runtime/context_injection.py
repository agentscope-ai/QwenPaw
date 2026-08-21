# -*- coding: utf-8 -*-
"""Helpers for request-local context messages.

AgentScope currently requires ``reply_stream`` inputs to use the user or
assistant role. QwenPaw therefore wraps dynamic system context in a tagged
user-role message for the current model call. These messages are runtime
inputs, not conversation transcript, and must never remain in session state.
"""

from __future__ import annotations

from typing import Any

from ..constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    RUNTIME_CONTEXT_MESSAGE_TAG,
)


def _field(message: Any, name: str) -> Any:
    if isinstance(message, dict):
        return message.get(name)
    return getattr(message, name, None)


def is_runtime_context_message(
    message: Any,
    *,
    include_legacy: bool = False,
) -> bool:
    """Return whether a message is model-only dynamic context.

    ``include_legacy`` recognizes snapshots written by QwenPaw v2.1.0 before
    the explicit metadata tag existed. In this codebase, ``name=system`` plus
    ``role=user`` was created only by the runtime context-injection path.
    """
    metadata = _field(message, "metadata")
    if (
        isinstance(metadata, dict)
        and metadata.get(QWENPAW_MESSAGE_TAG_KEY) == RUNTIME_CONTEXT_MESSAGE_TAG
    ):
        return True
    return bool(
        include_legacy
        and _field(message, "name") == "system"
        and _field(message, "role") == "user"
    )


def remove_runtime_context_from_state(state: dict) -> int:
    """Remove tagged and v2.1.0 legacy context messages from agent state."""
    if not isinstance(state, dict):
        return 0

    containers: list[dict] = []
    nested = state.get("state")
    if isinstance(nested, dict):
        containers.append(nested)
    containers.append(state)

    removed = 0
    seen_contexts: set[int] = set()
    for container in containers:
        context = container.get("context")
        if not isinstance(context, list) or id(context) in seen_contexts:
            continue
        seen_contexts.add(id(context))
        kept = [
            message
            for message in context
            if not is_runtime_context_message(message, include_legacy=True)
        ]
        removed += len(context) - len(kept)
        context[:] = kept
    return removed


__all__ = [
    "is_runtime_context_message",
    "remove_runtime_context_from_state",
]
