# -*- coding: utf-8 -*-
"""旧会话文件必须幂等回填历史只读关系。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.agent_history_backfill import backfill_agent_history_access
from qwenpaw.app.chats.models import ChatSpec


@pytest.mark.asyncio
async def test_backfill_skips_non_user_ids_and_records_existing_chats() -> None:
    user_id = uuid4()
    created_at = datetime(2026, 8, 22, tzinfo=UTC)
    chats = [
        ChatSpec(
            session_id="console:member",
            user_id=str(user_id),
            created_at=created_at,
        ),
        ChatSpec(session_id="console:legacy", user_id="default"),
    ]

    class Manager:
        async def get_agent(self, agent_key: str):
            assert agent_key == "agent-a"
            return SimpleNamespace(
                chat_manager=SimpleNamespace(
                    list_chats=lambda archived=None: _async_value(chats)
                )
            )

    class Repository:
        def __init__(self) -> None:
            self.rows = []

        async def record_chat_created(self, **kwargs) -> None:
            self.rows.append(kwargs)

    repository = Repository()

    count = await backfill_agent_history_access(
        workspace_manager=Manager(),
        agent_keys=["agent-a"],
        repository=repository,
    )

    assert count == 1
    assert repository.rows == [
        {
            "agent_key": "agent-a",
            "user_id": user_id,
            "created_at": created_at,
        }
    ]


async def _async_value(value):
    return value
