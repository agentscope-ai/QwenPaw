# -*- coding: utf-8 -*-
# pylint: disable=too-few-public-methods
"""Unit tests for fallback-aware LightContextManager compaction."""

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from qwenpaw.agents.context.light_context_manager import LightContextManager


class DummyTokenCounter:
    """Simple token counter for context-manager tests."""

    async def count(self, text: str = "", messages: list | None = None) -> int:
        if text:
            return max(1, len(text) // 8)
        if messages:
            return sum(max(1, len(str(m.content)) // 8) for m in messages)
        return 0


class DummyMemory:
    """Minimal memory stub for compaction tests."""

    def __init__(self, messages: list[Msg], summary: str = "") -> None:
        self._messages = messages
        self._summary = summary
        self.marked: list[Msg] = []
        self.updated_summary: str | None = None

    def get_compressed_summary(self) -> str:
        return self._summary

    async def get_memory(self, prepend_summary: bool = False) -> list[Msg]:
        assert prepend_summary is False
        return self._messages

    async def mark_messages_compressed(self, messages: list[Msg]) -> int:
        self.marked = list(messages)
        return len(messages)

    async def update_compressed_summary(self, summary: str) -> None:
        self.updated_summary = summary


class DummyMemoryManager:
    """Memory manager stub used by pre_reasoning."""

    def __init__(self) -> None:
        self.summarize_calls: list[list[Msg]] = []

    def add_summarize_task(self, messages: list[Msg]) -> None:
        self.summarize_calls.append(list(messages))


class DummyAgent:
    """Agent stub exposing the fields used by LightContextManager."""

    def __init__(self, memory: DummyMemory) -> None:
        self.name = "QwenPaw"
        self.memory = memory
        self.memory_manager = DummyMemoryManager()
        self.sys_prompt = "System prompt"
        self.model = object()
        self.formatter = object()
        self.printed_messages: list[str] = []

    async def print(self, msg: Msg) -> None:
        self.printed_messages.append(msg.get_text_content() or "")


def _build_agent_config(
    *,
    confirmation_mode: str = "risk_only",
    summarize_when_compact: bool = False,
) -> SimpleNamespace:
    """Build a lightweight config object with the required fields."""
    compact_cfg = SimpleNamespace(
        enabled=True,
        compact_threshold_ratio=0.8,
        reserve_threshold_ratio=0.1,
        compact_with_thinking_block=True,
        fallback_confirmation_mode=confirmation_mode,
    )
    light_context_cfg = SimpleNamespace(context_compact_config=compact_cfg)
    running_cfg = SimpleNamespace(
        max_input_length=100,
        light_context_config=light_context_cfg,
        reme_light_memory_config=SimpleNamespace(
            summarize_when_compact=summarize_when_compact,
        ),
    )
    return SimpleNamespace(language="en", running=running_cfg)


def _make_messages() -> list[Msg]:
    """Return a compactable message sequence."""
    return [
        Msg(name="user", role="user", content="Old user context"),
        Msg(
            name="assistant",
            role="assistant",
            content=[{"type": "text", "text": "Old assistant context"}],
        ),
        Msg(name="user", role="user", content="Latest user ask"),
        Msg(
            name="assistant",
            role="assistant",
            content=[{"type": "text", "text": "Recent assistant state"}],
        ),
    ]


@pytest.mark.asyncio
async def test_pre_reasoning_preserves_history_on_safe_reduction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = _make_messages()
    memory = DummyMemory(messages, summary="Existing summary")
    agent = DummyAgent(memory)
    manager = LightContextManager(working_dir="/tmp", agent_id="agent-test")

    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.load_agent_config",
        lambda _agent_id: _build_agent_config(),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.get_token_counter",
        lambda _cfg: DummyTokenCounter(),
    )

    async def fake_check_context(**_kwargs):
        return messages[:2], messages[2:], True, 90, 20

    async def fake_compact_context(**_kwargs):
        return {
            "success": False,
            "reason": "invalid summary",
            "history_compact": "",
            "before_tokens": 90,
            "after_tokens": 0,
        }

    async def fake_estimate_total_tokens(**_kwargs):
        return 85

    monkeypatch.setattr(manager, "_check_context", fake_check_context)
    monkeypatch.setattr(manager, "_compact_context", fake_compact_context)
    monkeypatch.setattr(
        manager,
        "_estimate_total_tokens",
        fake_estimate_total_tokens,
    )

    await manager.pre_reasoning(agent, {})

    assert not memory.marked
    assert memory.updated_summary is None
    assert any("History preserved" in text for text in agent.printed_messages)


@pytest.mark.asyncio
async def test_pre_reasoning_commits_emergency_fallback_summary_when_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = _make_messages()
    memory = DummyMemory(messages, summary="Existing summary")
    agent = DummyAgent(memory)
    manager = LightContextManager(working_dir="/tmp", agent_id="agent-test")

    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.load_agent_config",
        lambda _agent_id: _build_agent_config(),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.get_token_counter",
        lambda _cfg: DummyTokenCounter(),
    )

    async def fake_check_context(**_kwargs):
        return messages[:2], messages[2:], True, 90, 20

    async def fake_compact_context(**_kwargs):
        return {
            "success": False,
            "reason": "llm timeout",
            "history_compact": "",
            "before_tokens": 90,
            "after_tokens": 0,
        }

    estimates = iter([95, 70])

    async def fake_estimate_total_tokens(**_kwargs):
        return next(estimates)

    monkeypatch.setattr(manager, "_check_context", fake_check_context)
    monkeypatch.setattr(manager, "_compact_context", fake_compact_context)
    monkeypatch.setattr(
        manager,
        "_estimate_total_tokens",
        fake_estimate_total_tokens,
    )

    await manager.pre_reasoning(agent, {})

    assert [msg.id for msg in memory.marked] == [
        msg.id for msg in messages[:2]
    ]
    assert memory.updated_summary is not None
    assert "## Context Fallback Mode" in memory.updated_summary
    assert any(
        "minimum-context fallback mode" in text
        for text in agent.printed_messages
    )


@pytest.mark.asyncio
async def test_pre_reasoning_always_mode_skips_high_risk_fallback_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = _make_messages()
    memory = DummyMemory(messages, summary="Existing summary")
    agent = DummyAgent(memory)
    manager = LightContextManager(working_dir="/tmp", agent_id="agent-test")

    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.load_agent_config",
        lambda _agent_id: _build_agent_config(confirmation_mode="always"),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.context.light_context_manager.get_token_counter",
        lambda _cfg: DummyTokenCounter(),
    )

    async def fake_check_context(**_kwargs):
        return messages[:2], messages[2:], True, 90, 20

    async def fake_compact_context(**_kwargs):
        return {
            "success": False,
            "reason": "invalid summary",
            "history_compact": "",
            "before_tokens": 90,
            "after_tokens": 0,
        }

    estimates = iter([95, 70])

    async def fake_estimate_total_tokens(**_kwargs):
        return next(estimates)

    monkeypatch.setattr(manager, "_check_context", fake_check_context)
    monkeypatch.setattr(manager, "_compact_context", fake_compact_context)
    monkeypatch.setattr(
        manager,
        "_estimate_total_tokens",
        fake_estimate_total_tokens,
    )

    await manager.pre_reasoning(agent, {})

    assert not memory.marked
    assert memory.updated_summary is None
    assert any(
        "Confirmation mode is `always`" in text
        for text in agent.printed_messages
    )
