# -*- coding: utf-8 -*-
"""从现有会话文件回填 Agent 历史只读访问关系。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class AgentHistoryRepository(Protocol):
    async def record_chat_created(self, **kwargs) -> None: ...


async def backfill_agent_history_access(
    *,
    workspace_manager,
    agent_keys: list[str],
    repository: AgentHistoryRepository,
) -> int:
    """幂等扫描已启动 Agent 的 chats.json，并记录有效平台用户。"""
    recorded = 0
    for agent_key in agent_keys:
        workspace = await workspace_manager.get_agent(agent_key)
        if workspace is None:
            continue
        chats = await workspace.chat_manager.list_chats(archived=None)
        for chat in chats:
            try:
                user_id = UUID(chat.user_id)
            except (TypeError, ValueError):
                continue
            await repository.record_chat_created(
                agent_key=agent_key,
                user_id=user_id,
                created_at=chat.created_at,
            )
            recorded += 1
    return recorded
