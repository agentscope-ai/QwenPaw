# -*- coding: utf-8 -*-
"""把现有 ChatSpec 安全、幂等地补录为 PostgreSQL 会话元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .models import ChatSpec
from .repo.conversation import ConversationRecord


@dataclass(frozen=True, slots=True)
class BackfillReport:
    scanned: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    ambiguous: int = 0


def _resolve_owner(chat: ChatSpec, agent_owner_user_id: UUID | None) -> UUID | None:
    try:
        return UUID(chat.user_id)
    except (TypeError, ValueError):
        if chat.user_id == "default":
            return agent_owner_user_id
        return None


async def register_chat_metadata(
    *,
    chat: ChatSpec,
    agent_id: UUID,
    repository,
) -> None:
    """即时登记一个 UUID 所有者的新会话。"""
    owner_id = UUID(chat.user_id)
    bound = repository.with_user(owner_id)
    conversation_id = UUID(chat.id)
    existing = await bound.get_conversation(conversation_id)
    status = "archived" if chat.archived else "active"
    if existing is None:
        await bound.create_conversation(
            ConversationRecord(
                id=conversation_id,
                agent_id=agent_id,
                owner_user_id=owner_id,
                title=chat.name,
                status=status,
                created_at=chat.created_at,
                updated_at=chat.updated_at,
            )
        )
        return
    if (
        existing.title != chat.name
        or existing.status != status
        or existing.updated_at != chat.updated_at
    ):
        await bound.update_conversation(
            conversation_id,
            title=chat.name,
            status=status,
            updated_at=chat.updated_at,
        )


async def backfill_agent_chats(
    *,
    chats: list[ChatSpec],
    agent_id: UUID,
    agent_owner_user_id: UUID | None,
    repository,
) -> BackfillReport:
    """补录会话元数据，不修改传入 ChatSpec 或其来源文件。"""
    inserted = updated = skipped = ambiguous = 0
    for chat in chats:
        owner_id = _resolve_owner(chat, agent_owner_user_id)
        if owner_id is None:
            ambiguous += 1
            continue
        bound = repository.with_user(owner_id)
        conversation_id = UUID(chat.id)
        existing = await bound.get_conversation(conversation_id)
        status = "archived" if chat.archived else "active"
        if existing is None:
            await bound.create_conversation(
                ConversationRecord(
                    id=conversation_id,
                    agent_id=agent_id,
                    owner_user_id=owner_id,
                    title=chat.name,
                    status=status,
                    created_at=chat.created_at,
                    updated_at=chat.updated_at,
                )
            )
            inserted += 1
            continue
        if (
            existing.title != chat.name
            or existing.status != status
            or existing.updated_at != chat.updated_at
        ):
            await bound.update_conversation(
                conversation_id,
                title=chat.name,
                status=status,
                updated_at=chat.updated_at,
            )
            updated += 1
        else:
            skipped += 1
    return BackfillReport(
        scanned=len(chats),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        ambiguous=ambiguous,
    )
