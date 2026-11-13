# -*- coding: utf-8 -*-
"""Per-call runtime handle for tool execution lifecycle."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CancelReason(StrEnum):
    USER = "user"
    TIMEOUT = "timeout"
    AGENT = "agent"
    SHUTDOWN = "shutdown"


def cancellation_reason(error: BaseException | None) -> str | None:
    """Extract the cancel reason attached via ``Task.cancel(reason)``.

    Returns the normalized :class:`CancelReason` value, or ``None`` when
    the error is not a cancellation or carries no known reason. Single
    source of truth so every cancel observer (runtime cancel-save,
    ON_ERROR hooks, stop API) reports the same reason vocabulary.
    """
    if not isinstance(error, asyncio.CancelledError) or not error.args:
        return None
    try:
        return CancelReason(error.args[0]).value
    except ValueError:
        return None


def format_cancel_message(
    tool_name: str,
    cancel_reason: CancelReason | None,
) -> str:
    """Format the result message for a cancelled tool call."""
    if cancel_reason == CancelReason.USER:
        return (
            f"Tool `{tool_name}` was cancelled by the user. "
            "Do not retry this tool call unless the user explicitly asks."
        )
    if cancel_reason == CancelReason.TIMEOUT:
        return (
            f"Tool `{tool_name}` was cancelled due to timeout. "
            "Do not retry with the same timeout unless the user asks; "
            "consider a longer timeout or a different approach."
        )
    reason = cancel_reason.value if cancel_reason else "unknown"
    return (
        f"Tool `{tool_name}` was cancelled (reason={reason}). "
        "Do not retry unless appropriate for the new situation."
    )


class OffloadReason(StrEnum):
    USER = "user"
    TIMEOUT = "timeout"


@dataclass
class ToolCallContext:
    """Per-call runtime handle injected via ContextVar."""

    tool_call_id: str
    tool_name: str
    session_id: str
    agent_id: str
    root_session_id: str

    started_at: float
    offload_deadline: float | None

    cancel_event: asyncio.Event

    kill_deadline: float | None = None
    cancel_reason: CancelReason | None = None

    deadline_changed_event: asyncio.Event = field(
        default_factory=asyncio.Event,
    )

    offload_reason: OffloadReason | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    governance_metadata: dict[str, Any] = field(default_factory=dict)
    root_agent_id: str = ""

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def remaining(self) -> float | None:
        """How much execution time remains before this tool is killed."""
        if self.kill_deadline is None:
            return None
        loop = asyncio.get_running_loop()
        return max(0.0, self.kill_deadline - loop.time())
