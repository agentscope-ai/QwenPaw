# -*- coding: utf-8 -*-
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.agents.memory.powercontext_memory_manager import (
    PowerContextMemoryManager,
)
from qwenpaw.config.config import (
    AutoMemorySearchConfig,
    PowerContextMemoryConfig,
)


def user(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_auto_search_injects_powercontext_result(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = object()
    manager._config = PowerContextMemoryConfig(
        auto_memory_search_config=AutoMemorySearchConfig(
            enabled=True,
            max_results=2,
        ),
    )
    manager.memory_search = AsyncMock(
        return_value=ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text="[1] (powercontext, score: 0.90)\nkeep A",
                ),
            ],
        ),
    )
    result = await manager.auto_memory_search([user("what did we decide?")])
    assert result["query"] == "what did we decide?"
    assert "keep A" in result["text"]
    manager.memory_search.assert_awaited_once_with("what did we decide?", 2)


@pytest.mark.asyncio
async def test_auto_search_skips_backend_error(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = object()
    manager._config = PowerContextMemoryConfig()
    manager.memory_search = AsyncMock(
        return_value=ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(type="text", text="PowerContext unavailable")],
        ),
    )
    assert (
        await manager.auto_memory_search([user("what did we decide?")]) is None
    )


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


@pytest.mark.asyncio
async def test_auto_memory_bounds_multibyte_text_and_excludes_search(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    client = SimpleNamespace(remember=AsyncMock())
    manager._client = client
    synthetic_search = manager._build_auto_memory_search_msg(
        query="prior decision",
        max_results=1,
        text="recalled-memory-must-not-be-persisted",
    )
    await manager.auto_memory([user("你" * 3000), synthetic_search])
    await manager.close()
    payload = client.remember.await_args.kwargs["text"]
    assert len(payload.encode("utf-8")) <= 8000
    assert "recalled-memory-must-not-be-persisted" not in payload


def test_unconfigured_backend_is_safe(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    assert {tool.__name__ for tool in manager.list_memory_tools()} == {
        "memory_search",
        "memory_remember",
    }


@pytest.mark.asyncio
async def test_memory_search_reports_unconfigured_backend(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    result = await manager.memory_search("what did we decide?")
    assert result.state == ToolResultState.ERROR
    assert "not configured" in result.content[0].text


@pytest.mark.asyncio
async def test_memory_search_keeps_powercontext_citation(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = SimpleNamespace(
        search=AsyncMock(
            return_value=[
                {
                    "text": "decision",
                    "score": 0.9,
                    "citation": {
                        "memory_ref": {
                            "family": "memory",
                            "artifact_id": "memory",
                            "revision": 2,
                        },
                        "entry_id": "entry-1",
                        "entry_version_id": "version-1",
                    },
                },
            ],
        ),
    )
    result = await manager.memory_search("what did we decide?")
    text = result.content[0].text
    assert "entry_id: entry-1" in text
    assert "entry_version_id: version-1" in text
    assert "family: memory" in text
    assert "artifact_id: memory" in text
    assert "revision: 2" in text


@pytest.mark.asyncio
async def test_memory_search_returns_error_when_backend_fails(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = SimpleNamespace(
        search=AsyncMock(side_effect=RuntimeError("offline")),
    )
    result = await manager.memory_search("what did we decide?")
    assert result.state == ToolResultState.ERROR
    assert "offline" in result.content[0].text


@pytest.mark.asyncio
async def test_memory_remember_is_explicit_and_registered(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    manager._client = SimpleNamespace(
        remember=AsyncMock(return_value={"remembered": True}),
    )
    assert manager.memory_remember in manager.list_memory_tools()
    result = await manager.memory_remember("decision", "use PowerContext")
    assert result.state == ToolResultState.SUCCESS
    manager._client.remember.assert_awaited_once_with(
        kind="decision",
        text="use PowerContext",
    )


@pytest.mark.asyncio
async def test_memory_remember_bounds_multibyte_text(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    client = SimpleNamespace(
        remember=AsyncMock(return_value={"remembered": True}),
    )
    manager._client = client
    result = await manager.memory_remember("fact", "你" * 3000)
    assert result.state == ToolResultState.SUCCESS
    payload = client.remember.await_args.kwargs["text"]
    assert len(payload.encode("utf-8")) <= 8000


@pytest.mark.asyncio
async def test_memory_remember_reports_backend_failure(tmp_path):
    manager = PowerContextMemoryManager(str(tmp_path), "agent-1")
    client = SimpleNamespace(
        remember=AsyncMock(side_effect=RuntimeError("offline")),
    )
    manager._client = client
    result = await manager.memory_remember("fact", "important")
    assert result.state == ToolResultState.ERROR
    assert "offline" in result.content[0].text
