# -*- coding: utf-8 -*-
"""Unit tests for command handler compaction responses."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


class TextBlock(dict):
    """Lightweight text block stub for tests."""

    def __init__(self, type: str, text: str) -> None:
        super().__init__(type=type, text=text)


class Msg:
    """Lightweight message stub for tests."""

    def __init__(
        self,
        name: str,
        role: str,
        content: list[TextBlock],
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = "2026-03-24T00:00:00Z"

    def get_text_content(self) -> str:
        """Return concatenated text content."""
        return "".join(
            block.get("text", "")
            for block in self.content
            if block.get("type") == "text"
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the message."""
        return {
            "name": self.name,
            "role": self.role,
            "content": list(self.content),
            "metadata": self.metadata,
        }


agentscope_module = types.ModuleType("agentscope")
message_module = types.ModuleType("agentscope.message")
model_module = types.ModuleType("agentscope.model")
config_package = types.ModuleType("copaw.config")
config_module = types.ModuleType("copaw.config.config")
utils_module = types.ModuleType("copaw.agents.utils")
message_module.Msg = Msg
message_module.TextBlock = TextBlock
model_module.ChatModelBase = type("ChatModelBase", (), {})
config_module.load_agent_config = lambda _agent_id: SimpleNamespace()
utils_module.get_copaw_token_counter = lambda _config: None
agentscope_module.message = message_module
agentscope_module.model = model_module
config_package.config = config_module
sys.modules.setdefault("agentscope", agentscope_module)
sys.modules["agentscope.message"] = message_module
sys.modules["agentscope.model"] = model_module
sys.modules["copaw.config"] = config_package
sys.modules["copaw.config.config"] = config_module
sys.modules["copaw.agents.utils"] = utils_module

from copaw.agents.command_handler import CommandHandler


class _FakeMemory:
    """Minimal memory stub for command handler tests."""

    def __init__(self) -> None:
        self._summary = "previous summary"
        self.clear_content = MagicMock()
        self.update_compressed_summary = AsyncMock()

    def get_compressed_summary(self) -> str:
        """Return the current compressed summary."""
        return self._summary


class _FakeMemoryManager:
    """Minimal memory manager stub for command handler tests."""

    def __init__(self, compact_result: str) -> None:
        self.agent_id = "agent-1"
        self.compact_memory = AsyncMock(return_value=compact_result)
        self.add_async_summary_task = MagicMock()


def _build_message(text: str, role: str = "user") -> Msg:
    """Create a simple message for tests."""
    return Msg(
        name=role,
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_process_compact_includes_calculated_token_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compact responses should include message and token calculations."""
    memory = _FakeMemory()
    memory_manager = _FakeMemoryManager(compact_result="short summary")
    handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=memory_manager,
        enable_memory_manager=True,
    )
    counter = MagicMock()
    counter.count = AsyncMock(side_effect=[120, 30])
    agent_config = SimpleNamespace(running=SimpleNamespace())

    monkeypatch.setattr(
        "copaw.agents.command_handler.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        "copaw.agents.command_handler.get_copaw_token_counter",
        lambda _config: counter,
    )

    result = await handler._process_compact(
        messages=[_build_message("first"), _build_message("second", "assistant")],
    )

    text = result.get_text_content() or ""
    assert "- Messages compacted: 2" in text
    assert "- Original tokens: 120" in text
    assert "- Compressed summary tokens: 30" in text
    assert "- Tokens saved: 90" in text
    memory.update_compressed_summary.assert_awaited_once_with("short summary")
    memory.clear_content.assert_called_once_with()


@pytest.mark.asyncio
async def test_process_compact_skips_stats_when_token_count_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compaction should still succeed when stat calculation fails."""
    memory = _FakeMemory()
    memory_manager = _FakeMemoryManager(compact_result="short summary")
    handler = CommandHandler(
        agent_name="Friday",
        memory=memory,
        memory_manager=memory_manager,
        enable_memory_manager=True,
    )
    counter = MagicMock()
    counter.count = AsyncMock(side_effect=RuntimeError("boom"))
    agent_config = SimpleNamespace(running=SimpleNamespace())

    monkeypatch.setattr(
        "copaw.agents.command_handler.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        "copaw.agents.command_handler.get_copaw_token_counter",
        lambda _config: counter,
    )

    result = await handler._process_compact(messages=[_build_message("first")])

    text = result.get_text_content() or ""
    assert "- Messages compacted: 1" in text
    assert "- Original tokens:" not in text
    assert "- Compressed summary tokens:" not in text
    assert "- Tokens saved:" not in text
    assert "**Compressed Summary:**\nshort summary" in text
