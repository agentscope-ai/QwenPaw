# -*- coding: utf-8 -*-
"""聊天运行状态轻量接口回归测试。"""

from types import SimpleNamespace

import pytest

from qwenpaw.app.chats.api import get_chat_status


@pytest.mark.parametrize("status", ["idle", "running"])
async def test_get_chat_status_uses_agent_scoped_task_tracker(status: str) -> None:
    requested: list[str] = []

    class _TaskTracker:
        async def get_status(self, chat_id: str) -> str:
            requested.append(chat_id)
            return status

    response = await get_chat_status(
        "chat-status-id",
        workspace=SimpleNamespace(task_tracker=_TaskTracker()),
    )

    assert response.status == status
    assert requested == ["chat-status-id"]
