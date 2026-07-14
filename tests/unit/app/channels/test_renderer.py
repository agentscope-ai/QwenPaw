# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.renderer + streaming chunk splitting.

Covers:
- RenderStyle configuration & MessageRenderer.message_to_parts
- parts_to_text merging (text + media fallback)
- Streaming chunk splitting behavior (historical issue:
  multi-segment streaming merged → fixed via content_index split in
  BaseChannel._on_stream_content_delta). The streaming logic lives in
  BaseChannel, exercised here through ConsoleChannel which inherits it.
"""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.app.channels.renderer import (
    MessageRenderer,
    RenderStyle,
    _fmt_code_block,
    _fmt_tool_call,
    _fmt_tool_output_label,
)
from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    Message,
    MessageType,
    RefusalContent,
    RunStatus,
    TextContent,
    VideoContent,
)

# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------


class TestRenderStyle:
    def test_defaults(self):
        s = RenderStyle()
        assert s.show_tool_details
        assert s.supports_markdown
        assert s.supports_code_fence
        assert s.use_emoji
        assert not s.filter_tool_messages
        assert not s.filter_thinking
        assert s.internal_tools == frozenset()

    def test_custom(self):
        s = RenderStyle(use_emoji=False, supports_markdown=False)
        assert not s.use_emoji
        assert not s.supports_markdown


class TestFormatHelpers:
    def test_fmt_tool_call_emoji_markdown(self):
        s = RenderStyle()
        out = _fmt_tool_call("ls", "-la", s)
        assert "🔧" in out
        assert "**ls**" in out
        assert "```" in out

    def test_fmt_tool_call_no_emoji(self):
        s = RenderStyle(use_emoji=False)
        out = _fmt_tool_call("ls", "-la", s)
        assert "🔧" not in out
        assert "**ls**" in out

    def test_fmt_tool_call_no_markdown(self):
        s = RenderStyle(use_emoji=False, supports_markdown=False)
        out = _fmt_tool_call("ls", "-la", s)
        assert out.startswith("ls\n")

    def test_fmt_tool_call_plain(self):
        s = RenderStyle(
            use_emoji=False,
            supports_markdown=False,
            supports_code_fence=False,
        )
        out = _fmt_tool_call("ls", "-la", s)
        assert out == "ls: -la"

    def test_fmt_tool_output_label_emoji(self):
        s = RenderStyle()
        assert _fmt_tool_output_label("grep", s).startswith("✅ **grep**:")

    def test_fmt_tool_output_label_markdown_only(self):
        s = RenderStyle(use_emoji=False)
        assert _fmt_tool_output_label("grep", s) == "**grep**:"

    def test_fmt_tool_output_label_plain(self):
        s = RenderStyle(use_emoji=False, supports_markdown=False)
        assert _fmt_tool_output_label("grep", s) == "grep:"

    def test_fmt_code_block_with_fence(self):
        s = RenderStyle()
        assert "```" in _fmt_code_block("x", s)

    def test_fmt_code_block_no_fence(self):
        s = RenderStyle(supports_code_fence=False)
        assert "```" not in _fmt_code_block("x", s)


# ---------------------------------------------------------------------------
# MessageRenderer.message_to_parts
# ---------------------------------------------------------------------------


def _mk_message(
    content: list,
    msg_type: MessageType = MessageType.MESSAGE,
) -> Message:
    msg = Message(
        type=msg_type,
        role="assistant",
        content=content,
        status=RunStatus.Completed,
    )
    msg.object = "message"
    return msg


class TestMessageToParts:
    def test_text_content(self):
        r = MessageRenderer()
        msg = _mk_message([TextContent(text="hello")])
        parts = r.message_to_parts(msg)
        assert len(parts) == 1
        assert parts[0].text == "hello"

    def test_refusal_content(self):
        r = MessageRenderer()
        msg = _mk_message(
            [TextContent(text="x"), RefusalContent(refusal="no")],
        )
        parts = r.message_to_parts(msg)
        refusals = [
            p for p in parts if getattr(p, "type", None) == ContentType.REFUSAL
        ]
        assert len(refusals) == 1
        assert refusals[0].refusal == "no"

    def test_empty_content_with_msg_type_returns_placeholder(self):
        r = MessageRenderer()
        msg = _mk_message([])
        parts = r.message_to_parts(msg)
        assert len(parts) == 1
        assert parts[0].text.startswith("[Message type:")

    def test_image_content_passthrough(self):
        r = MessageRenderer()
        msg = _mk_message([ImageContent(image_url="http://x/a.png")])
        parts = r.message_to_parts(msg)
        assert any(
            getattr(p, "type", None) == ContentType.IMAGE for p in parts
        )

    def test_video_content_passthrough(self):
        r = MessageRenderer()
        msg = _mk_message([VideoContent(video_url="http://x/v.mp4")])
        parts = r.message_to_parts(msg)
        assert any(
            getattr(p, "type", None) == ContentType.VIDEO for p in parts
        )

    def test_audio_content_passthrough(self):
        r = MessageRenderer()
        msg = _mk_message([AudioContent(data="http://x/a.mp3")])
        parts = r.message_to_parts(msg)
        assert any(
            getattr(p, "type", None) == ContentType.AUDIO for p in parts
        )

    def test_file_content_passthrough(self):
        r = MessageRenderer()
        msg = _mk_message([FileContent(file_url="http://x/f.txt")])
        parts = r.message_to_parts(msg)
        assert any(getattr(p, "type", None) == ContentType.FILE for p in parts)

    def test_filter_thinking_drops_reasoning(self):
        r = MessageRenderer(RenderStyle(filter_thinking=True))
        msg = _mk_message([TextContent(text="r")], MessageType.REASONING)
        assert r.message_to_parts(msg) == []

    def test_filter_thinking_keeps_message(self):
        r = MessageRenderer(RenderStyle(filter_thinking=True))
        msg = _mk_message([TextContent(text="hi")], MessageType.MESSAGE)
        parts = r.message_to_parts(msg)
        assert len(parts) == 1

    def test_function_call_filter_tool_messages(self):
        r = MessageRenderer(RenderStyle(filter_tool_messages=True))
        msg = _mk_message([], MessageType.FUNCTION_CALL)
        assert r.message_to_parts(msg) == []


# ---------------------------------------------------------------------------
# parts_to_text
# ---------------------------------------------------------------------------


class TestPartsToText:
    def test_text_only(self):
        r = MessageRenderer()
        out = r.parts_to_text([TextContent(text="a"), TextContent(text="b")])
        assert "a" in out and "b" in out

    def test_prefix_prepended(self):
        r = MessageRenderer()
        out = r.parts_to_text([TextContent(text="body")], prefix="Bot:")
        assert out.startswith("Bot:")

    def test_image_fallback_annotation(self):
        r = MessageRenderer()
        out = r.parts_to_text(
            [TextContent(text="see"), ImageContent(image_url="u.png")],
        )
        assert "[Image: u.png]" in out

    def test_video_fallback_annotation(self):
        r = MessageRenderer()
        out = r.parts_to_text([VideoContent(video_url="v.mp4")])
        assert "[Video: v.mp4]" in out

    def test_file_fallback_annotation(self):
        r = MessageRenderer()
        out = r.parts_to_text([FileContent(file_url="f.txt")])
        assert "[File: f.txt]" in out

    def test_audio_fallback_annotation(self):
        r = MessageRenderer()
        out = r.parts_to_text([AudioContent(data="x")])
        assert "[Audio]" in out

    def test_refusal_emitted_as_text(self):
        r = MessageRenderer()
        out = r.parts_to_text([RefusalContent(refusal="blocked")])
        assert "blocked" in out


# ---------------------------------------------------------------------------
# Streaming chunk splitting (historical: multi-segment streaming merged)
# ---------------------------------------------------------------------------

# We spawn ConsoleChannel with a tmp work dir; streaming logic is on
# BaseChannel and inherited. Override async hooks to capture segment
# boundaries.


@pytest.fixture
def streaming_channel(tmp_path):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    class SpyChannel(ConsoleChannel):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
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

    ch = SpyChannel(
        process=MagicMock(),
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path),
    )
    # Disable flush throttle so logic-path runs instantly in tests
    ch._STREAM_DELTA_MIN_INTERVAL_S = 999.0
    return ch


class TestStreamingChunkSplitting:
    @pytest.mark.asyncio
    async def test_single_segment_accumulates(self, streaming_channel):
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "message"}
        buffers = {"message": ""}

        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text="hello"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text=" world"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        # No split yet — single segment
        assert streaming_channel.end_calls == []
        assert buffers["message"] == "hello world"

    @pytest.mark.asyncio
    async def test_content_index_change_triggers_split(
        self,
        streaming_channel,
    ):
        """Historical bug: multi-segment streaming merged into one box.

        Fix: when content_index changes mid-stream, finalize the current
        segment via on_streaming_end(accumulated_old) and start a fresh
        segment via on_streaming_start(accumulated='').
        """
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "message"}
        buffers = {"message": ""}

        # Segment 1 (index=0): "hello world"
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text="hello"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text=" world"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        # Segment 2 (index=1): "second"
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=1, text="second"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )

        # First segment finalized with its accumulated text
        assert ("message", "hello world") in streaming_channel.end_calls
        # New segment started with empty accumulated text
        assert ("message", "") in streaming_channel.start_calls
        # Buffer reset and now holds only the second segment's text
        assert buffers["message"] == "second"

    @pytest.mark.asyncio
    async def test_filter_thinking_skips_reasoning_delta(
        self,
        streaming_channel,
    ):
        streaming_channel._filter_thinking = True
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "reasoning"}
        buffers = {"reasoning": ""}

        # First call seeds the buffer entry for "reasoning"
        consumed = await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text="skip me"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        # Reasoning is filtered: should not accumulate, returns True
        assert consumed is True
        # No flush fired because filter short-circuits before flush
        assert streaming_channel.delta_calls == []
        # Buffer untouched (still empty)
        assert buffers["reasoning"] == ""

    @pytest.mark.asyncio
    async def test_non_delta_event_returns_false(
        self,
        streaming_channel,
    ):
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "message"}
        buffers = {"message": ""}

        consumed = await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=False, msg_id="m1", index=0, text="hi"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        assert consumed is False
        assert buffers["message"] == ""

    @pytest.mark.asyncio
    async def test_unknown_msg_id_returns_false(
        self,
        streaming_channel,
    ):
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "message"}
        buffers = {"message": ""}

        consumed = await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="unknown", index=0, text="x"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        assert consumed is False

    @pytest.mark.asyncio
    async def test_index_change_then_back_does_not_spuriously_split(
        self,
        streaming_channel,
    ):
        """Going back to previous index after a split must not fire an empty
        segment-end. Regression guard for the historical merge issue."""
        req = SimpleNamespace(
            user_id="u",
            session_id="console:u",
            channel="console",
        )
        send_meta: dict = {}
        msg_id_to_stream_type = {"m1": "message"}
        buffers = {"message": ""}

        # First segment, index 0
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text="a"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        # Move to index 1 → triggers split
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=1, text="b"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        ends_after_first_split = len(streaming_channel.end_calls)

        # Now index 0 again with EMPTY buffer would be a "new" segment;
        # since buffer is non-empty ("b"), it would split again. Confirm
        # split fires only when buffer is non-empty.
        # Move to index 0 → should split again (buffer "b" non-empty)
        await streaming_channel._on_stream_content_delta(
            req,
            "u",
            SimpleNamespace(delta=True, msg_id="m1", index=0, text="c"),
            send_meta,
            msg_id_to_stream_type,
            buffers,
        )
        assert len(streaming_channel.end_calls) == ends_after_first_split + 1
        assert buffers["message"] == "c"
