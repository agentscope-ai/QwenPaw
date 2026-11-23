# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent media classification, stripping, and retry.

Covers _is_media_block (dict/object/data-block detection) and
_strip_media_blocks_from_memory (top-level media removal, nested
tool_result output filtering, empty-content placeholder insertion), plus
request-only recovery from provider media-payload rejections.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import base64
from io import BytesIO
import json
import os
from types import SimpleNamespace

import httpx
from openai import APIStatusError, AsyncOpenAI
from PIL import Image
import pytest
from agentscope.agent import Agent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
    URLSource,
)

from qwenpaw.agents import model_factory
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.tools.send_file import send_file_to_user
from qwenpaw.agents.utils.image_resize import downscale_image_bytes
from qwenpaw.constant import MEDIA_UNSUPPORTED_PLACEHOLDER
from qwenpaw.loop.gates import StopAction, StopHandlerResult
from qwenpaw.providers import model_capability_cache
from qwenpaw.providers.model_capability_cache import get_capability_cache


_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR = (
    "Error code: 400 - {'error': {'message': 'Failed to deserialize the "
    "JSON body into the target type: messages[106].image[0]: You have "
    "uploaded an unsupported image. Please make sure your image is valid "
    "and has one of the following formats: webp, png, jpeg, and gif.'}}"
)

_MODEL_CAPABILITY_ERROR = (
    "Error code: 400 - {'error': {'message': 'This model does not support "
    "image input.'}}"
)


# Sanitized provider messages reported in #8298 and #8290.
_VIDEO_SCHEMA_ERROR = (
    "Failed to deserialize the JSON body into the target type: "
    "messages[443]: unknown variant `video_url`, "
    "expected one of `text`, `image_url`, `file`"
)
_VIDEO_ZERO_LIMIT = (
    "At most 0 video(s) may be provided in one prompt. (parameter=video)"
)


def _agent_with_context(context: list) -> QwenPawAgent:
    """Build a bare agent with only a state.context — no model needed."""
    agent = object.__new__(QwenPawAgent)
    agent.state = SimpleNamespace(context=context)
    return agent


def _msg_with(blocks: list) -> Msg:
    """Build a Msg whose content is assigned raw (bypassing block
    validation) so dict media blocks can be inspected by the strip logic."""
    msg = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="seed")],
    )
    msg.content = blocks
    return msg


def _reasoning_agent() -> QwenPawAgent:
    """Build the attributes read by the reasoning retry wrapper."""
    agent = object.__new__(QwenPawAgent)
    agent._context_manager = None
    agent._gate_pending_stop = None
    agent._request_context = {}
    agent.state = SimpleNamespace(context=[], reply_id="reply")
    agent.name = "agent"
    agent.model = SimpleNamespace(model_key=None)
    agent._model_rejects_media = lambda: False
    agent._uses_request_time_media_normalization = lambda: True

    async def stop_handlers(final_msg):
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            final_message=final_msg,
        )

    agent._run_stop_handlers = stop_handlers
    return agent


def _media_data_block() -> DataBlock:
    """Build an inline image block accepted by AgentScope validation."""
    return DataBlock(
        source=Base64Source(
            media_type="image/png",
            data="aGVsbG8=",
        ),
    )


def _current_media_context() -> list[Msg]:
    return [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="look"),
                _media_data_block(),
            ],
        ),
    ]


def _tool_media_context() -> list[Msg]:
    tool_result = ToolResultBlock(
        id="call-image",
        name="screenshot",
        state=ToolResultState.SUCCESS,
        output="seed",
    )
    tool_result.output = [_media_data_block()]
    return [
        Msg(
            name="agent",
            role="assistant",
            content=[
                TextBlock(type="text", text="calling screenshot"),
                tool_result,
            ],
        ),
    ]


def _historical_media_context() -> list[Msg]:
    return [
        *_current_media_context(),
        Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="accepted")],
        ),
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="plain follow-up")],
        ),
    ]


def _dump_context(context: list[Msg]) -> list[dict]:
    """Return the complete stored context for mutation checks."""
    return [msg.model_dump(mode="json") for msg in context]


def _omitted_media_ids(context: list[Msg]) -> set[str]:
    """Return every media id the historical-omission pass recorded."""
    omitted: set[str] = set()
    for msg in context:
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        ids = metadata.get("qwenpaw_omitted_media_ids")
        if isinstance(ids, list):
            omitted.update(str(item) for item in ids)
    return omitted


def _dump_without_omissions(context: list[Msg]) -> list[dict]:
    """Dump the context with omission markers removed for comparison."""
    dumped = _dump_context(context)
    for message in dumped:
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("qwenpaw_omitted_media_ids", None)
    return dumped


def _formatter(wire_media_count: int = 1) -> SimpleNamespace:
    """Build the formatter state used by media fallback tests."""
    return SimpleNamespace(
        _qwenpaw_last_wire_media_count=wire_media_count,
        _qwenpaw_last_wire_audio_count=0,
        # The images these tests send are base64 and can be re-encoded, so
        # tightening the limits can change the payload.
        _qwenpaw_last_wire_resizable_images=1,
        _qwenpaw_force_strip_media=False,
        _qwenpaw_force_strip_audio=False,
    )


# ---------------------------------------------------------------------------
# _is_media_block
# ---------------------------------------------------------------------------


class TestIsMediaBlock:
    def test_dict_image_is_media(self):
        agent = _agent_with_context([])
        assert agent._is_media_block({"type": "image"}) is True
        assert agent._is_media_block({"type": "audio"}) is True
        assert agent._is_media_block({"type": "video"}) is True
        assert agent._is_media_block({"type": "file"}) is True

    def test_dict_text_not_media(self):
        agent = _agent_with_context([])
        assert agent._is_media_block({"type": "text"}) is False

    def test_object_block_by_type(self):
        agent = _agent_with_context([])
        assert agent._is_media_block(SimpleNamespace(type="image")) is True
        assert agent._is_media_block(SimpleNamespace(type="text")) is False

    def test_data_block_image_mime_is_media(self):
        agent = _agent_with_context([])
        source = SimpleNamespace(media_type="image/png")
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=source),
            )
            is True
        )

    def test_data_block_non_media_mime_not_media(self):
        agent = _agent_with_context([])
        source = SimpleNamespace(media_type="application/json")
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=source),
            )
            is False
        )

    def test_data_block_without_source_not_media(self):
        agent = _agent_with_context([])
        assert (
            agent._is_media_block(
                SimpleNamespace(type="data", source=None),
            )
            is False
        )


# ---------------------------------------------------------------------------
# _strip_media_blocks_from_memory
# ---------------------------------------------------------------------------


class TestStripMediaBlocksFromMemory:
    def test_strips_top_level_media(self):
        msg = _msg_with(
            [
                TextBlock(type="text", text="keep"),
                {"type": "image", "source": {}},
            ],
        )
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert len(msg.content) == 1
        assert msg.content[0].text == "keep"

    def test_non_list_content_skipped(self):
        msg = _msg_with([])
        msg.content = "plain string"
        agent = _agent_with_context([msg])
        assert agent._strip_media_blocks_from_memory() == 0

    def test_empty_content_gets_placeholder(self):
        msg = _msg_with([{"type": "image", "source": {}}])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert len(msg.content) == 1
        assert msg.content[0].text == MEDIA_UNSUPPORTED_PLACEHOLDER

    def test_no_media_returns_zero(self):
        msg = _msg_with([TextBlock(type="text", text="plain")])
        agent = _agent_with_context([msg])
        assert agent._strip_media_blocks_from_memory() == 0
        assert len(msg.content) == 1

    def test_nested_media_in_tool_result_stripped(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="seed",
        )
        # Assign raw nested output (bypassing block validation) so a
        # dict media item can be inspected by the strip logic.
        tool_result.output = [
            TextBlock(type="text", text="kept"),
            {"type": "image", "source": {}},
        ]
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        # The media item is removed from the nested output, and an explicit
        # marker records the omission so the surviving "kept" text cannot be
        # read as "the media is still there".
        assert len(tool_result.output) == 2
        assert tool_result.output[0].text == "kept"
        assert tool_result.output[-1].text == MEDIA_UNSUPPORTED_PLACEHOLDER

    def test_nested_all_media_replaced_with_placeholder(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="seed",
        )
        tool_result.output = [{"type": "image", "source": {}}]
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 1
        assert tool_result.output == MEDIA_UNSUPPORTED_PLACEHOLDER

    def test_nested_output_not_list_untouched(self):
        tool_result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output="plain string output",
        )
        msg = _msg_with([tool_result])
        agent = _agent_with_context([msg])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 0
        assert tool_result.output == "plain string output"

    def test_counts_across_messages(self):
        msg1 = _msg_with([{"type": "image", "source": {}}])
        msg2 = _msg_with(
            [
                TextBlock(type="text", text="ok"),
                {"type": "video", "source": {}},
            ],
        )
        agent = _agent_with_context([msg1, msg2])
        removed = agent._strip_media_blocks_from_memory()
        assert removed == 2


# ---------------------------------------------------------------------------
# request-only retry for media payload rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR, True),
        (
            "Error code: 400 - unsupported image format: application/x-tiff",
            True,
        ),
        ("Error code: 400 - invalid image data in messages[3].image[0]", True),
        ("Error code: 400 - failed to decode the audio payload", True),
        ("Error code: 400 - multiple image inputs are not supported", True),
        (
            "[400] At most 0 video(s) may be provided in one prompt. "
            "(parameter=video)",
            True,
        ),
        (
            "[400] [unsupported_request] Message content supports text "
            "content only. Images, audio and files are not enabled.",
            True,
        ),
        ("Error code: 400 - streaming is not enabled for this key", False),
        (_MODEL_CAPABILITY_ERROR, False),
        (
            "Error code: 400 - image is sensitive: invalid image content",
            False,
        ),
        ("Error code: 400 - resolution not supported", False),
        ("Error code: 400 - invalid request", False),
    ],
)
def test_media_payload_rejection_classifier(
    error: str,
    expected: bool,
) -> None:
    """Classify payload failures without matching capability errors."""
    assert (
        QwenPawAgent._is_media_payload_rejection_error(RuntimeError(error))
        is expected
    )


@pytest.mark.asyncio
async def test_payload_rejection_without_history_tightens_limits(
    monkeypatch,
) -> None:
    """With no historical block to omit, the retry uses smaller limits.

    Deleting the only image would remove what the user is asking about, so
    the request-scoped limits are halved for one retry and restored
    afterwards.
    """
    cache = get_capability_cache()
    cache.clear()
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="deepseek:deepseek-v4-flash")
    agent.state.context = _current_media_context()
    agent.formatter = _formatter()
    agent.formatter.max_image_side = 8192
    agent.formatter.max_bytes = 2 * 1024 * 1024
    seen: dict[str, int] = {}
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)
        seen["side"] = agent.formatter.max_image_side
        seen["bytes"] = agent.formatter.max_bytes
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    try:
        events = [event async for event in agent._reasoning()]

        assert calls == 2
        assert isinstance(events[-1], Msg)
        assert seen == {"side": 4096, "bytes": 1024 * 1024}
        # The tighter limits are borrowed for that one retry only.
        assert agent.formatter.max_image_side == 8192
        assert agent.formatter.max_bytes == 2 * 1024 * 1024
        assert agent.formatter._qwenpaw_force_strip_media is False
    finally:
        cache.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context_factory", "expected_omitted"),
    [
        (_current_media_context, 0),
        (_tool_media_context, 0),
        (_historical_media_context, 1),
    ],
    ids=["current-media", "tool-media", "historical-media"],
)
async def test_payload_rejection_uses_request_only_retry(
    monkeypatch,
    context_factory,
    expected_omitted,
) -> None:
    """Strip the retry media and mark only historical copies as omitted.

    The active turn keeps its media — the user is asking about it — while
    historical blocks are marked once so later turns stop replaying the same
    rejection. Nothing else in the stored context changes.
    """
    cache = get_capability_cache()
    cache.clear()
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="deepseek:deepseek-v4-flash")
    agent.state.context = context_factory()
    original_context = agent.state.context
    original_dump = _dump_without_omissions(original_context)
    agent.formatter = _formatter()
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)
        # Only the historical copy is omitted; the active-turn block stays,
        # so a retry with history marked is not a media-free request.
        assert agent.formatter._qwenpaw_force_strip_media is (
            expected_omitted == 0
        )
        assert agent.formatter._qwenpaw_force_strip_audio is False
        assert agent.state.context is original_context
        assert len(_omitted_media_ids(agent.state.context)) == expected_omitted
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    try:
        events = [event async for event in agent._reasoning()]

        assert calls == 2
        assert isinstance(events[-1], Msg)
        assert agent.state.context is original_context
        assert len(_omitted_media_ids(agent.state.context)) == expected_omitted
        assert _dump_without_omissions(agent.state.context) == original_dump
        notice = (events[-1].metadata or {}).get("qwenpaw_media_omitted")
        if expected_omitted:
            assert notice == {
                "count": expected_omitted,
                "reason": "provider media limit",
            }
        else:
            assert notice is None
        assert (
            cache.get(
                "deepseek:deepseek-v4-flash",
                "rejects_media",
                False,
            )
            is False
        )
        assert agent.formatter._qwenpaw_force_strip_media is False
    finally:
        cache.clear()


@pytest.mark.asyncio
async def test_failed_payload_retry_preserves_context(monkeypatch) -> None:
    """A failed media-free retry must not corrupt persisted history."""
    agent = _reasoning_agent()
    agent.state.context = _current_media_context()
    original_context = agent.state.context
    original_dump = _dump_context(original_context)
    agent.formatter = _formatter()
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError("retry failed")

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="retry failed"):
        async for _ in agent._reasoning():
            pass

    assert calls == 2
    assert agent.state.context is original_context
    assert _dump_context(agent.state.context) == original_dump
    assert agent.formatter._qwenpaw_force_strip_media is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wire_media_count", "has_formatter"),
    [(0, True), (1, False)],
    ids=["no-wire-media", "no-formatter"],
)
async def test_payload_rejection_without_safe_retry_raises(
    monkeypatch,
    wire_media_count: int,
    has_formatter: bool,
) -> None:
    """Do not retry when the request cannot be safely normalized."""
    agent = _reasoning_agent()
    agent.state.context = _current_media_context()
    original_dump = _dump_context(agent.state.context)
    agent._uses_request_time_media_normalization = lambda: has_formatter
    agent.formatter = _formatter(wire_media_count)
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if tool_choice == "unreachable-test-sentinel":
            yield None
        raise RuntimeError(_DEEPSEEK_UNSUPPORTED_IMAGE_ERROR)

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    with pytest.raises(RuntimeError, match="unsupported image"):
        async for _ in agent._reasoning():
            pass

    assert calls == 1
    assert _dump_context(agent.state.context) == original_dump


def _error(status: int, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error"}},
    )


def _parts(messages: list[dict]) -> list[dict]:
    return [
        part
        for message in messages
        if isinstance(message.get("content"), list)
        for part in message["content"]
    ]


@pytest.fixture
async def video_session(monkeypatch, tmp_path):
    """Use real file-tool output and wire formatting with a mocked server."""
    cache = get_capability_cache()
    cache.clear()
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")
    sent = await send_file_to_user(str(path))
    pixels = BytesIO()
    Image.new("RGB", (2, 2)).save(pixels, format="PNG")
    image_data = base64.b64encode(pixels.getvalue()).decode("ascii")
    image = DataBlock(
        source=Base64Source(media_type="image/png", data=image_data),
    )
    audio = DataBlock(
        source=Base64Source(media_type="audio/mp3", data="YXVkaW8="),
    )
    video = DataBlock(
        source=URLSource(url=path.as_uri(), media_type="video/mp4"),
    )
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(
        model="test-video",
        model_key="test:video",
        formatter=OpenAIChatFormatter(),
    )
    agent.formatter = model_factory._install_model_formatter(agent.model)
    agent.state.context = [
        Msg(name="user", role="user", content=[image, audio, video]),
        Msg(
            name="agent",
            role="assistant",
            content=[
                ToolCallBlock(
                    id="send-1",
                    name="send_file_to_user",
                    input=json.dumps({"file_path": str(path)}),
                ),
                ToolResultBlock(
                    id="send-1",
                    name="send_file_to_user",
                    output=sent.content,
                ),
            ],
        ),
        Msg(name="user", role="user", content=[TextBlock(text="continue")]),
    ]
    session = SimpleNamespace(
        agent=agent,
        cache=cache,
        errors=[],
        requests=[],
        other_media=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_data}"},
            },
            {
                "type": "input_audio",
                "input_audio": {"data": "YXVkaW8=", "format": "mp3"},
            },
        ],
    )

    def respond(request):
        session.requests.append(json.loads(request.content)["messages"])
        if session.errors:
            return session.errors.pop(0)
        return httpx.Response(
            200,
            json={
                "id": "reply",
                "object": "chat.completion",
                "created": 0,
                "model": "test-video",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "done"},
                        "finish_reason": "stop",
                    },
                ],
            },
        )

    async with AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:

        async def provider_reasoning(self, tool_choice=None):
            del tool_choice
            messages = await self.formatter.format(self.state.context)
            response = await client.chat.completions.create(
                model="test-video",
                messages=messages,
            )
            yield Msg(
                name="agent",
                role="assistant",
                content=[TextBlock(text=response.choices[0].message.content)],
            )

        monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)
        try:
            yield session
        finally:
            cache.clear()


def _assert_recovery(session, video_counts, learned):
    snapshots = [
        {
            "videos": model_factory._count_wire_video_blocks(request),
            "other_media": [
                part
                for part in _parts(request)
                if part.get("type") in ("image_url", "input_audio")
            ],
        }
        for request in session.requests
    ]
    assert snapshots == [
        {"videos": count, "other_media": session.other_media}
        for count in video_counts
    ]
    assert {
        key: session.cache.get("test:video", key, False)
        for key in ("rejects_video", "rejects_audio", "rejects_media")
    } == {
        "rejects_video": learned,
        "rejects_audio": False,
        "rejects_media": False,
    }
    assert {
        kind: getattr(
            session.agent.formatter,
            f"_qwenpaw_force_strip_{kind}",
            False,
        )
        for kind in ("video", "audio", "media")
    } == {"video": False, "audio": False, "media": False}


@pytest.mark.parametrize(
    ("status", "message"),
    [(422, _VIDEO_SCHEMA_ERROR), (400, _VIDEO_ZERO_LIMIT)],
    ids=["deepseek-schema", "zero-video-budget"],
)
async def test_video_rejection_recovers_and_next_turn_skips_video(
    video_session,
    status,
    message,
):
    session = video_session
    agent = session.agent
    before = [msg.model_dump() for msg in agent.state.context]
    session.errors.append(_error(status, message))
    first = [event async for event in agent._reasoning()]
    second = [event async for event in agent._reasoning()]

    assert [events[-1].content[0].text for events in (first, second)] == [
        "done",
        "done",
    ]
    _assert_recovery(session, [2, 0, 0], learned=True)
    assert [msg.model_dump() for msg in agent.state.context] == before


@pytest.mark.parametrize("other_type", ["image", "audio"])
async def test_mixed_media_rejection_uses_media_free_retry(
    video_session,
    other_type,
):
    session = video_session
    before = _dump_context(session.agent.state.context)
    session.errors.append(
        _error(
            400,
            f"This model does not support video or {other_type} input",
        ),
    )
    events = [event async for event in session.agent._reasoning()]

    assert events[-1].content[0].text == "done"
    assert [
        [part["type"] for part in _parts(request) if part["type"] != "text"]
        for request in session.requests
    ] == [["image_url", "input_audio", "video_url", "video_url"], []]
    assert _dump_context(session.agent.state.context) == before
    assert {
        key: session.cache.get("test:video", key, False)
        for key in ("rejects_video", "rejects_audio", "rejects_media")
    } == {
        "rejects_video": False,
        "rejects_audio": False,
        "rejects_media": False,
    }
    assert {
        kind: getattr(
            session.agent.formatter,
            f"_qwenpaw_force_strip_{kind}",
            False,
        )
        for kind in ("video", "audio", "media")
    } == {"video": False, "audio": False, "media": False}


async def test_positive_video_limit_does_not_disable_next_valid_input(
    video_session,
):
    session = video_session
    session.errors.append(
        _error(400, "At most 1 video(s) may be provided in one prompt."),
    )
    _ = [event async for event in session.agent._reasoning()]
    # Keep one video, removing the redundant file-delivery exchange.
    session.agent.state.context = session.agent.state.context[:1]
    _ = [event async for event in session.agent._reasoning()]
    _assert_recovery(session, [2, 0, 1], learned=False)


async def test_failed_video_retry_does_not_learn_or_mutate_history(
    video_session,
):
    session = video_session
    before = [msg.model_dump() for msg in session.agent.state.context]
    session.errors.extend(
        [_error(422, _VIDEO_SCHEMA_ERROR), _error(400, "invalid request")],
    )
    with pytest.raises(APIStatusError, match="invalid request"):
        _ = [event async for event in session.agent._reasoning()]
    _assert_recovery(session, [2, 0], learned=False)
    assert [msg.model_dump() for msg in session.agent.state.context] == before


async def test_schema_error_without_wire_video_does_not_retry(video_session):
    session = video_session
    session.agent.state.context = [
        Msg(name="user", role="user", content=[TextBlock(text="hello")]),
    ]
    session.errors.append(_error(422, _VIDEO_SCHEMA_ERROR))
    with pytest.raises(APIStatusError, match="unknown variant"):
        _ = [event async for event in session.agent._reasoning()]
    assert len(session.requests) == 1
    assert session.cache.get("test:video", "rejects_video", False) is False


async def test_cached_audio_and_video_flags_clear_after_unrelated_failure(
    video_session,
):
    session = video_session
    session.cache.learn("test:video", "rejects_video", True)
    session.cache.learn("test:video", "rejects_audio", True)
    session.errors.append(_error(401, "invalid API key"))
    with pytest.raises(APIStatusError, match="invalid API key"):
        _ = [event async for event in session.agent._reasoning()]
    assert len(session.requests) == 1
    assert [
        part
        for part in _parts(session.requests[0])
        if part.get("type") in ("image_url", "input_audio", "video_url")
    ] == session.other_media[:1]
    assert {
        kind: getattr(session.agent.formatter, f"_qwenpaw_force_strip_{kind}")
        for kind in ("video", "audio")
    } == {"video": False, "audio": False}


async def test_video_cache_expires_and_is_scoped_to_model(
    video_session,
    monkeypatch,
):
    session = video_session
    now = [100.0]
    monkeypatch.setattr(
        model_capability_cache.time,
        "monotonic",
        lambda: now[0],
    )
    monkeypatch.setattr(
        model_capability_cache,
        "CAPABILITY_CACHE_TTL_SECONDS",
        1800,
    )
    session.errors.append(_error(422, _VIDEO_SCHEMA_ERROR))
    _ = [event async for event in session.agent._reasoning()]
    session.agent.model.model_key = "test:other-video-model"
    _ = [event async for event in session.agent._reasoning()]
    session.agent.model.model_key = "test:video"
    now[0] += 1801
    _ = [event async for event in session.agent._reasoning()]
    _assert_recovery(session, [2, 0, 2, 2], learned=False)


@pytest.mark.parametrize(
    ("message", "retry", "learn"),
    [
        (_VIDEO_SCHEMA_ERROR, True, True),
        (_VIDEO_ZERO_LIMIT, True, True),
        ("unknown variant `input_video`", True, True),
        ("This model does not support video input", True, True),
        ("video input is not supported", True, True),
        ("At most 2 videos may be provided in one prompt", True, False),
        ("unknown variant `input_audio`, expected `video_url`", False, False),
        ("unknown variant `image_url`", False, False),
        ("invalid video URL", False, False),
        ("video content_safety rejection", False, False),
    ],
)
def test_video_classifier_distinguishes_capability_from_request_limits(
    message,
    retry,
    learn,
):
    error = RuntimeError(message)
    assert {
        "retry": QwenPawAgent._is_video_fallback_error(error),
        "learn": QwenPawAgent._is_video_capability_error(error),
    } == {"retry": retry, "learn": learn}


# ---------------------------------------------------------------------------
# Review follow-ups: retry and omission reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_only_rejection_keeps_historical_images() -> None:
    """``At most 0 video(s)`` is about video; stored images must survive.

    Treating it as a generic media-payload rejection marked every media
    block as omitted, so a follow-up question about the image could no
    longer be answered.
    """
    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    agent._last_wire_request_had_video = lambda: True
    agent._last_wire_request_had_media = lambda: True

    assert agent._is_video_only_media_rejection(
        RuntimeError(_VIDEO_ZERO_LIMIT),
    )
    # A schema that does not know `video_url` is a video-only refusal too.
    assert agent._is_video_only_media_rejection(
        RuntimeError(_VIDEO_SCHEMA_ERROR),
    )
    # An envelope that names only the image variant is not this case: the
    # video was not what the provider refused.
    assert not agent._is_video_only_media_rejection(
        RuntimeError("unknown variant `image_url`"),
    )
    # Neither is a request that carried no video at all.
    agent._last_wire_request_had_video = lambda: False
    assert not agent._is_video_only_media_rejection(
        RuntimeError(_VIDEO_ZERO_LIMIT),
    )


def test_tighten_never_raises_a_limit_toward_its_floor() -> None:
    """A limit already below its floor must not be raised to it.

    ``256 px / 64 KiB`` used to become ``512 px / 128 KiB``, which allows a
    larger image after the provider rejected the previous one.
    """
    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    formatter = _formatter()
    formatter.max_image_side = 256
    formatter.max_bytes = 64 * 1024
    agent._get_active_formatter = lambda: formatter

    assert agent._tighten_media_limits() is None
    assert formatter.max_image_side == 256
    assert formatter.max_bytes == 64 * 1024
    assert (
        getattr(formatter, "_qwenpaw_media_limits_tightened", False) is False
    )


def test_tighten_starts_from_the_rejected_image_side() -> None:
    """A 2000 px image under an 8192 px cap must actually shrink.

    Halving the configured cap to 4096 px left the image untouched, so the
    retry resent byte-for-byte identical data.
    """
    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    formatter = _formatter()
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 2000
    agent._get_active_formatter = lambda: formatter

    saved = agent._tighten_media_limits()

    assert saved == (8192, 2 * 1024 * 1024)
    assert formatter.max_image_side == 1000
    assert formatter.max_bytes == 1024 * 1024


def test_tighten_skips_the_retry_when_only_the_bytes_change() -> None:
    """One limit can still tighten while the other stays put."""
    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    formatter = _formatter()
    formatter.max_image_side = 256
    formatter.max_bytes = 8 * 1024 * 1024
    agent._get_active_formatter = lambda: formatter

    assert agent._tighten_media_limits() == (256, 8 * 1024 * 1024)
    assert formatter.max_image_side == 256
    assert formatter.max_bytes == 4 * 1024 * 1024


@pytest.mark.asyncio
async def test_a_reasoning_iteration_keeps_the_pending_omission_count(
    monkeypatch,
) -> None:
    """A tool call runs another iteration; the notice must survive it."""
    agent = _reasoning_agent()
    agent._media_omission_notice = {
        "count": 2,
        "reason": "provider media limit",
    }

    async def provider_reasoning(self, tool_choice=None):
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="tool called")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    _ = [event async for event in agent._reasoning()]

    assert agent._media_omission_notice == {
        "count": 2,
        "reason": "provider media limit",
    }


def test_every_wire_media_block_is_counted_even_when_unlabelled() -> None:
    """An HTTPS ``image_url`` has no MIME type, but it is still a block.

    Counting labels instead of blocks made two removed media blocks read as
    a single omission.
    """
    from qwenpaw.agents.model_factory import _describe_wire_media_blocks

    blocks = [
        {
            "type": "image_url",
            "image_url": {"url": "https://example.test/a.png"},
        },
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,aGVsbG8="},
        },
    ]

    labels = _describe_wire_media_blocks(blocks)

    assert len(labels) == 2
    assert labels[0].endswith("unknown")


@pytest.mark.asyncio
async def test_the_omission_notice_rides_an_event_consumers_receive():
    """``AgentExecutor`` never forwards the final ``Msg``.

    It drives ``reply_stream`` with the default ``yield_final_msg=False``, and
    the envelope returns nothing at all for ``REPLY_END``. A notice attached
    only to those never reaches Console or a channel, so it rides the same
    streamed events the model-fallback notice rides.
    """
    from agentscope.event import TextBlockDeltaEvent

    from qwenpaw.runtime.envelope import Envelope

    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    agent._media_omission_notice = {
        "count": 2,
        "reason": "provider media limit",
    }

    event = TextBlockDeltaEvent(reply_id="r", block_id="b", delta="ok")
    agent._attach_media_omission_notice(event)

    assert event.metadata["qwenpaw_media_omitted"] == {
        "count": 2,
        "reason": "provider media limit",
    }

    # The envelope is what the executor hands to Console and channels.
    outputs = [obj async for obj in Envelope("s").translate_event(event)]
    assert any(
        "qwenpaw_media_omitted" in (getattr(obj, "metadata", None) or {})
        for obj in outputs
    )


# ---------------------------------------------------------------------------
# Review follow-ups, round 2
# ---------------------------------------------------------------------------


def test_an_image_url_does_not_spend_the_resize_retry() -> None:
    """A forwarded HTTPS image cannot shrink, so tightening must not retry.

    ``image_url`` is sent verbatim, so a smaller limit leaves the payload
    byte for byte identical — that is what produced three requests carrying
    the same URL before the turn failed.
    """
    agent: QwenPawAgent = object.__new__(QwenPawAgent)
    formatter = _formatter()
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 0
    formatter._qwenpaw_last_wire_resizable_images = 0
    agent._get_active_formatter = lambda: formatter

    assert agent._tighten_media_limits() is None
    assert formatter.max_image_side == 8192


def test_audio_and_video_count_limits_are_modality_specific() -> None:
    """These refusals must not reach the generic media path.

    Generic recovery answers a refusal by marking media blocks as omitted,
    which drops the images the user is still asking about.
    """
    for message in (
        "At most 0 audio(s) may be provided in one prompt.",
        "Multiple videos: at most 1 video may be provided.",
        "unknown variant `video_url`",
    ):
        assert QwenPawAgent._is_modality_specific_media_rejection(
            RuntimeError(message),
        ), message

    # A refusal that names images or the payload is the generic path's job.
    for message in (
        "image dimensions exceed the maximum",
        "too many media items",
        "At most 3 images and 2 videos may be provided",
    ):
        assert not QwenPawAgent._is_modality_specific_media_rejection(
            RuntimeError(message),
        ), message


@pytest.mark.asyncio
async def test_the_completed_message_keeps_the_omission_notice():
    """Channels read the notice from the completed message, not the deltas.

    ``Envelope.finalize()`` builds that message from accumulated text, so it
    starts without any metadata. A notice that only rode the deltas reached
    Console consumers and nothing else.
    """
    from agentscope.event import TextBlockDeltaEvent

    from qwenpaw.runtime.envelope import Envelope

    notice = {"count": 2, "reason": "provider media limit"}
    envelope = Envelope("s")
    event = TextBlockDeltaEvent(reply_id="r", block_id="b", delta="ok")
    event.metadata["qwenpaw_media_omitted"] = notice

    _ = [obj async for obj in envelope.translate_event(event)]
    finalized = [obj async for obj in envelope.finalize()]

    completed = [
        obj for obj in finalized if getattr(obj, "object", "") == "message"
    ]
    assert completed, [
        getattr(obj, "object", type(obj).__name__) for obj in finalized
    ]
    assert completed[0].metadata["qwenpaw_media_omitted"] == notice


@pytest.mark.asyncio
async def test_a_successful_resize_does_not_report_an_omission(
    monkeypatch,
) -> None:
    """A smaller rendition removes nothing, so the notice must stay empty.

    The notice counts media that did not reach the model. A 2000 px image
    accepted at 1000 px did reach it, and reporting an omission there told
    the user their image was dropped when it was not.
    """
    cache = get_capability_cache()
    cache.clear()
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="test:media")
    agent.state.context = _current_media_context()
    agent.formatter = _formatter()
    agent.formatter.max_image_side = 8192
    agent.formatter.max_bytes = 2 * 1024 * 1024
    agent.formatter._qwenpaw_last_wire_max_image_side = 2000
    agent._media_omission_notice = None
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("image size exceeds the maximum allowed pixels")
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    events = [event async for event in agent._reasoning()]

    assert calls == 2
    assert events[-1].content[0].text == "recovered"
    assert agent._media_omission_notice is None


def test_a_positive_audio_limit_routes_to_the_audio_handler() -> None:
    """``Multiple audio(s): at most 1`` is an audio count limit.

    The generic media path answers a refusal by marking media blocks as
    omitted, so with one image and two audio clips in history the image
    became unreachable on later turns.
    """
    for message in (
        "Multiple audio(s): at most 1 audio(s) may be provided.",
        "At most 2 audio(s) may be provided in one prompt.",
        "At most 0 audio(s) may be provided in one prompt.",
    ):
        assert QwenPawAgent._is_audio_count_limit_error(
            RuntimeError(message),
        ), message

    # A refusal about images is not this handler's job.
    assert not QwenPawAgent._is_audio_count_limit_error(
        RuntimeError("At most 1 image may be provided in one prompt."),
    )


def test_a_tool_schema_error_is_not_media_recovery() -> None:
    """A failing tool parameter must not mark media as omitted.

    ``code=invalid_function_parameters`` with
    ``param=tools[0].function.parameters`` names the tool schema. The
    classifier matched "image" in ``resize_image`` and "dimensions" in a
    field name, then dropped a valid historical image.
    """
    error = RuntimeError(
        "Error code: 400 - {'error': {'code': "
        "'invalid_function_parameters', 'message': 'Invalid schema for "
        "function resize_image: parameters must have dimensions', "
        "'param': 'tools[0].function.parameters'}}",
    )
    assert not QwenPawAgent._is_media_payload_rejection_error(error)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "animated image is not supported",
        "At most 1 image(s) may be provided in one prompt.",
        "Multiple images: at most 1 image may be provided.",
    ],
)
async def test_media_shape_rejections_skip_the_resize_retry(
    monkeypatch,
    message,
) -> None:
    """Animation and image-count refusals cannot be fixed by resizing.

    The retry used to halve the limits and resend the same payload: an
    animated GIF went out three times unchanged, and a provider allowing
    one image received two images on all three attempts. These refusals
    belong to the bounded media-free fallback instead.
    """
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="test:media")
    agent.state.context = _current_media_context()
    agent.formatter = _formatter()
    agent.formatter.max_image_side = 8192
    agent.formatter.max_bytes = 2 * 1024 * 1024
    agent.formatter._qwenpaw_last_wire_max_image_side = 2000
    agent._media_omission_notice = None
    seen: dict[str, object] = {}
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(message)
        seen["strip"] = agent.formatter._qwenpaw_force_strip_media
        seen["side"] = agent.formatter.max_image_side
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    events = [event async for event in agent._reasoning()]

    assert calls == 2
    assert events[-1].content[0].text == "recovered"
    assert seen["side"] == 8192, "the resize limits must not be tightened"
    assert seen["strip"] is True, "the media-free fallback must run"
    assert (
        getattr(
            agent.formatter,
            "_qwenpaw_media_limits_tightened",
            False,
        )
        is False
    )


@pytest.mark.asyncio
async def test_omitting_history_keeps_the_active_turn_image(
    monkeypatch,
) -> None:
    """Only the historical image is omitted; the current one still goes out.

    The outer retry stripped every media block once any historical block
    was omitted, so a turn with one historical and one current image
    retried with zero images, and the notice counted one loss while two
    left the request.
    """
    from agentscope.message import DataBlock, Base64Source

    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="test:media")
    agent.state.context = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="older"),
                DataBlock(
                    id="hist-image",
                    source=Base64Source(
                        media_type="image/png",
                        data="aGVsbG8=",
                    ),
                ),
            ],
        ),
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="current"),
                DataBlock(
                    id="active-image",
                    source=Base64Source(
                        media_type="image/png",
                        data="d29ybGQ=",
                    ),
                ),
            ],
        ),
    ]
    agent.formatter = _formatter(wire_media_count=2)
    agent._media_omission_notice = None
    seen: dict[str, object] = {}
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("image dimensions exceed the maximum")
        seen["strip"] = agent.formatter._qwenpaw_force_strip_media
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    events = [event async for event in agent._reasoning()]

    assert calls == 2
    assert events[-1].content[0].text == "recovered"
    assert seen["strip"] is False, "the active-turn image must stay"
    assert agent._media_omission_notice == {
        "count": 1,
        "reason": "provider media limit",
    }


@pytest.mark.asyncio
async def test_audio_count_limit_keeps_the_historical_image(
    monkeypatch,
) -> None:
    """An audio-count refusal must not mark the stored image as omitted.

    With one image and two audio clips in history, ``Multiple audio(s):
    at most 1`` used to reach the generic media path, which marked all
    three blocks as omitted. The image then could not be used on the retry
    or on any later turn. The audio-only strip must leave it alone.
    """
    agent = _reasoning_agent()
    agent.model = SimpleNamespace(model_key="test:media")
    agent.state.context = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(type="text", text="look and listen"),
                DataBlock(
                    id="hist-image",
                    source=Base64Source(
                        media_type="image/png",
                        data="aGVsbG8=",
                    ),
                ),
                DataBlock(
                    id="clip-1",
                    source=Base64Source(
                        media_type="audio/mpeg",
                        data="YXVkaW8=",
                    ),
                ),
                DataBlock(
                    id="clip-2",
                    source=Base64Source(
                        media_type="audio/mpeg",
                        data="YXVkaW8=",
                    ),
                ),
            ],
        ),
        Msg(name="user", role="user", content=[TextBlock(text="continue")]),
    ]
    agent.formatter = _formatter(wire_media_count=3)
    agent.formatter._qwenpaw_last_wire_audio_count = 2
    agent._media_omission_notice = None
    seen: dict[str, object] = {}
    calls = 0

    async def provider_reasoning(self, tool_choice=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(
                "Multiple audio(s): at most 1 audio(s) may be provided.",
            )
        seen["audio_strip"] = agent.formatter._qwenpaw_force_strip_audio
        seen["media_strip"] = agent.formatter._qwenpaw_force_strip_media
        seen["omitted"] = len(_omitted_media_ids(agent.state.context))
        yield Msg(
            name="agent",
            role="assistant",
            content=[TextBlock(type="text", text="recovered")],
        )

    monkeypatch.setattr(Agent, "_reasoning", provider_reasoning)

    events = [event async for event in agent._reasoning()]

    assert calls == 2
    assert events[-1].content[0].text == "recovered"
    assert seen["audio_strip"] is True, "audio must be stripped"
    assert seen["media_strip"] is False, "images must not be stripped"
    assert seen["omitted"] == 0, "no media block may be marked as omitted"
    assert agent._media_omission_notice is None


def test_a_later_call_reuses_the_accepted_rendition() -> None:
    """The second model call in a turn must not resend the original image.

    The limits are restored after the call that shrank them, so the next
    call would rebuild the request from the stored bytes at full size. With
    no second shrink allowed it then retried with no image at all; reusing
    the accepted rendition keeps the smaller image in place.
    """
    agent = _reasoning_agent()
    formatter = _formatter()
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 2000
    formatter._qwenpaw_last_wire_resizable_images = 1
    agent.formatter = formatter

    saved = agent._tighten_media_limits()
    assert saved == (8192, 2 * 1024 * 1024)
    assert formatter.max_image_side == 1000

    # The provider accepted that rendition, so the recovery path promotes it
    # before the limits are restored. Without this step the test skipped the
    # real call order and asserted reuse of a target that was never accepted.
    agent._accept_media_rendition()

    agent._restore_media_limits(saved)
    assert formatter.max_image_side == 8192
    formatter._qwenpaw_last_wire_max_image_side = 2000

    reused = agent._tighten_media_limits()

    assert reused is not None, "the accepted rendition must be reused"
    assert formatter.max_image_side == 1000


def test_a_structured_tool_schema_error_is_not_media_recovery() -> None:
    """The failing parameter lives in the body, not in the message.

    An SDK error's text mentions the tool and its fields — ``resize_image``,
    ``dimensions`` — while its body names ``tools[0].function.parameters``.
    Checking only the text marked a valid historical image as omitted.
    """
    exc = RuntimeError(
        "Invalid schema for function resize_image: parameters must have "
        "dimensions",
    )
    exc.body = {
        "error": {
            "code": "invalid_function_parameters",
            "message": (
                "Invalid schema for function resize_image: parameters must "
                "have dimensions"
            ),
            "param": "tools[0].function.parameters",
        },
    }

    assert not QwenPawAgent._is_media_payload_rejection_error(exc)


@pytest.mark.asyncio
async def test_the_inner_recovery_does_not_resize_an_animation(
    monkeypatch,
) -> None:
    """A shape refusal goes straight to the media-free fallback.

    The inner recovery path shrank the limits first, so a 647-byte animated
    GIF was sent twice before being dropped, and a provider allowing one
    image received requests with 2, 2, then 0 images.
    """
    agent = _reasoning_agent()
    agent.state.context = _current_media_context()
    formatter = _formatter()
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 2000
    formatter._qwenpaw_last_wire_resizable_images = 1
    agent.formatter = formatter
    seen: dict[str, object] = {}

    async def fake_prepare():
        return {"messages": [], "tools": []}

    monkeypatch.setattr(agent, "_prepare_model_input", fake_prepare)

    async def retry(*_args, **_kwargs):
        seen["strip"] = formatter._qwenpaw_force_strip_media
        seen["side"] = formatter.max_image_side
        return "retried"

    result = await agent._recover_model_overflow(
        RuntimeError("animated image is not supported"),
        None,
        retry=retry,
    )

    assert result == "retried"
    assert seen["strip"] is True, "media must be dropped, not resized"
    assert seen["side"] == 8192, "the resize step must not run"


# ---------------------------------------------------------------------------
# Resize-target lifetime (review: qbc2016, 2026-11-20)
# ---------------------------------------------------------------------------


def _tightening_agent() -> tuple[QwenPawAgent, SimpleNamespace]:
    """Build an agent whose formatter exposes the request-scoped limits."""
    agent = _agent_with_context([])
    formatter = _formatter()
    formatter.max_image_side = 8192
    formatter.max_bytes = 2 * 1024 * 1024
    agent.formatter = formatter
    return agent, formatter


def _png_bytes(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _noise_png(width: int, height: int) -> bytes:
    """A PNG that barely compresses, so it trips a byte limit with few pixels."""
    image = Image.frombytes(
        "RGB",
        (width, height),
        os.urandom(width * height * 3),
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _sent_side(width: int, limit: int) -> int:
    """The longest side an image carries after one real resize pass.

    The value comes out of ``downscale_image_bytes`` rather than being set by
    hand: the fix under test is exactly that the caller learns the size that
    was sent instead of the source dimensions.
    """
    observed: list[int] = []
    downscale_image_bytes(
        _png_bytes(width, width),
        "image/png",
        max_bytes=0,
        max_side=limit,
        observed_sides=observed,
    )
    assert observed, "the resize pass must report what it carried"
    return observed[0]


def test_the_observed_side_is_the_size_that_was_sent():
    """A shrink reports the outgoing width, not the source width."""
    assert _sent_side(2000, 1000) == 1000
    assert _sent_side(2000, 512) == 512
    # Inside the limit nothing is re-encoded, so source and sent size agree.
    assert _sent_side(300, 8192) == 300


def test_each_refusal_shrinks_below_the_image_that_was_sent():
    """2000 → 1000 → 512, never 2000 → 1000 → 1000."""
    agent, formatter = _tightening_agent()

    formatter._qwenpaw_last_wire_max_image_side = 2000
    assert agent._tighten_media_limits() == (8192, 2 * 1024 * 1024)
    assert formatter.max_image_side == 1000
    # The size stays a guess until a call completes.
    assert getattr(agent, "_media_rendition_target", None) is None
    agent._restore_media_limits((8192, 2 * 1024 * 1024))

    # What the refused request actually carried, produced by the real path.
    formatter._qwenpaw_last_wire_max_image_side = _sent_side(2000, 1000)
    assert agent._tighten_media_limits() == (8192, 2 * 1024 * 1024)
    assert formatter.max_image_side == 512
    agent._restore_media_limits((8192, 2 * 1024 * 1024))

    # At the floor the byte budget can still cut the payload, so the retry
    # stays available instead of dropping the image outright.
    formatter._qwenpaw_last_wire_max_image_side = _sent_side(2000, 512)
    saved = agent._tighten_media_limits()
    assert saved is not None
    assert formatter.max_bytes < 2 * 1024 * 1024
    agent._restore_media_limits(saved)


def test_a_byte_refusal_on_a_small_image_keeps_the_retry():
    """A 500 px PNG refused for its file size still retries, and keeps it."""
    agent, formatter = _tightening_agent()
    # The provider's per-image budget, not our default: 530 kB refuses the
    # ~750 kB file below even though its longest side is only 500 px.
    formatter.max_bytes = 530_000
    formatter._qwenpaw_last_wire_max_image_side = 500

    saved = agent._tighten_media_limits()
    assert saved == (8192, 530_000)
    assert formatter.max_bytes == 265_000
    agent._restore_media_limits(saved)

    # The lower budget really does produce fewer bytes for this file, so the
    # retry carries the image instead of dropping it.
    noisy = _noise_png(500, 500)
    assert len(noisy) > 530_000
    observed: list[int] = []
    out, _ = downscale_image_bytes(
        noisy,
        "image/png",
        max_bytes=265_000,
        max_side=8192,
        observed_sides=observed,
    )
    assert len(out) <= 265_000
    # PNG has no quality knob, so the byte budget is met by halving the side.
    assert max(observed) <= 500


def test_an_accepted_rendition_is_reused_in_the_same_turn():
    """A later call reuses the size the provider already accepted."""
    agent, formatter = _tightening_agent()
    formatter._qwenpaw_last_wire_max_image_side = 2000

    assert agent._tighten_media_limits() == (8192, 2 * 1024 * 1024)
    agent._accept_media_rendition()
    agent._restore_media_limits((8192, 2 * 1024 * 1024))

    assert agent._tighten_media_limits() == (8192, 2 * 1024 * 1024)
    assert formatter.max_image_side == 1000


# ---------------------------------------------------------------------------
# Boundary coverage for the resize/report path
# ---------------------------------------------------------------------------


def _gif_bytes(size: int) -> bytes:
    buffer = BytesIO()
    first = Image.new("RGB", (size, size), "red")
    second = Image.new("RGB", (size, size), "blue")
    first.save(buffer, format="GIF", save_all=True, append_images=[second])
    return buffer.getvalue()


def test_every_image_reports_the_size_it_carries():
    """Multi-image requests report one size per image, not just the largest."""
    observed: list[int] = []
    for size in (300, 900, 1500, 2000):
        downscale_image_bytes(
            _png_bytes(size, size),
            "image/png",
            max_bytes=0,
            max_side=8192,
            observed_sides=observed,
        )
    assert observed == [300, 900, 1500, 2000]


def test_an_animation_reports_its_source_size():
    """Animations are passed through untouched, so their size is unchanged."""
    observed: list[int] = []
    out, mtype = downscale_image_bytes(
        _gif_bytes(400),
        "image/gif",
        max_bytes=0,
        max_side=100,
        observed_sides=observed,
    )
    assert mtype == "image/gif"
    assert observed == [400]


def test_undecodable_bytes_are_returned_untouched():
    """A payload that is not an image is not reported as a resizable one."""
    observed: list[int] = []
    out, _ = downscale_image_bytes(
        b"not an image",
        "image/png",
        max_bytes=0,
        max_side=100,
        observed_sides=observed,
    )
    assert out == b"not an image"
    assert observed == []


def test_an_oversized_image_is_clamped_to_the_limit():
    """A 9000 px image reports the clamped width, not the source width."""
    observed: list[int] = []
    downscale_image_bytes(
        _png_bytes(9000, 100),
        "image/png",
        max_bytes=0,
        max_side=8192,
        observed_sides=observed,
    )
    assert observed == [8192]


def test_the_side_never_climbs_back_after_reaching_the_floor():
    """Refusals keep shrinking; they never send a bigger image than before."""
    agent, formatter = _tightening_agent()
    formatter._qwenpaw_last_wire_max_image_side = 2000

    sequence: list[int] = []
    for _ in range(6):
        saved = agent._tighten_media_limits()
        if saved is None:
            break
        sent = formatter.max_image_side
        sequence.append(sent)
        agent._restore_media_limits(saved)
        formatter._qwenpaw_last_wire_max_image_side = sent

    assert sequence
    assert all(
        later <= earlier for earlier, later in zip(sequence, sequence[1:])
    ), sequence
    assert sequence[-1] == 512


def test_a_disabled_side_limit_still_cuts_bytes():
    """``max_image_side=0`` disables the side limit, not the byte budget."""
    agent, formatter = _tightening_agent()
    formatter.max_image_side = 0
    formatter._qwenpaw_last_wire_max_image_side = 0

    saved = agent._tighten_media_limits()
    assert saved == (0, 2 * 1024 * 1024)
    assert formatter.max_bytes == 1024 * 1024


def test_both_limits_at_their_floor_stop_the_retry():
    """Nothing left to tighten means the caller drops the media instead."""
    agent, formatter = _tightening_agent()
    formatter.max_image_side = 512
    formatter.max_bytes = 128 * 1024
    formatter._qwenpaw_last_wire_max_image_side = 512

    assert agent._tighten_media_limits() is None


def test_nothing_resizable_stops_the_retry():
    """A request with no resizable image has no reason to be retried."""
    agent, formatter = _tightening_agent()
    formatter._qwenpaw_last_wire_resizable_images = 0
    formatter._qwenpaw_last_wire_max_image_side = 2000

    assert agent._tighten_media_limits() is None


def test_accepting_twice_is_a_no_op():
    """A second acceptance must not resurrect the promoted target."""
    agent, formatter = _tightening_agent()
    formatter._qwenpaw_last_wire_max_image_side = 2000

    agent._tighten_media_limits()
    agent._accept_media_rendition()
    agent._accept_media_rendition()

    assert agent._media_rendition_target == (2000, (1000, 1024 * 1024))
    assert agent._media_rendition_pending is None
