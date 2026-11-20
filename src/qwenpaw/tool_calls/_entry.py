# -*- coding: utf-8 -*-
"""Single-owner state for one in-flight tool call."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ._context import ToolCallContext
from ._stream import ToolStream


class ToolCallStatus(StrEnum):
    RUNNING = "running"
    OFFLOADED = "offloaded"
    COMPLETED = "completed"


@dataclass
class ToolCallEntry:
    """Single owner of one tool call's runtime state."""

    ctx: ToolCallContext
    stream: ToolStream
    final_response: Any
    status: ToolCallStatus = ToolCallStatus.RUNNING
    background_task: asyncio.Task[None] | None = None
    end_state: str | None = None
    force_cancelled: bool = False


def tool_call_owned_by(entry: ToolCallEntry, user_id) -> bool:
    """Match the server-captured owner, including older approval snapshots."""
    execution = entry.ctx.extra.get("execution_context") or {}
    owner = execution.get("user_id") or execution.get("approval_user_id")
    return bool(user_id and owner and str(owner) == str(user_id))
