# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for bounded recovery from context and request body overflow."""

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
from qwenpaw.agents.context.overflow_recovery import (
    call_with_overflow_recovery,
)
from qwenpaw.agents.context.visual_compression.runtime.middleware import (
    VisualCompressionMiddleware,
)
from qwenpaw.agents.model_factory import (
    _count_wire_media_blocks,
    _create_file_block_support_formatter,
)
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.utils.message_request_normalizer import (
    _omitted_ids,
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
    assert agent._prepare_model_input.await_count == 1
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
async def test_context_overflow_retries_at_most_twice(monkeypatch):
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

    assert calls == 3
    assert len(scroll.calls) == 2
    assert agent._prepare_model_input.await_count == 2


@pytest.mark.asyncio
async def test_context_overflow_recovers_from_invocation_then_stream(
    monkeypatch,
):
    calls = 0
    message = (
        "The input (265309 tokens) is longer than the model's context "
        "length (262144 tokens)."
    )

    async def fake_call_model(self, messages, tools, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _ContextOverflowError(message)

        async def stream():
            if calls == 2:
                raise _ContextOverflowError(message)
            yield SimpleNamespace(content=[TextBlock(text="recovered")])

        return stream()

    monkeypatch.setattr(Agent, "_call_model", fake_call_model)
    manager = _ScrollManager(["compacted"])
    agent = _agent(context_manager=manager)
    stream = await agent._call_model(messages=["old"], tools=[])
    chunks = [chunk async for chunk in stream]
    assert chunks[-1].content[0].text == "recovered"
    assert calls == 3
    assert len(manager.calls) == 2


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
    # Both refusals share one recovery budget. A retry that is refused
    # again spends the remaining recovery — omit history first, then try a
    # smaller rendition — instead of ending the turn.
    first_call = [(9, [], "auto"), (1, [], "auto")]
    if retry_fails:
        first_call.append((1, [], "auto"))
    assert requests == first_call + ([] if retry_fails else [(1, [], "auto")])
    # Each recovery rebuilds the input. A retry that is refused again spends
    # the second recovery on a smaller rendition, so a failing retry
    # prepares the input twice.
    assert agent._prepare_model_input.await_count == (2 if retry_fails else 1)
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


async def test_body_recovery_tightens_limits_without_folding_active_media(
    monkeypatch,
):
    """A body rejection with no historical media tightens, never deletes.

    The active turn is what the user is asking about, so its media must not
    be folded away. Shrinking the request-scoped limits and retrying once
    keeps the block and still gives the request a second chance.
    """
    agent = _media_agent(_media_history()[:2])
    before = agent.state_dict()
    original_side = agent.formatter.max_image_side
    original_bytes = agent.formatter.max_bytes
    manager = _ScrollManager([])
    agent._context_manager = manager
    calls = []

    async def call(self, messages, tools, tool_choice=None):
        calls.append(await self.formatter.format(messages))
        raise _BodyOverflowError()

    monkeypatch.setattr(Agent, "_call_model", call)
    with pytest.raises(_BodyOverflowError):
        await agent._call_model(agent.state.context, [])
    assert len(calls) == 2
    assert not manager.calls
    assert agent.state_dict() == before
    # The retry keeps every media block: rescaling is not omission.
    assert _count_wire_media_blocks(calls[1]) == _count_wire_media_blocks(
        calls[0],
    )
    # The tightened limits are only borrowed for that one retry.
    assert agent.formatter.max_image_side == original_side
    assert agent.formatter.max_bytes == original_bytes


async def test_media_payload_rejection_marks_history_and_retries(monkeypatch):
    """A 400 naming the media payload must not be replayed forever.

    The non-streaming path used to recognise only 413 / body-size wording,
    so a "image dimensions exceed the maximum" rejection raised straight
    through and the block stayed in state.context for every later turn.
    """
    agent = _media_agent(_media_history())
    agent.formatter._qwenpaw_last_wire_media_count = 8
    agent._retry_with_refreshed_input = AsyncMock(return_value="ok")
    rejection = _BodyOverflowError(
        400,
        "image dimensions exceed the maximum allowed size",
    )

    assert (
        await agent._recover_model_overflow(rejection, tool_choice=None)
        == "ok"
    )
    assert agent._retry_with_refreshed_input.await_count == 1
    marked = sum(len(_omitted_ids(message)) for message in agent.state.context)
    assert marked == 8


async def test_media_payload_rejection_tightens_limits_for_active_turn(
    monkeypatch,
):
    """With no historical media to omit, the failing rendition is rescaled."""
    agent = _media_agent(
        [Msg(name="user", role="user", content=[_image("only-active")])],
    )
    agent.formatter._qwenpaw_last_wire_media_count = 1
    # The image is base64, so tightening the limits can re-encode it.
    agent.formatter._qwenpaw_last_wire_resizable_images = 1
    original_side = agent.formatter.max_image_side
    original_bytes = agent.formatter.max_bytes
    seen = {}

    async def retry(tool_choice, retry=None):
        seen["side"] = agent.formatter.max_image_side
        seen["bytes"] = agent.formatter.max_bytes
        return "ok"

    agent._retry_with_refreshed_input = AsyncMock(side_effect=retry)
    rejection = _BodyOverflowError(
        400,
        "image size exceeds the maximum allowed pixels",
    )

    assert (
        await agent._recover_model_overflow(rejection, tool_choice=None)
        == "ok"
    )
    assert seen["side"] < original_side
    assert seen["bytes"] < original_bytes
    assert agent.formatter.max_image_side == original_side
    assert agent.formatter.max_bytes == original_bytes


def test_media_omission_notice_is_attached_to_the_reply():
    """Users must be able to tell "ignored" from "never delivered"."""
    agent = _media_agent(_media_history()[:1])
    reply = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(text="done")],
    )
    agent._note_media_omission(3, "provider media limit")
    agent._attach_media_omission_notice(reply)
    assert reply.metadata["qwenpaw_media_omitted"] == {
        "count": 3,
        "reason": "provider media limit",
    }


@pytest.mark.asyncio
async def test_a_recovered_retry_may_recover_once_more():
    """The second refusal of one request shares the recovery budget.

    A 413 that omits historical media can be followed by a second 413 about
    the media in the active turn. Without covering the retry, that second
    refusal ended the turn with the active image at its original size.
    """
    attempts = {"n": 0}

    async def call_model(**_kwargs):
        attempts["n"] += 1
        raise RuntimeError("request body too large")

    async def recover(_exc):
        async def retry():
            attempts["n"] += 1
            raise RuntimeError("request body too large")
            yield  # pragma: no cover

        return retry()

    result = await call_with_overflow_recovery(call_model, recover)
    with pytest.raises(RuntimeError, match="too large"):
        async for _ in result:
            pass

    # initial call + first retry + second retry, then the budget is spent
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_recovery_budget_is_capped():
    """A provider that keeps refusing must not be retried forever."""
    attempts = {"n": 0}

    async def call_model(**_kwargs):
        attempts["n"] += 1
        raise RuntimeError("request body too large")

    async def recover(_exc):
        async def retry():
            attempts["n"] += 1
            raise RuntimeError("request body too large")
            yield  # pragma: no cover

        return retry()

    result = await call_with_overflow_recovery(
        call_model,
        recover,
        max_recoveries=1,
    )
    with pytest.raises(RuntimeError):
        async for _ in result:
            pass

    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_second_non_streaming_refusal_reaches_the_shared_budget() -> None:
    """A refusal raised by the retry itself must recover from the budget.

    With one historical image and an oversized current image, the first
    recovery omits history and the retried call is refused again. That
    second refusal used to escape ``call_with_overflow_recovery`` and end
    the turn, because the recovery call sat outside the retry loop.
    """
    attempts: list[int] = []
    recoveries: list[str] = []

    async def call_model(**kwargs):
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise RuntimeError(f"413 attempt {len(attempts)}")
        return "ok"

    async def recover(exc):
        recoveries.append(str(exc))
        return await call_model()

    result = await call_with_overflow_recovery(
        call_model,
        recover,
        max_recoveries=2,
    )

    assert result == "ok"
    assert len(recoveries) == 2
    assert len(attempts) == 3


async def test_mixed_media_retry_keeps_the_configured_side_cap():
    """A large GIF must not raise the PNG above the configured cap.

    ``max_image_side=256`` with a 500 px animated GIF and a 600 px PNG: the
    request's observed side is 500, so the retry used to set the cap to 500
    and sent the PNG at 500 px as well.
    """
    agent = _media_agent(_media_history()[:2])
    agent.formatter.max_image_side = 256
    agent.formatter.max_bytes = 16 * 1024 * 1024
    agent.formatter._qwenpaw_last_wire_max_image_side = 500
    agent.formatter._qwenpaw_last_wire_resizable_images = 2

    saved = agent._tighten_media_limits()

    assert saved is not None
    assert agent.formatter.max_image_side == 256


async def test_identical_tighten_target_is_not_retried():
    """Recomputing the same target cannot fix a refusal; stop before it."""
    agent = _media_agent(_media_history()[:2])
    agent.formatter.max_image_side = 1024
    agent.formatter.max_bytes = 1024 * 1024
    agent.formatter._qwenpaw_last_wire_max_image_side = 1024
    agent.formatter._qwenpaw_last_wire_resizable_images = 1

    first = agent._tighten_media_limits()
    assert first is not None
    agent._restore_media_limits(first)

    # The provider refused the retry too, and recomputing from restored
    # limits yields the exact same rendition.
    assert agent._tighten_media_limits() is None


async def test_accepted_rendition_is_keyed_by_the_size_that_succeeded():
    """1000 px refused, 512 px accepted: cache 512, not the guess."""
    agent = _media_agent(_media_history()[:2])
    agent._media_rendition_pending = (1000, (1000, 512 * 1024))
    agent.formatter.max_image_side = 512
    agent.formatter.max_bytes = 128 * 1024
    agent.formatter._qwenpaw_last_wire_max_image_side = 512

    agent._accept_media_rendition()

    assert agent._media_rendition_target == (512, (512, 128 * 1024))


async def test_unreadable_image_is_returned_without_reopening(monkeypatch):
    """A bomb error must not be raised a second time by ``_emit()``."""
    from qwenpaw.agents.utils import image_resize

    opens = []

    def exploding_open(*args, **kwargs):
        opens.append(1)
        raise image_resize.Image.DecompressionBombError("too large")

    monkeypatch.setattr(image_resize.Image, "open", exploding_open)
    observed: list[int] = []

    data, media_type = image_resize.downscale_image_bytes(
        b"not-an-image",
        "image/png",
        max_side=256,
        max_bytes=1024,
        observed_sides=observed,
    )

    assert (data, media_type) == (b"not-an-image", "image/png")
    assert opens == [1]
    assert observed == []


def test_an_unchanged_rendition_side_is_not_retried():
    """2000 -> 1000 -> 512, then stop: another 512 would resend the payload.

    Halving the byte budget below the side floor re-encodes the same pixels,
    so the formatted request is identical. The reviewer saw the last two
    attempts carry the same 120-byte PNG; this pins that the chain ends at
    the second 512 instead of replaying it.
    """
    agent = _media_agent(_media_history()[:2])
    formatter = agent.formatter
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_resizable_images = 1
    # A 120-byte PNG: no tightened byte budget can re-encode it, so only the
    # side matters for whether a retry could carry a different payload.
    formatter._qwenpaw_last_wire_max_image_bytes = 120
    original = (8192, 2 * 1024 * 1024)

    formatter._qwenpaw_last_wire_max_image_side = 2000
    assert agent._tighten_media_limits(enforce_payload_check=True) is not None
    assert formatter.max_image_side == 1000
    agent._restore_media_limits(original)

    formatter._qwenpaw_last_wire_max_image_side = 1000
    assert agent._tighten_media_limits(enforce_payload_check=True) is not None
    assert formatter.max_image_side == 512
    agent._restore_media_limits(original)

    # 512 is the floor and the image is already 120 bytes, so no limit can
    # re-encode it: another attempt would format the identical payload.
    formatter._qwenpaw_last_wire_max_image_side = 512
    assert agent._tighten_media_limits(enforce_payload_check=True) is None


def test_a_media_free_success_does_not_cache_a_rendition():
    """A call that carried no media proves nothing about the rendition.

    The reviewer's run succeeded with ``500 px -> 500 px -> no image``; caching
    500 px as accepted made the next iteration resend a size the provider had
    never accepted.
    """
    agent = _media_agent(_media_history()[:2])
    agent._media_rendition_pending = (500, (512, 128 * 1024))
    agent.formatter._qwenpaw_last_wire_media_count = 0
    agent.formatter._qwenpaw_last_wire_media_summary = []

    agent._accept_media_rendition()

    assert agent._media_rendition_pending is None
    assert agent._media_rendition_target is None


def test_an_accepted_rendition_is_reused_by_its_source_image():
    """The next call in the turn starts from the accepted limits, not 2000.

    Keying the cache by the last rejected rendition made every iteration walk
    2000 -> 1000 -> 512 again. The source image is what the cache belongs to.
    """
    agent = _media_agent(_media_history()[:2])
    formatter = agent.formatter
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_resizable_images = 1
    # A 120-byte PNG: no tightened byte budget can re-encode it, so only the
    # side matters for whether a retry could carry a different payload.
    formatter._qwenpaw_last_wire_max_image_bytes = 120
    original = (8192, 2 * 1024 * 1024)
    formatter._qwenpaw_last_wire_max_image_side = 2000
    assert agent._tighten_media_limits() is not None
    agent._restore_media_limits(original)
    formatter._qwenpaw_last_wire_max_image_side = 1000
    assert agent._tighten_media_limits() is not None
    # The provider accepted the 512 rendition this attempt carried.

    # The provider accepted the 512 rendition of this call.
    formatter.max_image_side = 512
    formatter.max_bytes = 128 * 1024
    formatter._qwenpaw_last_wire_media_count = 1
    formatter._qwenpaw_last_wire_media_summary = ["#1 image 512x512"]
    agent._accept_media_rendition()
    agent._restore_media_limits(original)

    # Next call in the same turn: rebuilt from the stored source image.
    agent._media_tighten_history = None
    agent._media_rendition_source = None
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 2000

    assert agent._tighten_media_limits() is not None
    assert formatter.max_image_side == 512
    assert formatter.max_bytes == 128 * 1024
