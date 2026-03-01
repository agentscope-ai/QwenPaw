# -*- coding: utf-8 -*-
"""Event data model and type constants."""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType:
    """Known event type constants."""

    AGENT_QUERY_START = "agent.query_start"
    AGENT_QUERY_COMPLETE = "agent.query_complete"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"
    CONFIG_CHANGED = "config.changed"
    CRON_TRIGGERED = "cron.triggered"
    CRON_COMPLETED = "cron.completed"
    SESSION_STATUS = "session.status"


# All known event types for validation / filtering.
ALL_EVENT_TYPES = frozenset(
    v
    for k, v in vars(EventType).items()
    if not k.startswith("_") and isinstance(v, str)
)


class Event(BaseModel):
    """A single event emitted on the event bus."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str
    timestamp: float = Field(default_factory=time.time)
    data: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
