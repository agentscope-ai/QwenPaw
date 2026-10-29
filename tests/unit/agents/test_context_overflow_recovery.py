# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for one-shot recovery from context and request body overflow."""

import base64
import json
import random
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.agent import Agent
from agentscope.message import (
    Base64Source,
    DataBlock,
    HintBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.state import AgentState
from google.genai import errors as genai_errors
from PIL import Image

from qwenpaw.agents import prompt
from qwenpaw.agents.context.visual_compression.runtime.middleware import (
    VisualCompressionMiddleware,
)
from qwenpaw.agents.model_factory import (
    _count_wire_media_blocks,
    _create_file_block_support_formatter,
)
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.utils.message_request_normalizer import (
    mark_media_omitted_after_overflow,
)
from qwenpaw.providers.capping_formatter import (
    _CappingAnthropicFormatter,
    _CappingDashScopeFormatter,
    _CappingGeminiFormatter,
    _CappingOpenAIFormatter,
    _CappingOpenAIResponseFormatter,
)
from qwenpaw.providers.error_utils import is_request_body_too_large


class _ContextOverflowError(Exception):
    status_code = 400


class _ScrollManager:
    def __init__(self, refreshed_context):
        self.refreshed_context = refreshed_context
        self.calls = []

    async def recover_from_context_overflow(self, agent):
        self.calls.append(agent)
        agent.state.context = list(self.refreshed_context)
        return True

    async def compress(self, agent, context_config):
        raise AssertionError("normal compression must not be used")

    def on_save(self, agent, blocks):
        raise AssertionError("on_save must not be used")


class _OtherContextManager:
    def __init__(self):
        self.calls = []

    async def compress(self, agent, context_config):
        self.calls.append((agent, context_config))

    def on_save(self, agent, blocks):
        self.calls.append((agent, blocks))


class _NoOpScrollManager(_ScrollManager):
    async def recover_from_context_overflow(self, agent):
        self.calls.append(agent)
        return False


def _agent(*, context_manager=None):
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = context_manager
    agent.state = SimpleNamespace(context=["old-1", "old-2"])
    agent._prepare_model_input = AsyncMock(
        return_value={
            "messages": ["system", "compacted"],
            "tools": [{"name": "tool-after-compact"}],
        },
    )
    return agent


@pytest.mark.asyncio
async def test_context_overflow_forces_scroll_rebuilds_and_retries_once(
    monkeypatch,
):
    calls = []

    async def fake_call_model(self, messages, tools, tool_choice=None):
        calls.append((messages, tools, tool_choice))
        if len(calls) == 1:
            raise _ContextOverflowError(
                "Error code: 400 - Range of input length should be "
                "[1, 983616]",
            )
        return "ok"

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    scroll = _ScrollManager(["compacted"])
    agent = _agent(context_manager=scroll)
    agent.compress_context = AsyncMock(wraps=agent.compress_context)

    result = await agent._call_model(
        messages=["system", "old-1", "old-2"],
        tools=[{"name": "old-tool"}],
        tool_choice="auto",
    )

    assert result == "ok"
    assert len(scroll.calls) == 1
    assert scroll.calls[0] is agent
    agent.compress_context.assert_not_awaited()
    agent._prepare_model_input.assert_awaited_once()
    assert calls == [
        (
            ["system", "old-1", "old-2"],
            [{"name": "old-tool"}],
            "auto",
        ),
        (
            ["system", "compacted"],
            [{"name": "tool-after-compact"}],
            "auto",
        ),
    ]


@pytest.mark.asyncio
async def test_context_overflow_retries_only_once(monkeypatch):
    calls = 0

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        raise _ContextOverflowError(
            "Error code: 400 - context length exceeded",
        )

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    scroll = _ScrollManager(["compacted"])
    agent = _agent(context_manager=scroll)

    with pytest.raises(_ContextOverflowError, match="context length"):
        await agent._call_model(messages=["old"], tools=[])

    assert calls == 2
    assert len(scroll.calls) == 1
    agent._prepare_model_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_context_overflow_skips_retry_when_input_is_unchanged(
    monkeypatch,
):
    calls = 0

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        raise _ContextOverflowError(
            "Error code: 400 - context length exceeded",
        )

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    manager = _NoOpScrollManager(["unused"])
    agent = _agent(context_manager=manager)

    with pytest.raises(_ContextOverflowError, match="context length"):
        await agent._call_model(
            messages=["system", "old"],
            tools=[{"name": "same-tool"}],
        )

    assert calls == 1
    assert len(manager.calls) == 1
    agent._prepare_model_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_bad_request_does_not_compact_or_retry(monkeypatch):
    calls = 0

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        raise _ContextOverflowError(
            "Error code: 400 - unsupported parameter: temperature",
        )

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    scroll = _ScrollManager(["compacted"])
    agent = _agent(context_manager=scroll)

    with pytest.raises(_ContextOverflowError, match="unsupported parameter"):
        await agent._call_model(messages=["old"], tools=[])

    assert calls == 1
    assert not scroll.calls
    agent._prepare_model_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_overflow_without_scroll_does_not_retry(monkeypatch):
    calls = 0

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        raise _ContextOverflowError(
            "Error code: 400 - prompt is too long",
        )

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    agent = _agent(context_manager=None)

    with pytest.raises(_ContextOverflowError, match="prompt is too long"):
        await agent._call_model(messages=["old"], tools=[])

    assert calls == 1
    agent._prepare_model_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_overflow_with_other_manager_does_not_retry(monkeypatch):
    calls = 0

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        raise _ContextOverflowError(
            "Error code: 400 - prompt is too long",
        )

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    manager = _OtherContextManager()
    agent = _agent(context_manager=manager)

    with pytest.raises(_ContextOverflowError, match="prompt is too long"):
        await agent._call_model(messages=["old"], tools=[])

    assert calls == 1
    assert not manager.calls
    agent._prepare_model_input.assert_not_awaited()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 400 - maximum context length is 128000", True),
        ("<400> input length should be between 1 and 983616", False),
        ("Error code: 400 - image_url is unsupported", False),
        ("Error code: 500 - context length exceeded", False),
    ],
)
def test_context_overflow_classifier_requires_400_and_specific_marker(
    message,
    expected,
):
    exc = Exception(message)
    assert QwenPawAgent._is_context_overflow_error(exc) is expected


@pytest.mark.parametrize(
    "message",
    [
        (
            "The input token count (1337419) exceeds the maximum number "
            "of tokens allowed (1048576)."
        ),
        (
            "Unable to submit request because the input token count is "
            "135538 but model only supports up to 32768"
        ),
    ],
)
def test_context_overflow_classifier_supports_gemini_client_error(message):
    exc = genai_errors.ClientError(
        400,
        {
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": message,
            },
        },
    )
    assert QwenPawAgent._is_context_overflow_error(exc) is True


def test_context_overflow_classifier_supports_aiohttp_response_status():
    exc = Exception("context length exceeded")
    exc.response = SimpleNamespace(status=400)
    assert QwenPawAgent._is_context_overflow_error(exc) is True


class _BodyOverflowError(Exception):
    """Represent a gateway body-limit rejection."""

    def __init__(self, status=413, message="Request body too large"):
        super().__init__(message)
        self.status_code = status


def _image(block_id, color="red"):
    output = BytesIO()
    Image.new("RGB", (32, 32), color).save(output, format="PNG")
    return DataBlock(
        id=block_id,
        source=Base64Source(
            media_type="image/png",
            data=base64.b64encode(output.getvalue()).decode("ascii"),
        ),
    )


def _media_history():
    return [
        Msg(name="user", role="user", content=[_image("upload")]),
        Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(id="call", name="view_image", input="{}"),
                ToolResultBlock(
                    id="call",
                    name="view_image",
                    output=[_image(f"result-{i}") for i in range(6)],
                ),
                HintBlock(hint=[_image("background")]),
            ],
        ),
        Msg(name="user", role="user", content=[TextBlock(text="continue")]),
    ]


def _media_agent(history):
    agent = object.__new__(QwenPawAgent)
    agent.state = AgentState(context=history)
    agent._context_manager = None
    agent.formatter = _create_file_block_support_formatter(
        _CappingOpenAIFormatter,
    )(promote_tool_result_images=True)

    async def prepare():
        return {"messages": agent.state.context, "tools": []}

    agent._prepare_model_input = AsyncMock(side_effect=prepare)
    return agent


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (413, "Content Too Large", True),
        (None, "Error code: 413 - rejected", True),
        (400, "request body is too large", True),
        (
            500,
            "Failed to buffer the request body: length limit exceeded",
            True,
        ),
        (
            None,
            "Failed to buffer the request body: length limit exceeded",
            True,
        ),
        (400, "maximum context length exceeded", False),
        (400, "length limit exceeded", False),
        (400, "request body format invalid", False),
        (500, "internal server error", False),
        (200, "payload too large", False),
        (302, "request body too large", False),
    ],
)
def test_body_limit_classifier(status, message, expected):
    error = _BodyOverflowError(status, message)
    assert is_request_body_too_large(error) is expected
    if expected:
        assert QwenPawAgent._is_context_overflow_error(error) is False


@pytest.mark.parametrize(
    "formatter_class",
    [
        _CappingOpenAIFormatter,
        _CappingOpenAIResponseFormatter,
        _CappingAnthropicFormatter,
        _CappingGeminiFormatter,
        _CappingDashScopeFormatter,
    ],
)
async def test_omissions_survive_resume_and_allow_new_images(formatter_class):
    agent = _media_agent(_media_history())
    original = [msg.model_dump(mode="json") for msg in agent.state.context]
    assert mark_media_omitted_after_overflow(agent.state.context) == 8
    assert mark_media_omitted_after_overflow(agent.state.context) == 0

    snapshot = json.loads(json.dumps(agent.state_dict()))
    restored = _media_agent([])
    restored.load_state_dict(snapshot)
    assert restored.state_dict() == snapshot
    for before, after in zip(original, snapshot["state"]["context"]):
        assert {**after, "metadata": before["metadata"]} == before

    formatter = _create_file_block_support_formatter(formatter_class)()
    old_wire = await formatter.format(restored.state.context)
    assert _count_wire_media_blocks(old_wire) == 0
    assert "body size limit" in json.dumps(old_wire)
    assert _image("original").source.data not in json.dumps(old_wire)

    restored.state.context.append(
        Msg(name="user", role="user", content=[_image("new-upload")]),
    )
    new_wire = await formatter.format(restored.state.context)
    assert _count_wire_media_blocks(new_wire) == 1
    assert [msg.model_dump(mode="json") for msg in agent.state.context] == (
        snapshot["state"]["context"]
    )


@pytest.mark.parametrize("retry_fails", [False, True])
@pytest.mark.parametrize("visual_compression", [False, True])
async def test_body_recovery_rebuilds_once_without_scroll(
    monkeypatch,
    retry_fails,
    visual_compression,
):
    agent = _media_agent(_media_history())
    agent.state.context[-1].content.append(_image("active", "blue"))
    original_content = [
        msg.model_dump()["content"] for msg in agent.state.context
    ]
    requests = []
    middleware = VisualCompressionMiddleware(
        SimpleNamespace(enabled=visual_compression, effort="low"),
    )
    monkeypatch.setattr(prompt, "get_model_supports_image", lambda _: True)

    async def call(self, messages, tools, tool_choice=None):
        async def send(messages, tools, tool_choice, current_model):
            if visual_compression:
                assert all(
                    copied is not original
                    for copied, original in zip(messages, self.state.context)
                )
                assert [msg.model_dump() for msg in messages] == [
                    msg.model_dump() for msg in self.state.context
                ]
            wire = await self.formatter.format(messages)
            requests.append(
                (_count_wire_media_blocks(wire), tools, tool_choice),
            )
            if len(requests) == 1 or retry_fails:
                raise _BodyOverflowError()
            return "recovered"

        return await middleware.on_model_call(
            self,
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "current_model": SimpleNamespace(model_key="body-recovery"),
            },
            send,
        )

    monkeypatch.setattr(Agent, "_call_model", call)
    if retry_fails:
        with pytest.raises(_BodyOverflowError):
            await agent._call_model(agent.state.context, [], "auto")
    else:
        assert (
            await agent._call_model(
                agent.state.context,
                [],
                "auto",
            )
            == "recovered"
        )
        assert (
            await agent._call_model(
                agent.state.context,
                [],
                "auto",
            )
            == "recovered"
        )
    assert requests == (
        [(9, [], "auto"), (1, [], "auto")]
        + ([] if retry_fails else [(1, [], "auto")])
    )
    agent._prepare_model_input.assert_awaited_once()
    assert [msg.model_dump()["content"] for msg in agent.state.context] == (
        original_content
    )
    assert [msg.metadata for msg in agent.state.context] == [
        {"qwenpaw_omitted_media_ids": ["upload"]},
        {
            "qwenpaw_omitted_media_ids": [
                "background",
                *[f"result-{i}" for i in range(6)],
            ],
        },
        {},
    ]


async def test_text_only_body_overflow_is_not_retried(monkeypatch):
    agent = _media_agent(
        [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="large text")],
            ),
        ],
    )
    calls = []

    async def call(self, messages, tools, tool_choice=None):
        calls.append((messages, tools, tool_choice))
        await self.formatter.format(messages)
        raise _BodyOverflowError()

    monkeypatch.setattr(Agent, "_call_model", call)
    with pytest.raises(_BodyOverflowError):
        await agent._call_model(agent.state.context, [])
    assert calls == [(agent.state.context, [], None)]
    agent._prepare_model_input.assert_not_awaited()


@pytest.mark.parametrize("emitted", [False, True])
async def test_body_recovery_respects_stream_output(monkeypatch, emitted):
    agent = _media_agent(_media_history())
    requests = []

    async def call(self, messages, tools, tool_choice=None):
        wire = await self.formatter.format(messages)
        requests.append(_count_wire_media_blocks(wire))

        async def stream():
            if len(requests) == 1:
                if emitted:
                    yield SimpleNamespace(content=[TextBlock(text="partial")])
                raise _BodyOverflowError()
            yield SimpleNamespace(content=[TextBlock(text="recovered")])

        return stream()

    monkeypatch.setattr(Agent, "_call_model", call)
    stream = await agent._call_model(agent.state.context, [])
    if emitted:
        with pytest.raises(_BodyOverflowError):
            async for _ in stream:
                pass
        assert requests == [8]
        agent._prepare_model_input.assert_not_awaited()
    else:
        chunks = [chunk async for chunk in stream]
        assert [block.text for chunk in chunks for block in chunk.content] == [
            "recovered",
        ]
        assert requests == [8, 0]


async def test_aggregate_body_limit_with_small_individual_images(monkeypatch):
    agent = _media_agent(_media_history())
    output = BytesIO()
    Image.frombytes(
        "RGB",
        (128, 128),
        random.Random(8335).randbytes(128 * 128 * 3),
    ).save(output, format="PNG")
    image_bytes = output.getvalue()
    assert len(image_bytes) < 2 * 1024 * 1024
    for block in agent.state.context[1].content[1].output:
        block.source.data = base64.b64encode(image_bytes).decode("ascii")

    body_limit = 256 * 1024
    request_sizes = []

    async def call(self, messages, tools, tool_choice=None):
        wire = await self.formatter.format(messages)
        size = len(json.dumps({"messages": wire, "tools": tools}).encode())
        request_sizes.append(size)
        if size > body_limit:
            raise _BodyOverflowError()
        return "ok"

    monkeypatch.setattr(Agent, "_call_model", call)
    assert await agent._call_model(agent.state.context, []) == "ok"
    assert len(request_sizes) == 2
    assert request_sizes[0] > body_limit > request_sizes[1]
    assert await agent._call_model(agent.state.context, []) == "ok"
    assert request_sizes[2] == request_sizes[1]


@pytest.mark.parametrize("changes", [True, False])
async def test_text_body_overflow_uses_context_recovery(monkeypatch, changes):
    text = Msg(name="user", role="user", content=[TextBlock(text="text")])
    agent = _media_agent([text])
    manager = (_ScrollManager if changes else _NoOpScrollManager)([text])
    agent._context_manager = manager
    requests = []

    async def call(self, messages, tools, tool_choice=None):
        requests.append(messages)
        await self.formatter.format(messages)
        if len(requests) == 1:
            raise _BodyOverflowError()
        return "ok"

    monkeypatch.setattr(Agent, "_call_model", call)
    if changes:
        assert await agent._call_model(agent.state.context, []) == "ok"
    else:
        with pytest.raises(_BodyOverflowError):
            await agent._call_model(agent.state.context, [])
    assert manager.calls == [agent]
    assert len(requests) == (2 if changes else 1)


async def test_body_recovery_does_not_fold_active_media(monkeypatch):
    agent = _media_agent(_media_history()[:2])
    before = agent.state_dict()
    manager = _ScrollManager([])
    agent._context_manager = manager
    calls = []

    async def call(self, messages, tools, tool_choice=None):
        calls.append(await self.formatter.format(messages))
        raise _BodyOverflowError()

    monkeypatch.setattr(Agent, "_call_model", call)
    with pytest.raises(_BodyOverflowError):
        await agent._call_model(agent.state.context, [])
    assert len(calls) == 1
    assert not manager.calls
    assert agent.state_dict() == before
