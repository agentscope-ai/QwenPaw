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
    deadline: float | None

    cancel_event: asyncio.Event
    cancel_reason: CancelReason | None = None

    deadline_changed_event: asyncio.Event = field(
        default_factory=asyncio.Event,
    )

    offload_reason: OffloadReason | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    governance_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        loop = asyncio.get_running_loop()
        return max(0.0, self.deadline - loop.time())
