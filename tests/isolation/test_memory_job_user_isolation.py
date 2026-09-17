# -*- coding: utf-8 -*-
"""记忆任务收件箱事件不得跨用户可见或广播。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


@pytest.mark.asyncio
async def test_private_memory_result_targets_only_current_user() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-a"
    manager.get_memory_config = lambda: SimpleNamespace(
        auto_memory_inbox_push_enabled=True,
    )
    response = SimpleNamespace(
        success=True,
        answer="private result",
        metadata={"modified": True},
    )

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-a"},
    ) as append_event:
        emitted = await manager._append_reme_job_result_to_inbox(
            "auto_memory",
            response=response,
            kwargs={"recipient_user_id": "user-a"},
        )

    assert emitted is True
    assert append_event.await_args.kwargs["recipient_user_id"] == "user-a"


@pytest.mark.asyncio
async def test_public_daily_paper_targets_agent_owner_only() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-a"
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_inbox_push_enabled=True,
    )
    manager._resolve_public_memory_recipient = AsyncMock(
        return_value="owner-a",
    )
    response = SimpleNamespace(success=True, answer="paper", metadata={})

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
        return_value={"id": "event-owner"},
    ) as append_event:
        emitted = await manager._append_reme_job_result_to_inbox(
            "daily_paper",
            response=response,
            kwargs={"memory_scope": "public"},
        )

    assert emitted is True
    assert append_event.await_args.kwargs["recipient_user_id"] == "owner-a"


@pytest.mark.asyncio
async def test_public_job_without_reliable_owner_does_not_broadcast() -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-a"
    manager.get_memory_config = lambda: SimpleNamespace(
        daily_paper_inbox_push_enabled=True,
    )
    manager._resolve_public_memory_recipient = AsyncMock(return_value=None)
    response = SimpleNamespace(success=True, answer="paper", metadata={})

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        new_callable=AsyncMock,
    ) as append_event:
        emitted = await manager._append_reme_job_result_to_inbox(
            "daily_paper",
            response=response,
            kwargs={"memory_scope": "public"},
        )

    assert emitted is False
    append_event.assert_not_awaited()
