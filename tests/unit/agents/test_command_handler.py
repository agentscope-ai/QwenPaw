# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.message import Msg

from copaw.agents.command_handler import CommandHandler
from copaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


class FakeMemory:
    def __init__(self) -> None:
        self.compressed_summary = "previous summary"
        self.cleared = False
        self.updated_summary: str | None = None

    def get_compressed_summary(self) -> str:
        return self.compressed_summary

    async def update_compressed_summary(self, summary: str) -> None:
        self.updated_summary = summary

    def clear_content(self) -> None:
        self.cleared = True

    async def get_memory(self, _prepend_summary: bool = False) -> list[Msg]:
        return []


@pytest.mark.asyncio
async def test_compact_without_instruction_keeps_behavior() -> None:
    memory = FakeMemory()
    memory_manager = SimpleNamespace(
        add_async_summary_task=Mock(),
        compact_memory=AsyncMock(return_value="new compact summary"),
    )
    handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=memory_manager,
    )

    messages = [Msg(name="user", role="user", content="hello")]
    result = await handler._process_compact(messages, "")

    memory_manager.add_async_summary_task.assert_called_once_with(
        messages=messages,
    )
    memory_manager.compact_memory.assert_awaited_once_with(
        messages=messages,
        previous_summary="previous summary",
        extra_instruction="",
    )
    assert memory.updated_summary == "new compact summary"
    assert memory.cleared is True
    assert "Compact Complete!" in result.get_text_content()


@pytest.mark.asyncio
async def test_compact_passes_trimmed_instruction() -> None:
    memory = FakeMemory()
    memory_manager = SimpleNamespace(
        add_async_summary_task=Mock(),
        compact_memory=AsyncMock(return_value="new compact summary"),
    )
    handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=memory_manager,
    )

    messages = [Msg(name="user", role="user", content="hello")]
    instruction = "  keep requirements and decisions only  "
    await handler._process_compact(messages, instruction)

    memory_manager.compact_memory.assert_awaited_once_with(
        messages=messages,
        previous_summary="previous summary",
        extra_instruction="keep requirements and decisions only",
    )


def test_is_conversation_command_accepts_compact_with_args() -> None:
    handler = CommandHandler(
        agent_name="Friday",
        memory=FakeMemory(),
        memory_manager=None,
    )

    assert handler.is_conversation_command("/compact")
    assert handler.is_conversation_command("/compact keep requirements")
    assert not handler.is_conversation_command("/ compact")
    assert not handler.is_conversation_command("/compact_keep requirements")


@pytest.mark.asyncio
async def test_reme_light_compact_memory_passes_extra_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ReMeLightMemoryManager.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager.chat_model = object()
    manager.formatter = object()
    manager._reme = SimpleNamespace(
        compact_memory=AsyncMock(
            return_value={"history_compact": "summary", "is_valid": True},
        ),
    )
    manager._prepare_model_formatter = lambda: None

    fake_agent_config = SimpleNamespace(
        language="zh",
        workspace_dir="/tmp/workspace",
        running=SimpleNamespace(
            max_input_length=32000,
            context_compact=SimpleNamespace(
                memory_compact_ratio=0.75,
                compact_with_thinking_block=True,
            ),
        ),
    )

    monkeypatch.setattr(
        "copaw.agents.memory.reme_light_memory_manager.load_agent_config",
        lambda _agent_id: fake_agent_config,
    )
    monkeypatch.setattr(
        "copaw.agents.memory.reme_light_memory_manager."
        "get_copaw_token_counter",
        lambda _config: "token-counter",
    )

    messages = [Msg(name="user", role="user", content="hello")]
    result = await manager.compact_memory(
        messages=messages,
        previous_summary="previous summary",
        extra_instruction="keep decisions only",
    )

    assert result == "summary"
    manager._reme.compact_memory.assert_awaited_once_with(
        messages=messages,
        as_llm=manager.chat_model,
        as_llm_formatter=manager.formatter,
        as_token_counter="token-counter",
        language="zh",
        max_input_length=32000,
        compact_ratio=0.75,
        previous_summary="previous summary",
        return_dict=True,
        add_thinking_block=True,
        extra_instruction="keep decisions only",
    )
