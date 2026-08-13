from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.agents.memory.powercontext_memory_manager import PowerContextMemoryManager
from qwenpaw.config.config import AutoMemorySearchConfig, PowerContextMemoryConfig


def user(text: str) -> Msg:
    return Msg(name="user", role="user", content=[TextBlock(type="text", text=text)])


@pytest.mark.asyncio
async def test_auto_search_injects_powercontext_result(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = object()
    manager._config = PowerContextMemoryConfig(
        auto_memory_search_config=AutoMemorySearchConfig(enabled=True, max_results=2),
    )
    manager.memory_search = AsyncMock(return_value=ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text="[1] (powercontext, score: 0.90)\nkeep A")],
    ))
    result = await manager.auto_memory_search([user("what did we decide?")])
    assert result["query"] == "what did we decide?"
    assert "keep A" in result["text"]
    manager.memory_search.assert_awaited_once_with("what did we decide?", 2)


@pytest.mark.asyncio
async def test_auto_memory_schedules_structured_write(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    client = SimpleNamespace(remember=AsyncMock())
    manager._client = client
    await manager.auto_memory([user("goal A")])
    await manager.close()
    client.remember.assert_awaited_once()
    assert client.remember.await_args.kwargs["kind"] == "task_state"
    assert "goal A" in client.remember.await_args.kwargs["text"]


def test_unconfigured_backend_is_safe(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    assert manager.list_memory_tools() == [manager.memory_search]
