# -*- coding: utf-8 -*-
"""Public DTOs for attachment lifecycle APIs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ..chats.repo.conversation import AttachmentLifecycle, AttachmentRecord


class AttachmentListItem(BaseModel):
    id: UUID
    agent_id: UUID
    conversation_id: UUID | None
    message_id: UUID | None
    original_name: str
    media_type: str
    size: int
    lifecycle: AttachmentLifecycle
    saved_path: str | None
    saved_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    download_url: str | None
    can_save: bool
    can_move: bool
    can_delete: bool

    @classmethod
    def from_record(cls, record: AttachmentRecord) -> "AttachmentListItem":
        deleted = record.lifecycle == "deleted"
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            conversation_id=record.conversation_id,
            message_id=record.message_id,
            original_name=record.original_name,
            media_type=record.media_type,
            size=record.size,
            lifecycle=record.lifecycle,
            saved_path=record.saved_path,
            saved_at=record.saved_at,
            deleted_at=record.deleted_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            download_url=(
                None if deleted else f"/api/console/attachments/{record.id}"
            ),
            can_save=record.lifecycle == "temporary",
            can_move=record.lifecycle == "saved",
            can_delete=not deleted,
        )
