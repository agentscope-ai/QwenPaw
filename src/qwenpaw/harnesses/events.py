# -*- coding: utf-8 -*-
"""Provider-neutral third-party agent models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HarnessEventKind(str, Enum):
    """Events emitted by every third-party agent adapter."""

    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class HarnessEvent(BaseModel):
    """One normalized provider event."""

    kind: HarnessEventKind
    text: str = ""
    item_id: str = ""
    tool_name: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class HarnessProvider(BaseModel):
    """Static provider metadata combined with runtime status."""

    id: str
    name: str
    available: bool
    coming_soon: bool = False
    installed: bool = False
    authenticated: bool = False
    account: dict[str, Any] | None = None
    error: str | None = None


__all__ = ["HarnessEvent", "HarnessEventKind", "HarnessProvider"]
