# -*- coding: utf-8 -*-
"""Request-scoped recovery from provider media URL rejections (#7966)."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agentscope.agent import Agent
from agentscope.message import (
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
)
from openai import APIStatusError, BadRequestError

from qwenpaw.agents.model_factory import _create_formatter_instance
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.providers.capping_formatter import _CappingOpenAIFormatter
from qwenpaw.providers.model_capability_cache import ModelCapabilityCache

_URL_ERROR = (
    "The provided URL does not appear to be valid. "
    "Ensure it is correctly formatted."
)
_MODEL_KEY = "agentscope:qwen3.8-max"


def _bad_request(message=_URL_ERROR, status_code=400):
    error_type = BadRequestError if status_code == 400 else APIStatusError
    return error_type(
        message,
        response=httpx.Response(
            status_code,
            request=httpx.Request("POST", "https://example.test/v1/chat"),
        ),
        body={
            "error": {
                "code": "invalid_parameter_error",
                "type": "invalid_request_error",
                "message": message,
            },
        },
    )


@pytest.fixture
def media_agent(tmp_path, monkeypatch):
    """Reload a tool result as persisted history, using the real formatter."""
    video = tmp_path / "saved video.mp4"
    video.write_bytes(b"video")
    message = Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolCallBlock(id="call_video", name="view_video", input="{}"),
            ToolResultBlock(
                id="call_video",
                name="view_video",
                state=ToolResultState.SUCCESS,
                output=[
                    TextBlock(text="Saved video"),
                    {
                        "type": "data",
                        "source": {
                            "type": "url",
                            "url": video.as_uri(),
                            "media_type": "video/mp4",
                        },
                        "name": video.name,
                    },
                ],
            ),
        ],
    )
    history = [Msg.model_validate_json(message.model_dump_json())]
    model = SimpleNamespace(
        model="qwen3.8-max",
        model_key=_MODEL_KEY,
        formatter=_CappingOpenAIFormatter(),
    )
    model.formatter = _create_formatter_instance(
        model,
        provider_id="agentscope",
    )
    agent = object.__new__(QwenPawAgent)
    agent.model = model
    agent.name = "assistant"
    agent.state = SimpleNamespace(context=history, reply_id="reply")
    agent._context_manager = None
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent._inject_pending_hints = AsyncMock()
    agent._run_stop_handlers = AsyncMock(
        return_value=StopHandlerResult(action=StopAction.BYPASS),
    )
    cache = ModelCapabilityCache()
    monkeypatch.setattr(
        "qwenpaw.agents.react_agent.get_capability_cache",
        lambda: cache,
    )
    return agent, cache


@pytest.mark.parametrize(
    "error_message",
    [_URL_ERROR, _URL_ERROR + " This model is text-only."],
)
async def test_invalid_media_url_retries_without_mutating_history(
    media_agent,
    monkeypatch,
    error_message,
):
    agent, cache = media_agent
    history_before = [msg.model_dump_json() for msg in agent.state.context]
    requests = []

    async def provider_reasoning(self, tool_choice=None):
        requests.append(await self.model.formatter.format(self.state.context))
        if self._last_wire_request_had_media():
            raise _bad_request(error_message)
        yield Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="Recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    # The next turn must be able to use media again with another provider.
    for _ in range(2):
        result = [event async for event in agent._reasoning()]
        assert result[-1].get_text_content() == "Recovered"
        assert not agent.model.formatter._qwenpaw_force_strip_media
        assert cache.get(_MODEL_KEY, "rejects_media") is None
    assert len(requests) == 4
    assert any(
        block.get("type") == "video_url"
        for message in requests[0]
        for block in message.get("content") or []
        if isinstance(block, dict)
    )
    assert not any(
        block.get("type") == "video_url"
        for message in requests[1]
        for block in message.get("content") or []
        if isinstance(block, dict)
    )
    assert [
        msg.model_dump_json() for msg in agent.state.context
    ] == history_before


async def test_invalid_media_url_retries_only_once_and_resets_flags(
    media_agent,
    monkeypatch,
):
    agent, cache = media_agent
    requests = []

    async def provider_reasoning(self, tool_choice=None):
        requests.append(await self.model.formatter.format(self.state.context))
        raise _bad_request()
        yield  # pylint: disable=unreachable

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)
    with pytest.raises(BadRequestError, match="provided URL"):
        _ = [event async for event in agent._reasoning()]
    assert len(requests) == 2
    assert not agent.model.formatter._qwenpaw_force_strip_media
    assert cache.get(_MODEL_KEY, "rejects_media") is None


@pytest.mark.parametrize(
    "message,with_media,status_code",
    [
        (_URL_ERROR, False, 400),
        (_URL_ERROR, True, 401),
        (_URL_ERROR, True, 500),
        ("unsupported parameter: temperature", True, 400),
        ("Invalid API endpoint URL", True, 400),
        ("Image rejected by content policy", True, 400),
        (_URL_ERROR + " Image rejected by content policy", True, 400),
    ],
)
async def test_unrelated_bad_requests_do_not_strip_or_retry(
    media_agent,
    monkeypatch,
    message,
    with_media,
    status_code,
):
    agent, _cache = media_agent
    if not with_media:
        agent.state.context = [
            Msg(name="user", role="user", content=[TextBlock(text="hello")]),
        ]
    requests = []

    async def provider_reasoning(self, tool_choice=None):
        requests.append(await self.model.formatter.format(self.state.context))
        raise _bad_request(message, status_code)
        yield  # pylint: disable=unreachable

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)
    with pytest.raises(APIStatusError, match=message):
        _ = [event async for event in agent._reasoning()]
    assert len(requests) == 1
    assert not getattr(
        agent.model.formatter,
        "_qwenpaw_force_strip_media",
        False,
    )
