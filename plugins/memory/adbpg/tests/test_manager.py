# -*- coding: utf-8 -*-
"""Tests for ADBPG memory manager behavior."""
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from plugins.memory.adbpg.backend.config import ADBPGMemoryConfig
from plugins.memory.adbpg.backend.manager import ADBPGMemoryManager
from qwenpaw.memory import MemoryBackendContext
from qwenpaw.constant import AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY


def _manager(
    tmp_path,
    agent_id: str = "agent-1",
    config: ADBPGMemoryConfig | None = None,
) -> ADBPGMemoryManager:
    return ADBPGMemoryManager(
        MemoryBackendContext(
            agent_id=agent_id,
            working_dir=tmp_path,
            host_working_dir=tmp_path,
            backend_config=(config or ADBPGMemoryConfig()).model_dump(),
        ),
    )


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_adbpg_auto_memory_search_injects_tool_messages(tmp_path):
    manager = _manager(
        tmp_path,
        config=ADBPGMemoryConfig(
            auto_memory_search_config={"enabled": True, "max_results": 2},
        ),
    )
    manager._client = object()
    manager.memory_search = AsyncMock(
        return_value=ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="[1] (adbpg, score: 0.88)\n喜欢猫",
                ),
            ],
        ),
    )

    result = await manager.auto_memory_search(
        [_user_msg("我喜欢什么动物")],
        agent_name="Agent One",
    )

    assert result is not None
    assert result["query"] == "我喜欢什么动物"
    assert result["text"] == "[1] (adbpg, score: 0.88)\n喜欢猫"
    assert len(result["msg"]) == 2

    memory_msg = result["msg"][1]
    assert memory_msg.role == "assistant"
    assert memory_msg.name == "memory_search"
    assert memory_msg.id
    assert memory_msg.created_at
    assert memory_msg.metadata[AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY] == [
        block.id for block in memory_msg.content
    ]
    assert memory_msg.content[2].name == "memory_search"
    assert '"max_results": 2' in memory_msg.content[2].input
    assert memory_msg.content[3].name == "memory_search"
    assert memory_msg.content[3].output[0].text.endswith("喜欢猫")
    manager.memory_search.assert_awaited_once_with(
        query="我喜欢什么动物",
        max_results=2,
    )


@pytest.mark.asyncio
async def test_adbpg_auto_memory_search_respects_disabled_config(tmp_path):
    manager = _manager(
        tmp_path,
        config=ADBPGMemoryConfig(
            auto_memory_search_config={"enabled": False},
        ),
    )
    manager._client = object()
    manager.memory_search = AsyncMock()

    result = await manager.auto_memory_search([_user_msg("hello")])

    assert result is None
    manager.memory_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_adbpg_auto_memory_waits_for_backend_processing(tmp_path):
    manager = _manager(tmp_path)
    client = SimpleNamespace(add_memory=AsyncMock())
    manager._client = client
    message = _user_msg("remember this")

    result = await manager.auto_memory([message])

    assert (
        result == "Processed 1 user message(s) to ADBPG for agent 'agent-1'."
    )
    client.add_memory.assert_awaited_once()
    assert message.id in manager._persisted_msg_ids


@pytest.mark.asyncio
async def test_adbpg_auto_memory_tracks_each_success_before_later_failure(
    tmp_path,
):
    manager = _manager(tmp_path)
    client = SimpleNamespace(
        add_memory=AsyncMock(
            side_effect=[None, RuntimeError("second write failed")],
        ),
    )
    manager._client = client
    first = _user_msg("first")
    second = _user_msg("second")

    with pytest.raises(RuntimeError, match="second write failed"):
        await manager.auto_memory([first, second])

    assert first.id in manager._persisted_msg_ids
    assert second.id not in manager._persisted_msg_ids
