# -*- coding: utf-8 -*-
"""Storage records and pagination positions for conversation history."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...schemas import Message


@dataclass(frozen=True)
class TranscriptCursor:
    """Exclusive position before which an older page is read."""

    turn_seq: int
    ordinal: int
    content_before: int = 0
    text_before: int = 0
    snapshot_turn_seq: int | None = field(default=None, compare=False)
    snapshot_event_seq: int | None = field(default=None, compare=False)


@dataclass(frozen=True)
class TranscriptPage:
    """One byte-bounded transcript page in chronological display order."""

    messages: list[Message]
    next_before: TranscriptCursor | None
    has_more: bool
    snapshot_turn_seq: int
    snapshot_event_seq: int = 0


@dataclass(frozen=True)
class TranscriptUserMessage:
    """One lightweight user-message navigation entry."""

    message_id: str
    preview: str
    created_at: str
    anchor: TranscriptCursor
    client_message_id: str | None = None


@dataclass(frozen=True)
class TranscriptUserMessagePage:
    """One stable page of user-message navigation entries."""

    items: list[TranscriptUserMessage]
    next_before: TranscriptCursor | None
    has_more: bool
    snapshot_turn_seq: int
    total: int = 0
    snapshot_event_seq: int = 0


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Persisted agent runtime state for one conversation context."""

    state: dict[str, Any]
    context_generation: int
    current_usage: dict[str, Any] | None


@dataclass(frozen=True)
class PageSelection:
    messages: list[Message]
    oldest_position: TranscriptCursor | None
    has_more: bool
