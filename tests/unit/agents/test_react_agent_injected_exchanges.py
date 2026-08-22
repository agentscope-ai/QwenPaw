# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""``QwenPawAgent`` surfaces middleware-injected exchanges as tool events."""
from __future__ import annotations

from types import SimpleNamespace

from agentscope.event import (
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState

from qwenpaw.agents.react_agent import QwenPawAgent


def _bare_agent() -> QwenPawAgent:
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._injected_exchanges = []
    agent.state = SimpleNamespace(reply_id="reply-1")
    return agent


def test_queue_and_drain_emit_a_complete_tool_call_and_result():
    agent = _bare_agent()
    agent.queue_injected_exchange(
        call_id="c1",
        name="consult_advisor",
        arguments='{"question": "plan?"}',
        output="THE PLAN",
    )
    events = list(agent._drain_injected_exchange_events())
    assert [type(e) for e in events] == [
        ToolCallStartEvent,
        ToolCallDeltaEvent,
        ToolCallEndEvent,
        ToolResultStartEvent,
        ToolResultTextDeltaEvent,
        ToolResultEndEvent,
    ]
    assert all(e.reply_id == "reply-1" for e in events)
    assert all(e.tool_call_id == "c1" for e in events)
    assert events[0].tool_call_name == "consult_advisor"
    assert events[1].delta == '{"question": "plan?"}'
    assert events[4].delta == "THE PLAN"
    assert events[5].state == ToolResultState.SUCCESS
    assert not list(agent._drain_injected_exchange_events()), "drained"


def test_empty_arguments_and_output_skip_the_deltas():
    agent = _bare_agent()
    agent.queue_injected_exchange(
        call_id="c2",
        name="x",
        arguments="",
        output="",
    )
    events = list(agent._drain_injected_exchange_events())
    assert [type(e) for e in events] == [
        ToolCallStartEvent,
        ToolCallEndEvent,
        ToolResultStartEvent,
        ToolResultEndEvent,
    ]
