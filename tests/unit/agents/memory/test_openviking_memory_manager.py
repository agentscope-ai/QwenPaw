# -*- coding: utf-8 -*-
"""Behavior tests for QwenPaw's OpenViking memory backend."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.openviking_client import OpenVikingIdentity
from qwenpaw.agents.memory.openviking_memory_manager import (
    AUTO_COMMIT_POLICY,
    MAX_MEMORY_SEARCH_RESULTS,
    OpenVikingMemoryManager,
)
from qwenpaw.config.config import AutoMemorySearchConfig


def _msg(role: str, text: str) -> Msg:
    return Msg(
        name=role,
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


def _config(*, policy: str = "auto", budget: int = 64):
    return SimpleNamespace(
        commit_policy=policy,
        retrieval_token_budget=budget,
        auto_memory_search_config=AutoMemorySearchConfig(
            enabled=True,
            max_results=3,
        ),
    )


def _manager(tmp_path, *, policy: str = "auto"):
    manager = OpenVikingMemoryManager(str(tmp_path), "agent-a")
    manager._client = SimpleNamespace(
        resolve_identity=AsyncMock(
            return_value=OpenVikingIdentity("tenant-a", "user-a"),
        ),
        search_context=AsyncMock(return_value={"rendered": "memory"}),
        ensure_session=AsyncMock(),
        add_messages=AsyncMock(),
        commit=AsyncMock(),
        search_memories=AsyncMock(return_value=[]),
    )
    manager._identity = OpenVikingIdentity("tenant-a", "user-a")
    manager._installation_id = "install-a"
    manager._config = _config(policy=policy)
    manager._load_search_config = lambda: (manager._config, 4)
    return manager


def test_session_mapping_is_stable_and_collision_safe(tmp_path):
    manager = _manager(tmp_path)

    first = manager._map_session_id("chat-1")
    assert first == manager._map_session_id("chat-1")
    assert first != manager._map_session_id("chat-2")

    manager._identity = OpenVikingIdentity("tenant-b", "user-a")
    assert first != manager._map_session_id("chat-1")
    assert first.startswith("qwenpaw-")
    assert len(first) == len("qwenpaw-") + 40


@pytest.mark.asyncio
async def test_auto_recall_is_session_scoped_and_locally_bounded(tmp_path):
    manager = _manager(tmp_path)
    manager._client.search_context.return_value = {"rendered": "汉" * 200}

    result = await manager.auto_memory_search(
        [_msg("user", "我的风险偏好是什么？")],
        session_id="chat-1",
    )

    assert result is not None
    assert len(result["text"].encode("utf-8")) <= 64 * 4
    call = manager._client.search_context.await_args.kwargs
    assert call["session_id"] == manager._map_session_id("chat-1")
    assert call["token_budget"] == 64
    assert call["max_results"] == 3


@pytest.mark.asyncio
async def test_completed_turns_exclude_synthetic_recall_and_use_auto_policy(
    tmp_path,
):
    manager = _manager(tmp_path)
    user = _msg("user", "我偏好稳健型产品")
    synthetic = manager._build_auto_memory_search_msg(
        query="偏好",
        max_results=3,
        text="此前信息",
        estimate_divisor=4,
    )
    assistant = _msg("assistant", "已记录")
    second_user = _msg("user", "我还偏好固定利率")
    second_assistant = _msg("assistant", "也已记录")

    await manager.auto_memory(
        [user, synthetic, assistant, second_user, second_assistant],
        session_id="chat-1",
    )

    manager._client.ensure_session.assert_awaited_once_with(
        manager._map_session_id("chat-1"),
        auto_commit_policy=AUTO_COMMIT_POLICY,
    )
    payload = manager._client.add_messages.await_args.args[1]
    assert [item["content"] for item in payload] == [
        "我偏好稳健型产品",
        "已记录",
        "我还偏好固定利率",
        "也已记录",
    ]
    assert [item["message_kind"] for item in payload] == [
        "user_query",
        "assistant_step",
        "user_query",
        "assistant_step",
    ]
    assert [item["turn_id"] for item in payload] == [
        user.id,
        user.id,
        second_user.id,
        second_user.id,
    ]
    manager._client.commit.assert_not_awaited()

    # The manager records source message IDs only after a successful write,
    # so a middleware replay cannot persist the same turn twice.
    await manager.auto_memory(
        [user, assistant, second_user, second_assistant],
        session_id="chat-1",
    )
    assert manager._client.add_messages.await_count == 1


@pytest.mark.asyncio
async def test_explicit_search_caps_result_count(tmp_path):
    manager = _manager(tmp_path)

    await manager.memory_search("preference", max_results=10_000)

    manager._client.search_memories.assert_awaited_once_with(
        query="preference",
        max_results=MAX_MEMORY_SEARCH_RESULTS,
    )


@pytest.mark.asyncio
async def test_every_turn_policy_disables_auto_commit_and_commits(tmp_path):
    manager = _manager(tmp_path, policy="every_turn")

    await manager.auto_memory(
        [_msg("user", "hello"), _msg("assistant", "hi")],
        session_id="chat-1",
    )

    manager._client.ensure_session.assert_awaited_once_with(
        manager._map_session_id("chat-1"),
        auto_commit_policy=None,
    )
    manager._client.commit.assert_awaited_once_with(
        manager._map_session_id("chat-1"),
    )


@pytest.mark.asyncio
async def test_startup_outage_identity_is_retried_before_first_operation(
    tmp_path,
):
    manager = _manager(tmp_path)
    manager._identity = OpenVikingIdentity("unknown", "unknown")

    await manager.auto_memory_search(
        [_msg("user", "remember me")],
        session_id="chat-1",
    )

    manager._client.resolve_identity.assert_awaited_once()
    assert manager._identity.namespace == "tenant-a/user-a"


def test_utf8_clipping_never_exceeds_byte_limit():
    for limit in range(1, 100):
        clipped = OpenVikingMemoryManager._clip_utf8("汉字" * 100, limit)
        assert len(clipped.encode("utf-8")) <= limit
