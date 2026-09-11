# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Model→event bridge tests for fallback transparency metadata.

The pinned agentscope release drops ``ChatResponse.metadata`` when it
converts model output into agent events, so ``QwenPawAgent._reasoning``
re-attaches the fallback data published by ``FallbackChatModel`` through
the request sink.  These tests cover that real chain: a model that
actually falls back during ``Agent._reasoning`` and events that leave
``QwenPawAgent._reasoning`` carrying the notice.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agentscope.agent import Agent
from agentscope.event import TextBlockStartEvent
from agentscope.message import AssistantMsg, Msg
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.loop.gates import StopAction
from qwenpaw.providers.fallback_chat_model import FallbackChatModel


class _FakeModel(ChatModelBase):
    def __init__(self, name: str, behavior: Any) -> None:
        super().__init__(
            credential=None,
            model=name,
            parameters=ChatModelBase.Parameters(),
            stream=False,
            context_size=32_768,
        )
        self.behavior = behavior

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior()


class _HttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _bare_agent(model: ChatModelBase) -> QwenPawAgent:
    """Build a minimal agent without running heavy __init__."""
    agent = object.__new__(QwenPawAgent)
    agent.model = model
    agent._context_manager = None

    async def _noop() -> None:
        return None

    async def _stop_result(_final_msg: Any) -> Any:
        return SimpleNamespace(
            action=StopAction.BYPASS,
            final_message=None,
            reason="",
        )

    agent._inject_pending_hints = _noop
    agent._model_rejects_media = lambda: False
    agent._run_stop_handlers = _stop_result
    return agent


async def test_reasoning_events_carry_fallback_metadata(
    monkeypatch,
) -> None:
    """Fallback data survives the model→event conversion boundary."""
    primary = _FakeModel("primary", _HttpError(429))
    fallback = _FakeModel(
        "fallback",
        lambda: ChatResponse(
            content=[{"type": "text", "text": "ok"}],
            is_last=True,
        ),
    )
    model = FallbackChatModel([primary, fallback])
    agent = _bare_agent(model)

    async def fake_base_reasoning(self, tool_choice=None):
        # Mirrors the real flow: the model is called (and falls back)
        # inside the base reasoning loop, then block events and the
        # final message are emitted without any response metadata.
        del tool_choice
        await self.model()
        yield TextBlockStartEvent(reply_id="r1", block_id="b1")
        yield AssistantMsg("agent", content=[])

    monkeypatch.setattr(Agent, "_reasoning", fake_base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory."
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    outputs = [evt async for evt in agent._reasoning()]

    events = [evt for evt in outputs if not isinstance(evt, Msg)]
    messages = [evt for evt in outputs if isinstance(evt, Msg)]
    assert len(events) == 1
    assert len(messages) == 1

    event_notices = events[0].metadata["qwenpaw_model_fallbacks"]
    assert len(event_notices) == 1
    assert event_notices[0]["type"] == "model_fallback"
    assert event_notices[0]["to_model_id"] == "fallback"
    actual = events[0].metadata["qwenpaw_actual_model"]
    assert actual["model_id"] == "fallback"

    # The persisted assistant message carries the notice as well.
    msg_notices = messages[0].metadata["qwenpaw_model_fallbacks"]
    assert len(msg_notices) == 1
    assert msg_notices[0]["to_model_id"] == "fallback"


async def test_reasoning_events_stay_clean_without_fallback(
    monkeypatch,
) -> None:
    """No fallback → no metadata keys injected into events."""
    only = _FakeModel(
        "only",
        lambda: ChatResponse(
            content=[{"type": "text", "text": "ok"}],
            is_last=True,
        ),
    )
    model = FallbackChatModel([only])
    agent = _bare_agent(model)

    async def fake_base_reasoning(self, tool_choice=None):
        del tool_choice
        await self.model()
        yield TextBlockStartEvent(reply_id="r1", block_id="b1")
        yield AssistantMsg("agent", content=[])

    monkeypatch.setattr(Agent, "_reasoning", fake_base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory."
        "_supports_multimodal_for_current_model",
        lambda: True,
    )

    outputs = [evt async for evt in agent._reasoning()]

    for evt in outputs:
        metadata = getattr(evt, "metadata", None) or {}
        assert "qwenpaw_model_fallbacks" not in metadata
