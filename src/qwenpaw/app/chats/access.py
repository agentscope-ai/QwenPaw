# -*- coding: utf-8 -*-
"""可信会话身份与会话所有权校验。"""

from __future__ import annotations

from typing import Protocol, TypeVar
from uuid import UUID

from ...access.actor import ActorContext
from .repo.conversation import ConversationAccessRecord, ConversationRecord


class ChatOwner(Protocol):
    """会话所有权校验所需的最小接口。"""

    user_id: str


ChatOwnerT = TypeVar("ChatOwnerT", bound=ChatOwner)


class ChatAccessDeniedError(RuntimeError):
    """当前可信主体不能访问目标会话。"""

    def __init__(self) -> None:
        super().__init__("chat_not_found")


def resolve_chat_user_id(
    *,
    actor: ActorContext,
    requested_user_id: str,
    multi_user: bool,
) -> str:
    """多用户模式只接受认证主体 UUID，Legacy 保留原身份语义。"""
    if not multi_user:
        return requested_user_id
    if actor.user_id is None:
        raise ChatAccessDeniedError()
    return str(actor.user_id)


def require_chat_owner(
    *,
    actor: ActorContext,
    chat: ChatOwnerT,
    multi_user: bool,
    legacy_user_ids: frozenset[str] = frozenset(),
) -> ChatOwnerT:
    """确保多用户请求只能读取或修改自己的会话。"""
    if not multi_user:
        return chat
    if actor.user_id is None or (
        chat.user_id != str(actor.user_id)
        and chat.user_id not in legacy_user_ids
    ):
        raise ChatAccessDeniedError()
    return chat


async def require_chat_access(
    *,
    repository: object | None,
    conversation: ConversationRecord | None,
    user_id: UUID,
    write: bool = False,
    access: ConversationAccessRecord | None = None,
) -> ConversationAccessRecord:
    """返回当前用户访问角色；无权访问统一按会话不存在处理。"""
    if conversation is None:
        raise ChatAccessDeniedError()
    resolved = access
    if resolved is None and conversation.owner_user_id == user_id:
        resolved = ConversationAccessRecord(
            conversation=conversation,
            access_role="owner",
        )
    if resolved is None and repository is not None:
        checker = getattr(repository, "get_conversation_for_user", None)
        if checker is not None:
            resolved = await checker(
                conversation_id=conversation.id,
                user_id=user_id,
            )
    if (
        resolved is None
        or resolved.conversation.id != conversation.id
        or (write and resolved.read_only)
    ):
        raise ChatAccessDeniedError()
    return resolved


async def require_conversation_access(
    *,
    repository: object | None,
    conversation_id: UUID,
    user_id: UUID,
    expected_agent_id: UUID,
    write: bool = False,
) -> ConversationAccessRecord:
    """从 PostgreSQL 事实源加载并校验当前 Agent 下的会话权限。"""
    if repository is None:
        raise ChatAccessDeniedError()
    bound = repository.with_user(user_id)
    checker = getattr(bound, "get_conversation_for_user", None)
    if checker is None:
        raise ChatAccessDeniedError()
    access = await checker(
        conversation_id=conversation_id,
        user_id=user_id,
    )
    if access is None or access.conversation.agent_id != expected_agent_id:
        raise ChatAccessDeniedError()
    return await require_chat_access(
        repository=bound,
        conversation=access.conversation,
        user_id=user_id,
        write=write,
        access=access,
    )
