# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for one-shot recovery from provider-side remote media failures."""

from types import SimpleNamespace

import pytest
from agentscope.agent import Agent
from agentscope.message import (
    DataBlock,
    Msg,
    TextBlock,
    ToolResultBlock,
    URLSource,
)

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.constant import REMOTE_MEDIA_UNAVAILABLE_PLACEHOLDER
from qwenpaw.loop.gates import StopAction, StopHandlerResult

_BAD_URL = "https://example.com/unreachable.jpg"
_GOOD_URL = "https://example.com/available.jpg"


def _media(url: str) -> DataBlock:
    return DataBlock(
        source=URLSource(url=url, media_type="image/jpeg"),
    )


def _tool_result_with_remote_media() -> ToolResultBlock:
    return ToolResultBlock(
        id="call-view-image",
        name="view_image",
        output=[
            _media(_BAD_URL),
            TextBlock(text=f"Image loaded from URL: {_BAD_URL}"),
            _media(_GOOD_URL),
            TextBlock(text=f"Image loaded from URL: {_GOOD_URL}"),
        ],
    )


def _agent() -> QwenPawAgent:
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = None
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.state = SimpleNamespace(
        context=[
            Msg(
                name="agent",
                role="assistant",
                content=[_tool_result_with_remote_media()],
            ),
        ],
        reply_id="reply",
    )
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key="provider:model")
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: True
    agent.formatter = SimpleNamespace(
        _qwenpaw_last_wire_media_count=2,
        _qwenpaw_last_wire_audio_count=0,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )

    async def stop_handlers(final_msg):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=final_msg,
        )

    agent._run_stop_handlers = stop_handlers
    return agent


def _download_error(url: str = _BAD_URL) -> RuntimeError:
    return RuntimeError(f"Timeout while downloading url: {url}")


def _skip_proactive_media_strip(monkeypatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory._supports_multimodal_for_current_model",
        lambda: True,
    )


def test_remote_media_download_classifier_is_narrow() -> None:
    assert QwenPawAgent._is_remote_media_download_error(
        _download_error(),
    )
    assert QwenPawAgent._is_remote_media_download_error(
        RuntimeError(f"Timed out while downloading URL: {_BAD_URL}"),
    )
    assert not QwenPawAgent._is_remote_media_download_error(
        RuntimeError("Model inference timed out"),
    )


def test_degrade_failed_remote_media_only_rewrites_matching_url() -> None:
    agent = _agent()

    degraded = agent._degrade_failed_remote_media(_download_error())

    assert degraded == 1
    result = agent.state.context[0].content[0]
    assert isinstance(result, ToolResultBlock)
    assert any(
        isinstance(block, TextBlock)
        and block.text == REMOTE_MEDIA_UNAVAILABLE_PLACEHOLDER
        for block in result.output
    )
    assert not any(_BAD_URL in str(block) for block in result.output)
    assert any(
        isinstance(block, DataBlock) and str(block.source.url) == _GOOD_URL
        for block in result.output
    )
    assert any(
        isinstance(block, TextBlock) and _GOOD_URL in block.text
        for block in result.output
    )


def test_degrade_failed_remote_media_requires_url_from_context() -> None:
    agent = _agent()

    degraded = agent._degrade_failed_remote_media(
        _download_error("https://example.com/not-in-context.jpg"),
    )

    assert degraded == 0
    result = agent.state.context[0].content[0]
    assert any(_BAD_URL in str(block) for block in result.output)


@pytest.mark.asyncio
async def test_reasoning_degrades_failed_url_and_retries_once(
    monkeypatch,
) -> None:
    _skip_proactive_media_strip(monkeypatch)
    agent = _agent()
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _download_error()
        result = agent.state.context[0].content[0]
        assert not any(_BAD_URL in str(block) for block in result.output)
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(text="done")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    events = [event async for event in agent._reasoning()]

    assert calls == 2
    assert events[-1].get_text_content() == "done"
    assert agent.formatter._qwenpaw_force_strip_media is False
    assert agent.formatter._qwenpaw_force_strip_audio is False


@pytest.mark.asyncio
async def test_reasoning_does_not_retry_without_a_matching_url(
    monkeypatch,
) -> None:
    _skip_proactive_media_strip(monkeypatch)
    agent = _agent()
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise _download_error("https://example.com/not-in-context.jpg")

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="not-in-context"):
        async for _ in agent._reasoning():
            pass

    assert calls == 1


@pytest.mark.asyncio
async def test_reasoning_recovery_retries_at_most_once(monkeypatch) -> None:
    _skip_proactive_media_strip(monkeypatch)
    agent = _agent()
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise _download_error()

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="downloading url"):
        async for _ in agent._reasoning():
            pass

    assert calls == 2
