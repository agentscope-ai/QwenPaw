# -*- coding: utf-8 -*-
import pytest
from agentscope.message import Msg

from qwenpaw.agents.context.agent_context import AgentContext
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter


def _make_context(events: list[str]) -> AgentContext:
    return AgentContext(
        token_counter=EstimatedTokenCounter(),
        on_context_rewritten=lambda: events.append("rewritten"),
    )


@pytest.mark.asyncio
async def test_clear_content_notifies_context_rewritten() -> None:
    events: list[str] = []
    memory = _make_context(events)
    await memory.add(Msg(name="user", content="hello", role="user"))

    await memory.clear_content()

    assert events == ["rewritten"]


def test_clear_compressed_summary_notifies_context_rewritten() -> None:
    events: list[str] = []
    memory = _make_context(events)

    memory.clear_compressed_summary()

    assert events == ["rewritten"]


@pytest.mark.asyncio
async def test_update_compressed_summary_notifies_context_rewritten() -> None:
    events: list[str] = []
    memory = _make_context(events)

    await memory.update_compressed_summary("summary")

    assert events == ["rewritten"]


@pytest.mark.asyncio
async def test_mark_messages_compressed_notifies_on_remove() -> None:
    events: list[str] = []
    memory = _make_context(events)
    msg = Msg(name="user", content="hello", role="user")
    await memory.add(msg)

    removed = await memory.mark_messages_compressed([msg])

    assert removed == 1
    assert events == ["rewritten"]


def test_load_state_dict_does_not_notify_context_rewritten() -> None:
    events: list[str] = []
    memory = _make_context(events)

    memory.load_state_dict({"content": [], "_compressed_summary": ""})

    assert not events


def test_notify_context_rewritten_public_hook() -> None:
    events: list[str] = []
    memory = _make_context(events)

    memory.notify_context_rewritten()

    assert events == ["rewritten"]
