# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Agent-layer tool-call input coercion funnel (issue #6839).

The pure coercion helpers live in ``qwenpaw.agents.utils.tool_call_coerce``
(tested in ``tests/unit/agents/test_tool_call_coerce.py``).  QwenPawAgent
indexes the tool schemas in ``_call_model`` and applies the coercion in
its ``_execute_tool_call`` override — the single funnel both the
sequential and the concurrent execution paths reach, immediately before
agentscope parses and validates the input.  This makes the fix
provider-agnostic: Gemini, Anthropic and DashScope go through the same
path as OpenAI.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from agentscope.agent import Agent
from agentscope.message import Msg, ToolCallBlock

from qwenpaw.agents.react_agent import QwenPawAgent

STOCK_SCHEMA = {
    "type": "object",
    "required": ["apiKey", "assetInfo"],
    "properties": {
        "apiKey": {"type": "string"},
        "assetInfo": {"type": "string"},
        "count": {"type": "integer", "default": 240},
    },
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "stock-client-local__analyze",
            "description": "fetch K-line data",
            "parameters": STOCK_SCHEMA,
        },
    },
]


def _agent() -> QwenPawAgent:
    agent = object.__new__(QwenPawAgent)
    agent._tool_schema_index = {}
    return agent


def _bad_input_block() -> ToolCallBlock:
    return ToolCallBlock(
        id="call_1",
        name="stock-client-local__analyze",
        input='{"apiKey": "k", "assetInfo": 1.000001, "count": 240}',
    )


# ---------------------------------------------------------------------------
# Schema indexing in _call_model
# ---------------------------------------------------------------------------


async def test_call_model_indexes_tool_schemas(monkeypatch) -> None:
    agent = _agent()

    async def fake_base_call_model(
        self,
        messages,
        tools,
        tool_choice=None,
    ):
        return "ok"

    monkeypatch.setattr(Agent, "_call_model", fake_base_call_model)
    await agent._call_model(messages=[], tools=TOOLS)
    assert agent._tool_schema_index == {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }


async def test_call_model_without_tools_clears_index(monkeypatch) -> None:
    agent = _agent()
    agent._tool_schema_index = {"stale": {"type": "object"}}
    monkeypatch.setattr(
        Agent,
        "_call_model",
        AsyncMock(return_value="ok"),
    )
    await agent._call_model(messages=[], tools=None)
    assert not agent._tool_schema_index


async def test_call_model_retry_reindexes_refreshed_tools(
    monkeypatch,
) -> None:
    """The overflow-recovery retry rebuilds the index from the refreshed
    tool list, because that is the list the retried model call sees."""
    refreshed_tools = [
        {
            "type": "function",
            "function": {
                "name": "tool-after-compact",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    class _OverflowError(Exception):
        status_code = 400

    class _ScrollManager:
        async def recover_from_context_overflow(self, agent):
            agent.state.context = ["compacted"]
            return True

        async def compress(self, agent, context_config):
            raise AssertionError("compression must not be used")

        def on_save(self, agent, blocks):
            raise AssertionError("on_save must not be used")

    calls: list[tuple] = []

    async def fake_base_call_model(
        self,
        messages,
        tools,
        tool_choice=None,
    ):
        calls.append(tools)
        if len(calls) == 1:
            raise _OverflowError(
                "Error code: 400 - Range of input length should be "
                "[1, 983616]",
            )
        return "ok"

    monkeypatch.setattr(Agent, "_call_model", fake_base_call_model)
    agent = _agent()
    agent._context_manager = _ScrollManager()
    agent.state = SimpleNamespace(context=["old"])
    agent._prepare_model_input = AsyncMock(
        return_value={"messages": ["m"], "tools": refreshed_tools},
    )
    await agent._call_model(messages=["m"], tools=TOOLS)
    assert len(calls) == 2
    assert agent._tool_schema_index == {
        "tool-after-compact": {"type": "object", "properties": {}},
    }


# ---------------------------------------------------------------------------
# The _execute_tool_call funnel
# ---------------------------------------------------------------------------


async def test_execute_tool_call_coerces_before_base(
    monkeypatch,
) -> None:
    """The base funnel sees already-coerced input (agent-level equivalent
    of the former stream/non-stream end-to-end provider tests: every
    provider response reaches tool execution through this single point).
    """
    agent = _agent()
    agent._tool_schema_index = {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }
    seen: dict[str, str] = {}

    async def fake_base_execute(self, tool_call, kept_rules=None):
        seen["input"] = tool_call.input
        seen["kept_rules"] = kept_rules
        yield "result-event"

    monkeypatch.setattr(Agent, "_execute_tool_call", fake_base_execute)
    block = _bad_input_block()
    events = [evt async for evt in agent._execute_tool_call(block)]
    assert events == ["result-event"]
    parsed = json.loads(seen["input"])
    assert parsed == {"apiKey": "k", "assetInfo": "1.000001", "count": 240}
    assert isinstance(parsed["assetInfo"], str)
    assert isinstance(parsed["count"], int)


async def test_execute_tool_call_mutates_block_in_place(
    monkeypatch,
) -> None:
    """The rewrite happens on the block stored in the message, so the
    repaired input travels with the persisted context."""
    agent = _agent()
    agent._tool_schema_index = {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }

    async def fake_base_execute(self, tool_call, kept_rules=None):
        yield "done"

    monkeypatch.setattr(Agent, "_execute_tool_call", fake_base_execute)
    block = _bad_input_block()
    msg = Msg(name="assistant", role="assistant", content=[block])
    stored = msg.get_content_blocks("tool_call")[0]
    assert stored is block  # get_content_blocks returns stored blocks
    _ = [evt async for evt in agent._execute_tool_call(stored)]
    parsed = json.loads(msg.get_content_blocks("tool_call")[0].input)
    assert parsed["assetInfo"] == "1.000001"


async def test_execute_tool_call_noop_for_unindexed_tool(
    monkeypatch,
) -> None:
    agent = _agent()
    agent._tool_schema_index = {}
    seen: dict[str, str] = {}

    async def fake_base_execute(self, tool_call, kept_rules=None):
        seen["input"] = tool_call.input
        seen["kept_rules"] = kept_rules
        yield "done"

    monkeypatch.setattr(Agent, "_execute_tool_call", fake_base_execute)
    block = _bad_input_block()
    _ = [evt async for evt in agent._execute_tool_call(block)]
    assert seen["input"] == block.input  # unchanged


async def test_execute_tool_call_invalid_json_passthrough(
    monkeypatch,
) -> None:
    """Broken JSON is left to agentscope's existing json-repair path."""
    agent = _agent()
    agent._tool_schema_index = {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }
    seen: dict[str, str] = {}

    async def fake_base_execute(self, tool_call, kept_rules=None):
        seen["input"] = tool_call.input
        seen["kept_rules"] = kept_rules
        yield "done"

    monkeypatch.setattr(Agent, "_execute_tool_call", fake_base_execute)
    broken = '{"apiKey": "k", "assetInfo": 1.000001'
    block = ToolCallBlock(
        id="call_2",
        name="stock-client-local__analyze",
        input=broken,
    )
    _ = [evt async for evt in agent._execute_tool_call(block)]
    assert seen["input"] == broken


async def test_coerce_tool_call_input_accepts_dict_form() -> None:
    """Defensive dict form is handled identically."""
    agent = _agent()
    agent._tool_schema_index = {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }
    tool_call = {
        "id": "call_3",
        "name": "stock-client-local__analyze",
        "input": '{"apiKey": "k", "assetInfo": 7, "count": 1}',
    }
    agent._coerce_tool_call_input(tool_call)
    parsed = json.loads(tool_call["input"])
    assert parsed["assetInfo"] == "7"
    assert parsed["count"] == 1


async def test_execute_tool_call_accepts_concurrent_path_args(
    monkeypatch,
) -> None:
    """Regression: agentscope's concurrent path (``Agent._into_queue``)
    calls ``self._execute_tool_call(tool_call, kept_rules)`` with two
    positional arguments.  The first revision of this override declared
    only ``(self, tool_call)``, so every concurrent tool call raised
    ``TypeError: takes 2 positional arguments but 3 were given`` (run
    33614106515, 11 integrated-test jobs across 3 platforms).
    """
    agent = _agent()
    agent._tool_schema_index = {
        "stock-client-local__analyze": STOCK_SCHEMA,
    }
    seen: dict[str, Any] = {}

    async def fake_base_execute(self, tool_call, kept_rules=None):
        seen["input"] = tool_call.input
        seen["kept_rules"] = kept_rules
        yield "done"

    monkeypatch.setattr(Agent, "_execute_tool_call", fake_base_execute)
    block = _bad_input_block()
    sentinel_rules = ["rule-sentinel"]
    events = [
        evt async for evt in agent._execute_tool_call(block, sentinel_rules)
    ]
    assert events == ["done"]
    # kept_rules is forwarded to the base funnel untouched.
    assert seen["kept_rules"] is sentinel_rules
    parsed = json.loads(seen["input"])
    assert parsed["assetInfo"] == "1.000001"
