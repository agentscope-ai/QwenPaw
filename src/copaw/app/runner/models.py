# -*- coding: utf-8 -*-
"""Chat models for runner with UUID management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, Field
from agentscope_runtime.engine.schemas.agent_schemas import Message

from ..channels.schema import DEFAULT_CHANNEL


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


class ChatUpdate(BaseModel):
    """Partial chat update payload.

    Allows clients to update only the fields they intend to change, which
    avoids stale full-record overwrites from UI/CLI callers.
    """

    id: str | None = Field(default=None, description="Chat UUID identifier")
    name: str | None = Field(default=None, description="Chat name")
    session_id: str | None = Field(default=None, description="Session ID")
    user_id: str | None = Field(default=None, description="User ID")
    channel: str | None = Field(default=None, description="Channel name")
    created_at: datetime | None = Field(
        default=None,
        description="Chat creation timestamp",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Chat last update timestamp",
    )
    meta: Dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata",
    )
    status: str | None = Field(
        default=None,
        description="Conversation status: idle or running",
    )


class ChatHistory(BaseModel):
    """Complete chat view with spec and state."""

    messages: list[Message] = Field(default_factory=list)
    status: str = Field(
        default="idle",
        description="Conversation status: idle or running",
    )


class ChatsFile(BaseModel):
    """Chat registry file for JSON repository.

    Stores chat_id (UUID) -> session_id mappings for persistence.
    """

    version: int = 1
    chats: list[ChatSpec] = Field(default_factory=list)
