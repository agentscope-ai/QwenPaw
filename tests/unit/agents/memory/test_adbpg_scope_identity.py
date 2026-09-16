# -*- coding: utf-8 -*-
"""ADBPG 请求必须绑定真实的用户、Agent 和运行身份。"""

from __future__ import annotations

import asyncio

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.adbpg_client import ADBPGConfig, ADBPGMemoryClient
from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager
from qwenpaw.memory_scope.models import MemoryScopeDenied


class _RecordingClient:
    def __init__(self) -> None:
        self.add_payloads: list[dict] = []
        self.search_payloads: list[dict] = []

    async def add_memory(self, **payload) -> None:
        self.add_payloads.append(payload)

    async def search_memory(self, **payload) -> list[dict]:
        self.search_payloads.append(payload)
        return []


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_request_views_keep_two_users_add_and_search_identity_separate(
    tmp_path,
) -> None:
    """若视图复用 shared 或串用另一用户身份，本测试必须失败。"""
    manager = ADBPGMemoryManager(str(tmp_path), "agent-a")
    client = _RecordingClient()
    manager._client = client  # pylint: disable=protected-access

    user_a = manager.for_request(
        {"user_id": "user-a", "agent_id": "agent-a", "run_id": "run-a"},
    )
    user_b = manager.for_request(
        {"user_id": "user-b", "agent_id": "agent-a", "run_id": "run-b"},
    )

    await user_a.auto_memory([_user_msg("A 的记忆")])
    await user_b.auto_memory([_user_msg("B 的记忆")])
    await asyncio.gather(*manager._pending_add_tasks)  # pylint: disable=protected-access
    await user_a.memory_search("A")
    await user_b.memory_search("B")

    assert [
        (item["user_id"], item["agent_id"], item["run_id"])
        for item in client.add_payloads
    ] == [
        ("user-a", "agent-a", "run-a"),
        ("user-b", "agent-a", "run-b"),
    ]
    assert [
        (item["user_id"], item["agent_id"], item["run_id"])
        for item in client.search_payloads
    ] == [
        ("user-a", "agent-a", "run-a"),
        ("user-b", "agent-a", "run-b"),
    ]


def test_request_view_rejects_missing_authenticated_user(tmp_path) -> None:
    """删除可信用户校验时，本测试必须失败。"""
    manager = ADBPGMemoryManager(str(tmp_path), "agent-a")

    with pytest.raises(MemoryScopeDenied, match="authenticated_user_required"):
        manager.for_request(
            {"agent_id": "agent-a", "session_id": "session-a"},
        )


def test_request_view_uses_session_as_run_id_when_run_id_is_absent(
    tmp_path,
) -> None:
    """会话请求没有独立 run_id 时仍必须携带可审计运行标识。"""
    manager = ADBPGMemoryManager(str(tmp_path), "agent-a")

    view = manager.for_request(
        {
            "user_id": "user-a",
            "agent_id": "agent-a",
            "session_id": "session-a",
        },
    )

    assert view.run_id == "session-a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "agent_id", "run_id", "reason"),
    [
        ("", "agent-a", "run-a", "authenticated_user_required"),
        ("shared", "agent-a", "run-a", "shared_identity_denied"),
        ("user-a", "", "run-a", "agent_id_required"),
        ("user-a", "agent-a", "", "run_id_required"),
    ],
)
async def test_client_rejects_incomplete_or_shared_private_identity(
    user_id: str,
    agent_id: str,
    run_id: str,
    reason: str,
) -> None:
    """客户端若允许不完整或 shared 私有身份，本测试必须失败。"""
    client = ADBPGMemoryClient(
        ADBPGConfig(
            rest_base_url="https://adbpg.test",
            rest_api_key="test-only-key",
        ),
    )
    try:
        with pytest.raises(MemoryScopeDenied, match=reason):
            await client.search_memory(
                query="memory",
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
            )
    finally:
        await client.close()
