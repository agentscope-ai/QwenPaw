# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from copaw.agents.hooks.memory_compaction import MemoryCompactionHook


@dataclass
class FakeMsg:
    id: str
    role: str
    content: str = "x"


class FakeMemory:
    def __init__(
        self,
        messages: list[FakeMsg],
        compressed_summary: str = "",
    ) -> None:
        self._messages = messages
        self._compressed_summary = compressed_summary
        self.updated_summary: str | None = None
        self.marked_ids: list[str] = []

    async def get_memory(
        self,
        prepend_summary: bool = False,
        **_kwargs,
    ) -> list[FakeMsg]:
        del prepend_summary
        return self._messages

    def get_compressed_summary(self) -> str:
        return self._compressed_summary

    async def update_compressed_summary(self, summary: str) -> None:
        self.updated_summary = summary
        self._compressed_summary = summary

    async def update_messages_mark(
        self,
        new_mark: str,
        msg_ids: list[str],
    ) -> int:
        del new_mark
        self.marked_ids = list(msg_ids)
        return len(msg_ids)


class FakeCheckContextResult:
    def __init__(
        self,
        messages_to_compact: list[FakeMsg],
        is_valid: bool,
    ) -> None:
        self.messages_to_compact = messages_to_compact
        self.is_valid = is_valid


class FakeMemoryManager:
    def __init__(self, check_context_result: Any) -> None:
        self.check_context_result = check_context_result
        self.token_counter = object()
        self.summary_task_messages: list[list[FakeMsg]] = []
        self.compact_calls: list[dict[str, Any]] = []
        self.tool_result_compact_calls: list[list[FakeMsg]] = []

    async def check_context(self, **_kwargs) -> Any:
        return self.check_context_result

    async def compact_tool_result(self, messages: list[FakeMsg]) -> None:
        self.tool_result_compact_calls.append(list(messages))

    def add_async_summary_task(self, messages: list[FakeMsg]) -> None:
        self.summary_task_messages.append(list(messages))

    async def compact_memory(
        self,
        messages: list[FakeMsg],
        previous_summary: str = "",
    ) -> str:
        self.compact_calls.append(
            {
                "messages": list(messages),
                "previous_summary": previous_summary,
            },
        )
        return "compacted-summary"


def _make_agent(messages: list[FakeMsg], summary: str = "") -> Any:
    return SimpleNamespace(
        memory=FakeMemory(messages=messages, compressed_summary=summary),
        sys_prompt="system-prompt",
    )


def _make_config(
    *,
    memory_compact_threshold: int = 100,
    enable_tool_result_compact: bool = False,
    tool_result_compact_keep_n: int = 0,
    memory_compact_reserve: int = 10,
) -> Any:
    return SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                memory_compact_threshold=memory_compact_threshold,
                enable_tool_result_compact=enable_tool_result_compact,
                tool_result_compact_keep_n=tool_result_compact_keep_n,
                memory_compact_reserve=memory_compact_reserve,
            ),
        ),
    )


def _make_config_loader(config: Any):
    def _loader() -> Any:
        return config

    return _loader


def _zero_token_count(_text: str) -> int:
    return 0


async def test_compaction_succeeds_with_three_item_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.load_config",
        _make_config_loader(_make_config()),
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _zero_token_count,
    )

    messages = [
        FakeMsg(id="old-1", role="user"),
        FakeMsg(id="old-2", role="assistant"),
        FakeMsg(id="recent", role="user"),
    ]
    memory_manager = FakeMemoryManager(
        check_context_result=(messages[:2], messages[2:], True),
    )
    hook = MemoryCompactionHook(memory_manager=memory_manager)
    agent = _make_agent(messages=messages, summary="existing-summary")

    await hook(agent=agent, kwargs={})

    assert memory_manager.compact_calls
    assert memory_manager.summary_task_messages == [messages[:2]]
    assert agent.memory.updated_summary == "compacted-summary"
    assert agent.memory.marked_ids == ["old-1", "old-2"]


async def test_compaction_succeeds_with_extended_tuple_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.load_config",
        _make_config_loader(_make_config()),
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _zero_token_count,
    )

    messages = [
        FakeMsg(id="old-1", role="user"),
        FakeMsg(id="recent", role="assistant"),
    ]
    memory_manager = FakeMemoryManager(
        check_context_result=(messages[:1], messages[1:], True, {"extra": 1}),
    )
    hook = MemoryCompactionHook(memory_manager=memory_manager)
    agent = _make_agent(messages=messages)

    await hook(agent=agent, kwargs={})

    assert memory_manager.compact_calls
    assert memory_manager.summary_task_messages == [messages[:1]]
    assert agent.memory.marked_ids == ["old-1"]


async def test_compaction_succeeds_with_object_result(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.load_config",
        _make_config_loader(_make_config()),
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _zero_token_count,
    )

    messages = [
        FakeMsg(id="old-1", role="user"),
        FakeMsg(id="recent", role="assistant"),
    ]
    memory_manager = FakeMemoryManager(
        check_context_result=FakeCheckContextResult(
            messages_to_compact=messages[:1],
            is_valid=True,
        ),
    )
    hook = MemoryCompactionHook(memory_manager=memory_manager)
    agent = _make_agent(messages=messages)

    await hook(agent=agent, kwargs={})

    assert memory_manager.compact_calls
    assert agent.memory.updated_summary == "compacted-summary"
    assert agent.memory.marked_ids == ["old-1"]


async def test_no_compaction_when_check_context_returns_empty_messages(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.load_config",
        _make_config_loader(
            _make_config(
                enable_tool_result_compact=True,
                tool_result_compact_keep_n=1,
            ),
        ),
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _zero_token_count,
    )

    messages = [
        FakeMsg(id="old-1", role="user"),
        FakeMsg(id="recent", role="assistant"),
    ]
    memory_manager = FakeMemoryManager(
        check_context_result={"messages_to_compact": [], "is_valid": True},
    )
    hook = MemoryCompactionHook(memory_manager=memory_manager)
    agent = _make_agent(messages=messages)

    await hook(agent=agent, kwargs={})

    assert memory_manager.tool_result_compact_calls == [messages[:-1]]
    assert not memory_manager.compact_calls
    assert not memory_manager.summary_task_messages
    assert agent.memory.updated_summary is None
    assert agent.memory.marked_ids == []
