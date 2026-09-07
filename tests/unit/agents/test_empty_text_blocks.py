# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Empty assistant text blocks must never reach a provider request.

A turn that spends all of its completion tokens on reasoning finishes with
an empty text part.  Persisting it replays ``{"type": "output_text",
"text": ""}`` on every later request; Volcengine Ark rejects that item with
``400 MissingParameter: input.content.text``, so one such turn poisons the
whole session (QwenPaw#7402).

The agent is exercised through ``__new__`` plus the two attributes the
methods under test touch, so the production ``_save_to_context`` and
``_sanitize_loaded_context`` run without building a model or toolkit.
"""

import pytest
from agentscope.formatter import OpenAIResponseFormatter
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock
from agentscope.state import AgentState

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.utils.text_block_utils import (
    drop_empty_text_blocks,
    is_empty_text_block,
)


def _agent() -> QwenPawAgent:
    """A QwenPawAgent shell carrying only the state the save path reads."""
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent.state = AgentState()
    agent._context_manager = None
    agent.name = "assistant"
    return agent


def _assistant(*blocks) -> Msg:
    return Msg(name="assistant", role="assistant", content=list(blocks))


class TestEmptyTextBlockPredicate:
    """The predicate rejects only the exact string the provider rejects."""

    def test_empty_text_block_is_empty(self):
        assert is_empty_text_block(TextBlock(type="text", text="")) is True

    def test_dict_block_from_legacy_state_is_recognized(self):
        assert is_empty_text_block({"type": "text", "text": ""}) is True

    @pytest.mark.parametrize("text", ["ok", " ", "\n"])
    def test_non_empty_text_is_kept(self, text):
        assert is_empty_text_block(TextBlock(type="text", text=text)) is False

    def test_non_text_blocks_are_never_empty(self):
        call = ToolCallBlock(id="c1", name="ls", input="{}")
        assert is_empty_text_block(call) is False

    def test_drop_keeps_order_of_surviving_blocks(self):
        blocks = [
            TextBlock(type="text", text=""),
            TextBlock(type="text", text="first"),
            TextBlock(type="text", text=""),
            TextBlock(type="text", text="second"),
        ]
        assert [b.text for b in drop_empty_text_blocks(blocks)] == [
            "first",
            "second",
        ]


class TestSavePath:
    """``_save_to_context`` is where the poisoned block gets persisted."""

    def test_reasoning_only_turn_persists_no_empty_text(self):
        agent = _agent()

        agent._save_to_context([TextBlock(type="text", text="")])

        assert agent.state.context == []

    def test_tool_call_in_the_same_turn_survives(self):
        agent = _agent()
        call = ToolCallBlock(id="c1", name="ls", input="{}")

        agent._save_to_context([TextBlock(type="text", text=""), call])

        assert agent.state.context[0].content == [call]

    def test_normal_text_is_untouched(self):
        agent = _agent()
        block = TextBlock(type="text", text="hello")

        agent._save_to_context([block])

        assert agent.state.context[0].content == [block]


class TestLoadPath:
    """Sessions poisoned before the save-time guard existed must heal."""

    def test_persisted_empty_block_is_stripped_on_load(self):
        agent = _agent()
        agent.state.context = [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="hi")],
            ),
            _assistant(TextBlock(type="text", text="")),
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="continue")],
            ),
        ]

        agent._sanitize_loaded_context()

        assert [m.role for m in agent.state.context] == [
            "user",
            "assistant",
            "user",
        ]
        assert agent.state.context[1].content == []

    def test_paired_tool_messages_are_preserved(self):
        agent = _agent()
        call = ToolCallBlock(id="c1", name="ls", input="{}")
        result = ToolResultBlock(id="c1", name="ls", output="ok")
        agent.state.context = [
            _assistant(TextBlock(type="text", text=""), call),
            _assistant(result),
        ]

        agent._sanitize_loaded_context()

        assert agent.state.context[0].content == [call]
        assert agent.state.context[1].content == [result]


class TestWireFormat:
    """The end the bug is actually reported at: the provider request."""

    @pytest.mark.asyncio
    async def test_no_empty_output_text_item_reaches_the_request(self):
        agent = _agent()
        agent.state.context = [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="hi")],
            ),
            _assistant(TextBlock(type="text", text="")),
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text="continue")],
            ),
        ]

        agent._sanitize_loaded_context()
        items = await OpenAIResponseFormatter().format(agent.state.context)

        parts = [
            part
            for item in items
            for part in item.get("content", [])
            if isinstance(item.get("content"), list)
        ]
        assert not [p for p in parts if p.get("text") == ""]
        assert [p["text"] for p in parts] == ["hi", "continue"]
