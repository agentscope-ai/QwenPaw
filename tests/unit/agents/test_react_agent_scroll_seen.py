# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for Scroll's successful-model-input acknowledgement hook."""
from types import SimpleNamespace

import pytest
from agentscope.agent import Agent
from agentscope.event import ModelCallEndEvent
from agentscope.message import HintBlock, Msg, TextBlock
from agentscope.model import FinishedReason

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.loop.gates import StopAction, StopHandlerResult


class SeenTracker:
    """Minimal Scroll manager surface used by ``QwenPawAgent._reasoning``."""

    def __init__(self) -> None:
        self.acknowledged: list[set[str]] = []

    @staticmethod
    def model_input_tool_result_ids(agent) -> set[str]:
        return {"call-seen"}

    def acknowledge_model_input_tool_results(self, ids: set[str]) -> None:
        self.acknowledged.append(set(ids))


class CompressionTracker:
    """Capture context-manager compression delegation arguments."""

    def __init__(self) -> None:
        self.calls = []

    async def compress(self, agent, context_config=None, instructions=None):
        self.calls.append((agent, context_config, instructions))


def make_agent(tracker: SeenTracker) -> QwenPawAgent:
    """Build only the attributes the reasoning wrapper reads."""
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = tracker
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.state = SimpleNamespace(context=[], reply_id="reply")
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key=None)
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: False

    async def stop_handlers(final_msg):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=final_msg,
        )

    agent._run_stop_handlers = stop_handlers
    return agent


def _skip_media_strip(monkeypatch) -> None:
    """Keep tests focused on seen-ack; avoid multimodal/env-dependent strip."""
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )


async def test_successful_model_call_acknowledges_input_results(monkeypatch):
    _skip_media_strip(monkeypatch)
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def successful_reasoning(self, tool_choice=None):
        yield ModelCallEndEvent(
            reply_id="reply",
            input_tokens=10,
            output_tokens=2,
            finished_reason=FinishedReason.COMPLETED,
        )
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="done")],
        )

    monkeypatch.setattr(Agent, "_reasoning", successful_reasoning)
    events = [event async for event in agent._reasoning()]

    assert tracker.acknowledged == [{"call-seen"}]
    assert isinstance(events[-1], Msg)


async def test_failed_model_call_does_not_acknowledge_results(monkeypatch):
    _skip_media_strip(monkeypatch)
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def failed_reasoning(self, tool_choice=None):
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError("provider rejected request")

    monkeypatch.setattr(Agent, "_reasoning", failed_reasoning)

    with pytest.raises(RuntimeError, match="provider rejected request"):
        async for _ in agent._reasoning():
            pass

    assert not tracker.acknowledged


async def test_interrupted_model_call_does_not_acknowledge_results(
    monkeypatch,
):
    _skip_media_strip(monkeypatch)
    tracker = SeenTracker()
    agent = make_agent(tracker)

    async def interrupted_reasoning(self, tool_choice=None):
        yield ModelCallEndEvent(
            reply_id="reply",
            input_tokens=10,
            output_tokens=0,
            finished_reason=FinishedReason.INTERRUPTED,
        )

    monkeypatch.setattr(Agent, "_reasoning", interrupted_reasoning)
    events = [event async for event in agent._reasoning()]

    assert len(events) == 1
    assert not tracker.acknowledged


async def test_compress_context_forwards_one_shot_instructions():
    tracker = CompressionTracker()
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = tracker
    agent.state = SimpleNamespace(context=[])
    config = SimpleNamespace(trigger_ratio=0.1)
    instructions = HintBlock(hint="prioritize failures", source="user")

    await agent.compress_context(config, instructions=instructions)

    assert tracker.calls == [(agent, config, instructions)]
