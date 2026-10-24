# -*- coding: utf-8 -*-
"""Versioned, persistence-safe models for plugin recordings."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class RecordingState(StrEnum):
    """Python-owned durable recording lifecycle."""

    STARTING = "starting"
    RECORDING = "recording"
    PAUSED = "paused"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    DELETED = "deleted"


class RecordingEvent(BaseModel):
    """One event after the Python privacy guard has accepted it."""

    model_config = ConfigDict(extra="forbid")

    event_schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    seq: int = Field(ge=0)
    t_monotonic_ms: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=64)
    app: dict[str, Any] | None = None
    window: dict[str, Any] | None = None
    target: dict[str, Any] | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    enrichment: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    redaction: dict[str, Any] = Field(default_factory=dict)

class RecordingSession(BaseModel):
    """Durable session metadata stored in ``session.json``."""

    model_config = ConfigDict(extra="forbid")

    session_schema_version: Literal[1] = 1
    recording_id: UUID
    workspace_id: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=256)
    state: RecordingState
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    event_count: int = Field(default=0, ge=0)
    dropped_event_count: int = Field(default=0, ge=0)
    last_seq: int | None = Field(default=None, ge=0)
    failure_code: str | None = Field(default=None, max_length=128)


class RecordingSummary(BaseModel):
    """Small final summary; semantic generation is a later phase."""

    model_config = ConfigDict(extra="forbid")

    summary_schema_version: Literal[1] = 1
    recording_id: UUID
    state: RecordingState
    event_count: int = Field(ge=0)
    dropped_event_count: int = Field(ge=0)
    first_seq: int | None = Field(default=None, ge=0)
    last_seq: int | None = Field(default=None, ge=0)


class RecordingDescriptor(BaseModel):
    """Low-sensitivity recording metadata returned by the application API."""

    model_config = ConfigDict(extra="forbid")

    recording_id: UUID
    agent_id: str
    state: RecordingState
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    event_count: int = Field(ge=0)
    dropped_event_count: int = Field(ge=0)
    failure_code: str | None = None

    @classmethod
    def from_session(cls, session: RecordingSession) -> "RecordingDescriptor":
        """Remove storage and user identity details from a session."""
        return cls(
            recording_id=session.recording_id,
            agent_id=session.agent_id,
            state=session.state,
            created_at=session.created_at,
            updated_at=session.updated_at,
            completed_at=session.completed_at,
            event_count=session.event_count,
            dropped_event_count=session.dropped_event_count,
            failure_code=session.failure_code,
        )


class RecordingStatus(BaseModel):
    """Versioned product-facing snapshot of the global recorder."""

    model_config = ConfigDict(extra="forbid")

    api_schema_version: Literal[1] = 1
    available: bool
    input_monitoring: Literal["granted", "required", "unavailable"]
    accessibility: Literal["granted", "required", "unavailable"]
    state: Literal[
        "idle",
        "starting",
        "recording",
        "paused",
        "finalizing",
        "completed",
        "failed",
        "interrupted",
        "deleted",
    ]
    recording: RecordingDescriptor | None = None
    last_recording: RecordingDescriptor | None = None


__all__ = [
    "RecordingEvent",
    "RecordingDescriptor",
    "RecordingSession",
    "RecordingState",
    "RecordingStatus",
    "RecordingSummary",
    "utc_now",
]
