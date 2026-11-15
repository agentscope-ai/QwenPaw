# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Regression tests for the synthetic auto-memory-recall payload.

The recall payload is injected into the model request only. It must:

1. reach the model as a separate ``user`` turn, never as an assistant
   tail — Anthropic reads a trailing assistant turn as a prefill
   continuation, which Claude 4.6+ rejects;
2. never reach a user-visible transcript;
3. survive the middleware cache round-trip (serialize then revalidate).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import HintBlock, Msg, TextBlock

from qwenpaw.agents.memory.base_memory_manager import BaseMemoryManager
from qwenpaw.agents.middlewares import MemoryMiddleware
from qwenpaw.app.chats.utils import agentscope_msg_to_message
from qwenpaw.constant import (
    AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY,
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from qwenpaw.providers.capping_formatter import (
    MAX_INLINE_MEDIA_BYTES,
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
    _CappingOpenAIResponseFormatter,
)

RECALL_MARKER = "<auto_memory_recall>"
RECALL_TEXT = "用户的社保卡信息"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MemoryManager(BaseMemoryManager):
    """Concrete manager implementing the three abstract methods."""

    async def start(self) -> None:
        pass

    async def memory_search(self, query, **_kwargs):
        return None

    async def auto_memory(self, messages, **_kwargs):
        return ""


def _text_of(entry) -> str:
    """Flatten a formatted turn or a runtime content object into text."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, list):
        return "\n".join(_text_of(item) for item in entry)
    if isinstance(entry, dict):
        for key in ("text", "content", "parts"):
            if key in entry:
                return _text_of(entry[key])
        return ""
    text = getattr(entry, "text", None)
    if isinstance(text, str):
        return text
    return str(entry)


def _make_agent():
    """Build a minimal fake agent for a normal user request."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.state = SimpleNamespace(
        context=[],
        session_id="session-1",
        middle_context={},
    )
    agent._request_context = {"session_id": "session-1"}
    return agent


def _user_msg(text: str = "hello", *, msg_id: str = "turn-1") -> Msg:
    """Build an external user query message."""
    msg = Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        metadata={
            QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
        },
    )
    msg.id = msg_id
    return msg


def _make_memory_manager():
    """Build a mocked memory manager for the middleware tests."""
    mm = MagicMock()
    mm.auto_memory_search = AsyncMock(return_value=None)
    return mm


def _assert_is_recall(msg: Msg, original: Msg) -> None:
    """Assert that ``msg`` is the recall payload of ``original``."""
    block = msg.content[0]
    assert isinstance(block, HintBlock)
    assert block.hint == original.content[0].hint
    assert RECALL_MARKER in block.hint
    assert msg.metadata[AUTO_MEMORY_SEARCH_BLOCK_IDS_KEY] == [block.id]
    assert block.id == original.content[0].id


@pytest.fixture
def manager(tmp_path):
    return _MemoryManager(working_dir=str(tmp_path), agent_id="test-agent")


@pytest.fixture
def recall_msg(manager):
    """The synthetic recall message injected into the model request."""
    return manager._build_auto_memory_search_msg(
        query="社保卡",
        max_results=3,
        text=RECALL_TEXT,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "formatter_cls",
    [
        _CappingAnthropicFormatter,
        _CappingOpenAIFormatter,
        _CappingOpenAIResponseFormatter,
        _CappingGeminiFormatter,
        _CappingDashScopeFormatter,
        _CappingOpenAIFormatter,
    ],
    ids=[
        "anthropic",
        "openai",
        "openai-responses",
        "gemini",
        "dashscope",
        "ollama",
    ],
)
async def test_final_request_carries_the_recall_as_a_user_turn(
    formatter_cls,
    recall_msg,
):
    """The recall reaches the model as a user turn, not an assistant tail."""
    formatter = formatter_cls(max_bytes=MAX_INLINE_MEDIA_BYTES)
    formatted = await formatter.format(
        [_user_msg("查一下社保卡"), recall_msg],
    )

    assert formatted[-1]["role"] == "user"
    recalled = _text_of(formatted[-1])
    assert RECALL_MARKER in recalled
    assert RECALL_TEXT in recalled
    assert [
        turn for turn in formatted if turn.get("role") == "assistant"
    ] == []


async def test_recall_is_injected_and_reused_from_the_cache(recall_msg):
    """The middleware injects the recall and reuses it within the same turn."""
    mm = _make_memory_manager()
    mw = MemoryMiddleware(memory_manager=mm)
    agent = _make_agent()
    query = _user_msg("查一下社保卡")
    agent.state.context = [query]
    mm.auto_memory_search.return_value = {"msg": [query, recall_msg]}
    first_input = {"messages": [query]}
    follow_up = Msg(
        name="agent",
        role="assistant",
        content=[TextBlock(text="continued reasoning")],
    )
    second_input = {"messages": [query, follow_up]}

    await mw.on_model_call(
        agent,
        first_input,
        AsyncMock(return_value="first"),
    )

    # The recall lands right after the user turn and the agent context is
    # left untouched.
    assert [msg.id for msg in first_input["messages"]] == [
        query.id,
        recall_msg.id,
    ]
    _assert_is_recall(first_input["messages"][1], recall_msg)
    assert agent.state.context == [query]

    await mw.on_model_call(
        agent,
        second_input,
        AsyncMock(return_value="second"),
    )

    # The second model call of the same turn must not search again, and the
    # recall comes back from the serialized cache unchanged.
    mm.auto_memory_search.assert_awaited_once()
    assert [msg.id for msg in second_input["messages"]] == [
        query.id,
        recall_msg.id,
        follow_up.id,
    ]
    _assert_is_recall(second_input["messages"][1], recall_msg)
    assert agent.state.context == [query]


def test_recall_is_omitted_from_the_converted_transcript(recall_msg):
    """The console / PawApp history conversion drops the recall."""
    reply = Msg(
        name="agent",
        role="assistant",
        content=[TextBlock(text="正常回复")],
    )
    converted = agentscope_msg_to_message(
        [_user_msg("查一下社保卡"), recall_msg, reply],
    )

    assert len(converted) == 2
    assert _text_of(converted[0].content) == "查一下社保卡"
    assert _text_of(converted[1].content) == "正常回复"


@pytest.mark.parametrize(
    "second_result",
    ["fresh", "empty"],
    ids=["fresh-results", "no-results"],
)
async def test_next_user_turn_replaces_the_cached_recall(
    manager,
    second_result,
):
    """A new user turn drops the cached recall, with or without new hits."""
    mm = _make_memory_manager()
    mw = MemoryMiddleware(memory_manager=mm)
    agent = _make_agent()
    first = _user_msg("第一轮", msg_id="turn-1")
    second = _user_msg("第二轮", msg_id="turn-2")
    stale = manager._build_auto_memory_search_msg(
        query="第一轮",
        max_results=1,
        text="旧证据",
    )
    fresh = manager._build_auto_memory_search_msg(
        query="第二轮",
        max_results=1,
        text="新证据",
    )
    mm.auto_memory_search.side_effect = [
        {"msg": [first, stale]},
        {"msg": [second, fresh]} if second_result == "fresh" else None,
    ]
    agent.state.context = [first]

    await mw.on_model_call(
        agent,
        {"messages": [first]},
        AsyncMock(return_value="first"),
    )
    agent.state.context.extend([second])
    second_input = {"messages": [first, second]}

    await mw.on_model_call(
        agent,
        second_input,
        AsyncMock(return_value="second"),
    )

    assert mm.auto_memory_search.await_count == 2
    injected_ids = [msg.id for msg in second_input["messages"]]
    # The stale evidence must be gone either way.
    assert stale.id not in injected_ids
    if second_result == "fresh":
        assert fresh.id in injected_ids
        _assert_is_recall(second_input["messages"][-1], fresh)
    else:
        assert fresh.id not in injected_ids
    assert agent.state.context == [first, second]
