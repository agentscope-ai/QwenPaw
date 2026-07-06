# -*- coding: utf-8 -*-
"""Tests for ADBPG memory manager behavior."""
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.agents.memory.adbpg_memory_manager import ADBPGMemoryManager
from qwenpaw.config.config import AutoMemorySearchConfig
from qwenpaw.constant import AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def _memory_config(
    *,
    enabled: bool = True,
    max_results: int = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        auto_memory_search_config=AutoMemorySearchConfig(
            enabled=enabled,
            max_results=max_results,
        ),
    )


@pytest.mark.asyncio
async def test_adbpg_auto_memory_search_injects_tool_messages(tmp_path):
    manager = ADBPGMemoryManager(str(tmp_path), "agent-1")
    manager._client = object()
    manager.get_memory_config = lambda: _memory_config(max_results=2)
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
    manager = ADBPGMemoryManager(str(tmp_path), "agent-1")
    manager._client = object()
    manager.get_memory_config = lambda: _memory_config(enabled=False)
    manager.memory_search = AsyncMock()

    result = await manager.auto_memory_search([_user_msg("hello")])

    assert result is None
    manager.memory_search.assert_not_awaited()
