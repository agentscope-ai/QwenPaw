# -*- coding: utf-8 -*-
"""Regression tests for the round-10 review on the scaffolding filter.

Every case below is taken from the reviewer's six points; each docstring
quotes the sentence it encodes. Tag literals are built from parts so that no
tooling layer can swallow them while this file is written.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from qwenpaw.agents.context.scroll.serialize import (
    ScaffoldDeltaState,
    strip_model_scaffolding,
    strip_scaffold_delta,
)
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.renderer import MessageRenderer
from qwenpaw.schemas import (
    AgentResponse,
    Message,
    MessageType,
    RunStatus,
    TextContent,
)

LT = "<"
GT = ">"
OPEN = f"{LT}thinking{GT}"
CLOSE = f"{LT}/thinking{GT}"
OPEN_SPLIT = f"{LT}thin"
OPEN_TAIL = f"king{GT}"
CLOSE_SPLIT = f"{LT}/thin"
CLOSE_TAIL = f"king{GT}"
PARAM_SHELL = f'{LT}parameter name="count"{GT}3'
PARAM_CLOSED = f'{LT}parameter name="count"{GT}3{LT}/parameter{GT}'


class _Event:
    """Minimal stand-in for an SSE event with an arbitrary object name."""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        object_name: str = "content",
    ) -> None:
        self.object = object_name
        self._payload = payload
        self.delta = payload.get("delta", False)
        self.msg_id = payload.get("msg_id", "m1")
        self.index = payload.get("index", 0)
        self.text = payload.get("text", "")

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self._payload

    def model_dump_json(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False)


def _channel() -> BaseChannel:
    return object.__new__(BaseChannel)


def _msg(*texts: str) -> Message:
    msg = Message(
        type=MessageType.MESSAGE,
        role="assistant",
        content=[TextContent(text=t) for t in texts],
        status=RunStatus.Completed,
    )
    msg.object = "message"
    return msg


def _sse_states(channel: BaseChannel) -> dict[str, Any]:
    states: dict[str, Any] = {}
    message = _msg().in_progress()
    message.id = "m1"
    channel._serialize_event_for_sse(message, states)
    return states


def _feed_stream(chunks: list[str]) -> str:
    state = ScaffoldDeltaState()
    out = []
    for chunk in chunks:
        piece, state = strip_scaffold_delta(chunk, state=state)
        out.append(piece)
    return "".join(out)


# --------------------------------------------------------------------------
# 1. "Ensure filtering is applied to all output channels."
# --------------------------------------------------------------------------
def test_filter_runs_on_non_content_events() -> None:
    """Leak via ``message.completed`` / ``response.output`` style events."""
    channel = _channel()
    event = _msg(f"{OPEN}secret{CLOSE}hello")

    raw = channel._serialize_event_for_sse(event, {})

    assert "secret" not in raw
    assert "hello" in raw


def test_sse_delta_filters_system_injection_blocks() -> None:
    """SSE ``delta`` events must also drop ``system-*`` injection blocks."""
    channel = _channel()
    states = _sse_states(channel)
    raw = channel._serialize_event_for_sse(
        _Event(
            {
                "object": "content",
                "type": "text",
                "delta": True,
                "msg_id": "m1",
                "index": 0,
                "text": "<system-info>\nnoise\n</system-info>hi",
            },
        ),
        states,
    )

    assert "noise" not in raw
    assert "hi" in raw


def test_sse_delta_filters_tool_parameter_shell() -> None:
    """An unclosed tool-parameter wrapper is model-facing, not a reply."""
    channel = _channel()
    states = _sse_states(channel)
    raw = channel._serialize_event_for_sse(
        _Event(
            {
                "object": "content",
                "type": "text",
                "delta": True,
                "msg_id": "m1",
                "index": 0,
                "text": PARAM_SHELL,
            },
        ),
        states,
    )

    assert "parameter" not in raw


# --------------------------------------------------------------------------
# 2. "Fix the streaming state machine."
# --------------------------------------------------------------------------
def test_open_and_close_in_one_chunk_keep_surrounding_text() -> None:
    """``A<thinking>secret</thinking>B`` must yield ``AB``, not ``B``."""
    assert _feed_stream([f"A{OPEN}secret{CLOSE}B"]) == "AB"


def test_reasoning_spanning_chunks_is_not_leaked() -> None:
    """An unclosed tag carried across chunks must not leak reasoning."""
    visible = _feed_stream([f"A{OPEN}secret", " more secret"])

    assert visible == "A"
    assert "secret" not in visible


def test_tag_split_across_chunks_keeps_surrounding_text() -> None:
    visible = _feed_stream(
        [
            f"A{OPEN_SPLIT}",
            f"{OPEN_TAIL}secret",
            CLOSE_SPLIT,
            f"{CLOSE_TAIL}B",
        ],
    )

    assert visible == "AB"


# --------------------------------------------------------------------------
# 3. "Implement filtering that persists across text blocks."
# --------------------------------------------------------------------------
def test_reasoning_spanning_text_blocks_is_hidden() -> None:
    """A block may end mid-reasoning and the next one close it."""
    renderer = MessageRenderer()
    parts = renderer.message_to_parts(
        _msg(f"{OPEN}secret", f"tail{CLOSE}answer"),
    )

    rendered = "".join(p.text for p in parts if getattr(p, "text", None))

    assert rendered == "answer"
    assert "secret" not in rendered


def test_history_playback_shares_one_scan_per_message() -> None:
    """History blocks are cleaned with the same per-message state."""
    from qwenpaw.agents.context.scroll.scaffold_filter import ScaffoldFilter
    from qwenpaw.app.chats.utils import clean_display_text

    state = ScaffoldFilter()
    first = clean_display_text(f"{OPEN}secret", "assistant", state=state)
    second = clean_display_text(f"tail{CLOSE}answer", "assistant", state=state)

    assert first == ""
    assert second == "answer"


# --------------------------------------------------------------------------
# 4. "Prevent the accidental deletion of valid responses and code examples."
# --------------------------------------------------------------------------
def test_streaming_keeps_literal_tags_inside_a_blockquote() -> None:
    text = f"> {OPEN}quoted example{CLOSE}"
    assert _feed_stream([text]) == text


@pytest.mark.parametrize(
    "text",
    [
        f"``{OPEN}x{CLOSE}``",
        f"~~~python\n{OPEN}x{CLOSE}\n~~~",
        f"    {OPEN}x{CLOSE}\n",
    ],
)
def test_non_streaming_keeps_literal_tags_inside_code(text: str) -> None:
    assert strip_model_scaffolding(text) == text


def test_closed_parameter_tag_is_not_treated_as_a_tool_call() -> None:
    assert strip_model_scaffolding(PARAM_CLOSED) == PARAM_CLOSED


# --------------------------------------------------------------------------
# 5. "Ensure compatibility with CRLF line endings."
# --------------------------------------------------------------------------
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_valid_response_before_an_inline_reasoning_marker_survives(
    newline: str,
) -> None:
    text = f"valid response{newline}{newline}internal reasoning{CLOSE}"
    assert _feed_stream([text]) == "valid response"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_valid_response_survives_when_rendered(newline: str) -> None:
    text = f"valid response{newline}{newline}internal reasoning{CLOSE}"
    renderer = MessageRenderer()
    parts = renderer.message_to_parts(_msg(text))

    rendered = "".join(p.text for p in parts if getattr(p, "text", None))

    assert rendered == "valid response"


# --------------------------------------------------------------------------
# 6. "Eliminate quadratic-time complexity in regular expression scanning."
# --------------------------------------------------------------------------
def _elapsed(payload: str) -> float:
    start = time.perf_counter()
    strip_model_scaffolding(payload)
    return time.perf_counter() - start


def test_many_unclosed_tags_do_not_scan_quadratically() -> None:
    small = OPEN * (56 * 1024 // len(OPEN))
    large = OPEN * (112 * 1024 // len(OPEN))

    _elapsed(small)  # warm-up
    small_s = _elapsed(small)
    large_s = _elapsed(large)

    assert small_s < 0.35, f"56 KB took {small_s:.3f}s"
    assert large_s < 0.80, f"112 KB took {large_s:.3f}s"
    assert (
        large_s < small_s * 3.5 + 0.05
    ), f"looks quadratic: {small_s:.3f}s -> {large_s:.3f}s"


# --------------------------------------------------------------------------
# 7. "The issues regarding ... incorrect exits from code blocks must be
#     resolved before this PR can be merged."
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fence", ["`", "~"])
def test_fence_closes_and_later_reasoning_is_still_removed(fence: str) -> None:
    """A closed fence must not turn the rest of the message into code."""
    marker = fence * 3
    text = f"{marker}\ncode\n{marker}\nafter {OPEN}secret{CLOSE}reply"

    assert (
        strip_model_scaffolding(text)
        == f"{marker}\ncode\n{marker}\nafter reply"
    )


@pytest.mark.parametrize("fence", ["`", "~"])
def test_tags_inside_a_fence_stay_verbatim(fence: str) -> None:
    """The mirror case: the fence opening must not be undone too early."""
    marker = fence * 3
    text = f"{marker}\n{OPEN}not reasoning{CLOSE}\n{marker}"

    assert strip_model_scaffolding(text) == text


def test_unclosed_fence_keeps_the_remainder_verbatim() -> None:
    """Without a closing fence the rest of the text is still code."""
    text = f"```\ncode\n{OPEN}still code{CLOSE}"

    assert strip_model_scaffolding(text) == text


def test_fence_state_survives_a_chunk_boundary() -> None:
    """The closing fence may arrive in its own delta."""
    state = ScaffoldDeltaState()
    out = ""
    for chunk in (
        "```\n",
        "code\n",
        "```\n",
        f"after {OPEN}sec",
        f"ret{CLOSE}reply",
    ):
        piece, state = strip_scaffold_delta(chunk, state=state)
        out += piece

    assert out == "```\ncode\n```\nafter reply"


def test_default_reply_path_filters_scaffolding() -> None:
    """Channels that send the extracted text directly never see the renderer."""
    channel = _channel()
    response = AgentResponse(
        output=[_msg(f"{OPEN}secret{CLOSE}hello")],
        status=RunStatus.Completed,
    )

    assert channel._response_to_text(response) == "hello"


def test_default_reply_path_filters_injected_context() -> None:
    """The same egress carries injected notes, not only reasoning blocks."""
    channel = _channel()
    response = AgentResponse(
        output=[_msg(f"{LT}system-warning{GT}w{LT}/system-warning{GT}answer")],
        status=RunStatus.Completed,
    )

    assert channel._response_to_text(response) == "answer"


# --------------------------------------------------------------------------
# 12th review · three regression cases run through the real egress points.
# --------------------------------------------------------------------------
OPEN_INFO = f"{LT}system-info{GT}"
CLOSE_INFO = f"{LT}/system-info{GT}"


@pytest.fixture
def streaming_channel(tmp_path):
    """Real channel whose streaming hooks record instead of delivering."""
    from unittest.mock import MagicMock

    from qwenpaw.app.channels.console.channel import ConsoleChannel

    class SpyChannel(ConsoleChannel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.start_calls: list[tuple[str, str]] = []
            self.end_calls: list[tuple[str, str]] = []
            self.delta_calls: list[tuple[str, str]] = []

        async def on_streaming_start(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text: str = "",
        ):
            self.start_calls.append((stream_type, accumulated_text))

        async def on_streaming_end(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text: str = "",
        ):
            self.end_calls.append((stream_type, accumulated_text))

        async def on_streaming_delta(
            self,
            request,
            to_handle,
            event,
            send_meta,
            stream_type,
            accumulated_text: str = "",
        ):
            self.delta_calls.append((stream_type, accumulated_text))

    channel = SpyChannel(
        process=MagicMock(),
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path),
    )
    channel._STREAM_DELTA_MIN_INTERVAL_S = 999.0
    return channel


@pytest.mark.asyncio
async def test_streaming_hooks_show_only_the_public_reply(
    streaming_channel,
) -> None:
    """``secretPublic.`` reaches delta/end as ``Public.`` only."""
    from types import SimpleNamespace

    request = SimpleNamespace(
        user_id="u",
        session_id="console:u",
        channel="console",
    )
    send_meta: dict[str, Any] = {}
    buffers = {"message": ""}
    mapping = {"m1": "message"}
    full = f"{OPEN}secret{CLOSE}Public."

    for chunk in (f"{OPEN}secret", f"{CLOSE}Public."):
        await streaming_channel._on_stream_content_delta(
            request,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text=chunk),
            send_meta,
            mapping,
            buffers,
        )

    # The accumulated raw text stays untouched while the display is filtered.
    assert buffers["message"] == full

    await streaming_channel._on_stream_msg_end(
        request,
        "u",
        SimpleNamespace(
            type="message",
            id="m1",
            content=[SimpleNamespace(text=full)],
        ),
        send_meta,
        mapping,
        buffers,
    )

    assert streaming_channel.end_calls[-1][1] == "Public."
    assert all(
        "secret" not in text for _, text in streaming_channel.delta_calls
    )


@pytest.mark.asyncio
async def test_streaming_hooks_hide_scaffolding_across_content_indexes(
    streaming_channel,
) -> None:
    from types import SimpleNamespace

    request = SimpleNamespace(user_id="u", session_id="console:u")
    send_meta: dict[str, Any] = {}
    buffers = {"message": ""}
    mapping = {"m1": "message"}
    chunks = (f"{OPEN}private start", "private middle", f"{CLOSE}Public.")
    for index, text in enumerate(chunks):
        await streaming_channel._on_stream_content_delta(
            request,
            "u",
            TextContent(delta=True, msg_id="m1", index=index, text=text),
            send_meta,
            mapping,
            buffers,
        )

    await streaming_channel._on_stream_msg_end(
        request,
        "u",
        _msg(*chunks),
        send_meta,
        mapping,
        buffers,
    )

    assert streaming_channel.end_calls[-1][1] == "Public."
    for _, text in streaming_channel.delta_calls + streaming_channel.end_calls:
        assert "private" not in text


def test_sse_injected_block_across_three_chunks() -> None:
    """An injected block split over three deltas hides as one block."""
    channel = _channel()
    states = _sse_states(channel)
    visible: list[str] = []

    for chunk in (OPEN_INFO, "`secret`", f"{CLOSE_INFO}Public."):
        raw = channel._serialize_event_for_sse(
            _Event(
                {
                    "object": "content",
                    "type": "text",
                    "delta": True,
                    "msg_id": "m1",
                    "index": 0,
                    "text": chunk,
                },
            ),
            states,
        )
        visible.append(json.loads(raw)["text"])

    assert "".join(visible) == "Public."


def test_sse_code_examples_survive_chunk_splitting() -> None:
    """Quoted tags survive, and the quote state survives the chunk break.

    Dropping the scanner between deltas loses the open backtick run and the
    open fence, so the next fragment re-enters as prose and the tag literals
    inside the example get stripped.
    """
    channel = _channel()
    states = _sse_states(channel)
    chunks = [
        "Inline `",
        "<thin",
        "king>x</thin",
        "king>` done\n```\n",
        "<thin",
        "king>code</thin",
        "king>\n```\ntail",
    ]
    visible: list[str] = []

    for chunk in chunks:
        raw = channel._serialize_event_for_sse(
            _Event(
                {
                    "object": "content",
                    "type": "text",
                    "delta": True,
                    "msg_id": "m1",
                    "index": 0,
                    "text": chunk,
                },
            ),
            states,
        )
        visible.append(json.loads(raw)["text"])

    assert "".join(visible) == "".join(chunks)
