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
    token_count: int
    content: str = "x"


class FakeMemory:
    def __init__(
        self,
        messages: list[FakeMsg],
        compressed_summary: str = "",
    ) -> None:
        self._messages = messages
        self._compressed_summary = compressed_summary
        self.updated_summary = None
        self.marked_ids: list[str] = []
        # Track per-message marks for hard-limit filtering
        self._marks: dict[str, list[str]] = {m.id: [] for m in messages}

    async def get_memory(
        self,
        exclude_mark: str | None = None,
        prepend_summary: bool = False,
        **_kwargs,
    ) -> list[FakeMsg]:
        del prepend_summary
        if exclude_mark is not None:
            return [
                m
                for m in self._messages
                if exclude_mark not in self._marks.get(m.id, [])
            ]
        return list(self._messages)

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
        self.marked_ids = list(msg_ids)
        for mid in msg_ids:
            if mid not in self._marks:
                self._marks[mid] = []
            if new_mark not in self._marks[mid]:
                self._marks[mid].append(new_mark)
        return len(msg_ids)


class FakeMemoryManager:
    def __init__(self) -> None:
        self.summary_task_messages: list[list[FakeMsg]] = []
        self.compact_calls: list[dict[str, Any]] = []

    def add_async_summary_task(self, messages: list[FakeMsg]) -> None:
        self.summary_task_messages.append(list(messages))

    async def compact_memory(
        self,
        messages: list[FakeMsg] | None = None,
        messages_to_summarize: list[FakeMsg] | None = None,
        previous_summary: str = "",
    ) -> str:
        msgs = messages if messages is not None else messages_to_summarize
        self.compact_calls.append(
            {
                "messages_to_summarize": list(msgs) if msgs else [],
                "previous_summary": previous_summary,
            },
        )
        return "compacted-summary"


class FakeFormatter:
    def __init__(self) -> None:
        self.calls = 0

    async def format(self, msgs: list[FakeMsg]) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            {
                "role": msg.role,
                "content": str(getattr(msg, "content", "")),
                "_test_token_count": int(
                    getattr(msg, "token_count", 0)
                    or max(len(str(getattr(msg, "content", ""))) // 4, 1),
                ),
            }
            for msg in msgs
        ]


def _make_agent(messages: list[FakeMsg], summary: str = "") -> Any:
    memory = FakeMemory(messages=messages, compressed_summary=summary)
    formatter = FakeFormatter()
    return SimpleNamespace(
        memory=memory,
        formatter=formatter,
    )


async def _fake_safe_count_message_tokens(
    messages: list[dict[str, Any]],
) -> int:
    return sum(int(msg.get("_test_token_count", 0)) for msg in messages)


def _fake_safe_count_str_tokens(text: str) -> int:
    return len(text) // 4 if text else 0


async def test_compaction_triggers_on_total_context_budget(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_message_tokens",
        _fake_safe_count_message_tokens,
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _fake_safe_count_str_tokens,
    )

    memory_manager = FakeMemoryManager()
    hook = MemoryCompactionHook(
        memory_manager=memory_manager,
        memory_compact_threshold=950,
        keep_recent=1,
    )

    # message_tokens = 950 (at threshold),
    # so no compaction by message-only count
    # summary_tokens > 0 for non-empty wrapped summary
    # total = message_tokens + summary_tokens > threshold => should compact.
    messages = [
        FakeMsg(id="sys", role="system", token_count=250),
        FakeMsg(id="old-1", role="user", token_count=250),
        FakeMsg(id="old-2", role="assistant", token_count=250),
        FakeMsg(id="recent", role="user", token_count=200),
    ]
    agent = _make_agent(messages=messages, summary="existing-summary")

    await hook(agent=agent, kwargs={})

    assert memory_manager.compact_calls
    assert memory_manager.summary_task_messages
    assert agent.memory.updated_summary == "compacted-summary"
    assert agent.memory.marked_ids == ["old-1", "old-2"]
    assert agent.formatter.calls == 1


async def test_compaction_not_triggered_when_total_under_threshold(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_message_tokens",
        _fake_safe_count_message_tokens,
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _fake_safe_count_str_tokens,
    )

    memory_manager = FakeMemoryManager()
    hook = MemoryCompactionHook(
        memory_manager=memory_manager,
        memory_compact_threshold=1000,
        keep_recent=1,
    )

    # message_tokens = 800
    # summary_tokens ~= wrapped-summary-length//4
    # total stays below threshold => should not compact.
    messages = [
        FakeMsg(id="sys", role="system", token_count=200),
        FakeMsg(id="old-1", role="user", token_count=200),
        FakeMsg(id="old-2", role="assistant", token_count=200),
        FakeMsg(id="recent", role="user", token_count=200),
    ]
    agent = _make_agent(messages=messages, summary="existing-summary")

    await hook(agent=agent, kwargs={})

    assert not memory_manager.compact_calls
    assert not memory_manager.summary_task_messages
    assert agent.memory.updated_summary is None
    assert agent.memory.marked_ids == []
    assert agent.formatter.calls == 1


async def test_hard_limit_drops_oldest_messages_after_compaction(
    monkeypatch,
) -> None:
    """Hard-limit enforcement should drop oldest non-system messages
    until estimated tokens fall below hard_token_limit."""
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_message_tokens",
        _fake_safe_count_message_tokens,
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _fake_safe_count_str_tokens,
    )

    memory_manager = FakeMemoryManager()
    # Soft threshold very high (won't trigger compaction),
    # hard limit at 600 tokens.
    hook = MemoryCompactionHook(
        memory_manager=memory_manager,
        memory_compact_threshold=99999,
        keep_recent=1,
        hard_token_limit=600,
    )

    # Total = 200 + 300 + 300 + 100 = 900 tokens (> 600 hard limit)
    # After dropping old-1 (300): 200 + 300 + 100 = 600 => ok
    messages = [
        FakeMsg(id="sys", role="system", token_count=200),
        FakeMsg(id="old-1", role="user", token_count=300),
        FakeMsg(id="old-2", role="assistant", token_count=300),
        FakeMsg(id="recent", role="user", token_count=100),
    ]
    agent = _make_agent(messages=messages, summary="")

    await hook(agent=agent, kwargs={})

    # Compaction should NOT have been triggered (under soft threshold)
    assert not memory_manager.compact_calls

    # Hard-limit should have dropped old-1 (the oldest non-system msg)
    assert "old-1" in agent.memory._marks
    assert "compressed" in agent.memory._marks["old-1"]


async def test_hard_limit_not_triggered_when_under_limit(
    monkeypatch,
) -> None:
    """When tokens are under hard_token_limit, no messages should be dropped."""
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_message_tokens",
        _fake_safe_count_message_tokens,
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _fake_safe_count_str_tokens,
    )

    memory_manager = FakeMemoryManager()
    hook = MemoryCompactionHook(
        memory_manager=memory_manager,
        memory_compact_threshold=99999,
        keep_recent=1,
        hard_token_limit=1000,
    )

    # Total = 200 + 100 + 100 + 100 = 500 tokens (< 1000 limit)
    messages = [
        FakeMsg(id="sys", role="system", token_count=200),
        FakeMsg(id="old-1", role="user", token_count=100),
        FakeMsg(id="old-2", role="assistant", token_count=100),
        FakeMsg(id="recent", role="user", token_count=100),
    ]
    agent = _make_agent(messages=messages, summary="")

    await hook(agent=agent, kwargs={})

    # Nothing should have been dropped
    assert not memory_manager.compact_calls
    for mid, marks in agent.memory._marks.items():
        assert "compressed" not in marks, f"Message {mid} was unexpectedly dropped"


async def test_hard_limit_zero_disables_enforcement(
    monkeypatch,
) -> None:
    """When hard_token_limit=0, hard-limit enforcement is disabled."""
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_message_tokens",
        _fake_safe_count_message_tokens,
    )
    monkeypatch.setattr(
        "copaw.agents.hooks.memory_compaction.safe_count_str_tokens",
        _fake_safe_count_str_tokens,
    )

    memory_manager = FakeMemoryManager()
    hook = MemoryCompactionHook(
        memory_manager=memory_manager,
        memory_compact_threshold=99999,
        keep_recent=1,
        hard_token_limit=0,  # disabled
    )

    # Total = 900 tokens, but hard limit is disabled
    messages = [
        FakeMsg(id="sys", role="system", token_count=200),
        FakeMsg(id="old-1", role="user", token_count=300),
        FakeMsg(id="old-2", role="assistant", token_count=300),
        FakeMsg(id="recent", role="user", token_count=100),
    ]
    agent = _make_agent(messages=messages, summary="")

    await hook(agent=agent, kwargs={})

    # Nothing should have been dropped (hard limit disabled)
    for mid, marks in agent.memory._marks.items():
        assert "compressed" not in marks, f"Message {mid} was unexpectedly dropped"
