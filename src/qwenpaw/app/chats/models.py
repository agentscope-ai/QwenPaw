# -*- coding: utf-8 -*-
"""Chat models with UUID management."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)
from qwenpaw.schemas import Message

from ..channels.schema import DEFAULT_CHANNEL


class SessionSource(str, Enum):
    """Identifies how a session was initiated.

    For future using.
    """

    chat = "chat"
    cron = "cron"
    subagent = "subagent"


class ChatGroupKind(str, Enum):
    """Distinguishes built-in and user-created chat groups."""

    default = "default"
    subagents = "subagents"
    custom = "custom"


DEFAULT_CHAT_GROUP_ID = "default"
SUBAGENT_CHAT_GROUP_ID = "subagents"


class ChatGroup(BaseModel):
    """One persisted group in the Console chat list."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=64)
    order: int = Field(default=0, ge=0)
    kind: ChatGroupKind = Field(default=ChatGroupKind.custom)


def default_chat_groups() -> list[ChatGroup]:
    """Return the two non-deletable groups for a new chat registry."""
    return [
        ChatGroup(
            id=DEFAULT_CHAT_GROUP_ID,
            name="Uncategorized",
            order=0,
            kind=ChatGroupKind.default,
        ),
        ChatGroup(
            id=SUBAGENT_CHAT_GROUP_ID,
            name="Subagents",
            order=1,
            kind=ChatGroupKind.subagents,
        ),
    ]


class ChatSpec(BaseModel):
    """Chat specification with UUID identifier.

    Stored in Redis and can be persisted in JSON file.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Chat UUID identifier",
    )
    name: str = Field(default="New Chat", description="Chat name")
    session_id: str = Field(
        ...,
        description="Session identifier (channel:user_id format)",
    )
    user_id: str = Field(..., description="User identifier")
    channel: str = Field(default=DEFAULT_CHANNEL, description="Channel name")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Chat creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Chat last update timestamp",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )
    status: str = Field(
        default="idle",
        description="Conversation status: idle or running",
    )
    pinned: bool = Field(
        default=False,
        description="Whether the chat is pinned to the top",
    )
    archived_at: Optional[datetime] = Field(
        default=None,
        description="When the chat was archived; None means active",
    )
    source: SessionSource = Field(
        default=SessionSource.chat,
        description="What initiated this session (chat, cron, …)",
    )
    group_id: Optional[str] = Field(
        default=None,
        description="Persisted Console group identifier",
    )
    parent_session_id: Optional[str] = Field(
        default=None,
        description="Immediate parent session for a subagent chat",
    )
    root_session_id: Optional[str] = Field(
        default=None,
        description="Root session for a subagent chat tree",
    )

    @computed_field  # type: ignore[misc]
    @property
    def archived(self) -> bool:
        """Whether this chat is archived (derived from archived_at)."""
        return self.archived_at is not None


class ChatUpdate(BaseModel):
    """Mutable chat fields accepted from external clients.

    Chat identity and system-managed fields stay read-only. The update API is
    currently used for renaming chats, so only externally mutable fields belong
    here.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="Chat name")
    pinned: bool | None = Field(
        default=None,
        description="Whether the chat is pinned to the top",
    )
    group_id: str | None = Field(
        default=None,
        description="Target Console group identifier",
    )


class ChatGroupCreate(BaseModel):
    """Fields accepted when creating a custom chat group."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


class ChatGroupUpdate(BaseModel):
    """Mutable chat-group fields."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


class ChatGroupOrderUpdate(BaseModel):
    """Complete group order submitted by the Console."""

    model_config = ConfigDict(extra="forbid")

    group_ids: list[str] = Field(min_length=2)


class ChatHistory(BaseModel):
    """Complete chat view with spec and state."""

    messages: list[Message] = Field(default_factory=list)
    status: str = Field(
        default="idle",
        description="Conversation status: idle or running",
    )


class BatchFailure(BaseModel):
    """A single failure entry in a batch operation."""

    chat_id: str
    reason: Literal["not_found", "in_progress"]
    message: str


class BatchArchiveResult(BaseModel):
    """Result of a batch archive/unarchive operation."""

    succeeded: list[str] = Field(default_factory=list)
    failed: list[BatchFailure] = Field(default_factory=list)


class ChatsFile(BaseModel):
    """Chat registry file for JSON repository.

    Stores chat_id (UUID) -> session_id mappings for persistence.
    """

    version: int = 1
    chats: list[ChatSpec] = Field(default_factory=list)
    groups: list[ChatGroup] = Field(default_factory=default_chat_groups)

    @model_validator(mode="after")
    def ensure_system_groups(self) -> "ChatsFile":
        """Ensure both non-deletable groups are present."""
        by_id = {group.id: group for group in self.groups}
        defaults = default_chat_groups()
        for group in defaults:
            if group.id not in by_id:
                self.groups.append(group)
        return self
