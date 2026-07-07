# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.channels.console.channel.ConsoleChannel.

Focuses on the *local* ConsoleChannel helpers (start/stop/send, session
resolution, parts rendering). Heavy streaming pipeline behavior is covered
elsewhere; here we exercise pure helpers and async lifecycle methods.
"""

from __future__ import annotations

# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison,unused-import  # noqa: E501

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.schemas import (
    ContentType,
    ImageContent,
    Message,
    MessageType,
    RefusalContent,
    RunStatus,
    TextContent,
    VideoContent,
)


@pytest.fixture
def console_channel(tmp_path: Path):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    return ConsoleChannel(
        process=MagicMock(),
        enabled=True,
        bot_prefix="",
        media_dir=str(tmp_path),
    )


@pytest.fixture
def disabled_console_channel(tmp_path: Path):
    from qwenpaw.app.channels.console.channel import ConsoleChannel

    return ConsoleChannel(
        process=MagicMock(),
        enabled=False,
        bot_prefix="",
        media_dir=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# resolve_session_id
# ---------------------------------------------------------------------------


class TestResolveSessionId:
    def test_default_format(self, console_channel):
        assert console_channel.resolve_session_id("u1") == "console:u1"

    def test_meta_session_overrides(self, console_channel):
        assert (
            console_channel.resolve_session_id(
                "u1",
                {"session_id": "custom-sid"},
            )
            == "custom-sid"
        )

    def test_empty_meta_uses_default(self, console_channel):
        assert console_channel.resolve_session_id("u1", {}) == "console:u1"

    def test_empty_sender(self, console_channel):
        assert console_channel.resolve_session_id("") == "console:"


# ---------------------------------------------------------------------------
# _parts_to_text
# ---------------------------------------------------------------------------


class TestPartsToText:
    def test_empty(self, console_channel):
        assert console_channel._parts_to_text([]) == ""

    def test_text_only(self, console_channel):
        parts = [TextContent(text="hello"), TextContent(text="world")]
        assert console_channel._parts_to_text(parts) == "hello\nworld"

    def test_refusal_included(self, console_channel):
        parts = [
            TextContent(text="msg"),
            RefusalContent(refusal="refused"),
        ]
        assert "msg" in console_channel._parts_to_text(parts)
        assert "refused" in console_channel._parts_to_text(parts)

    def test_bot_prefix_applied(self, console_channel):
        console_channel.bot_prefix = "Bot:"
        parts = [TextContent(text="hello")]
        assert console_channel._parts_to_text(parts, {}) == "Bot:  hello"

    def test_meta_prefix_overrides(self, console_channel):
        console_channel.bot_prefix = "Bot:"
        parts = [TextContent(text="hello")]
        # meta carries bot_prefix → should override instance prefix
        assert (
            console_channel._parts_to_text(parts, {"bot_prefix": "Meta:"})
            == "Meta:  hello"
        )


# ---------------------------------------------------------------------------
# build_agent_request_from_native
# ---------------------------------------------------------------------------


class TestBuildAgentRequestFromNative:
    def test_basic_payload(self, console_channel):
        payload = {
            "channel_id": "console",
            "sender_id": "u1",
            "content_parts": [TextContent(text="hi")],
            "meta": {"k": "v"},
        }
        req = console_channel.build_agent_request_from_native(payload)
        assert req.channel == "console"
        assert req.user_id == "u1"
        assert req.session_id == "console:u1"
        assert req.channel_meta == {"k": "v"}

    def test_meta_request_context_propagated(self, console_channel):
        payload = {
            "sender_id": "u1",
            "content_parts": [],
            "meta": {"request_context": {"foo": "bar"}},
        }
        req = console_channel.build_agent_request_from_native(payload)
        assert req.request_context == {"foo": "bar"}

    def test_non_dict_payload_returns_empty_request(
        self,
        console_channel,
    ):
        req = console_channel.build_agent_request_from_native(None)
        assert req.channel == "console"


# ---------------------------------------------------------------------------
# _print_parts — output capture (no exception = pass)
# ---------------------------------------------------------------------------


class TestPrintHelpers:
    def test_safe_print_handles_stdout(self, console_channel, capsys):
        console_channel._safe_print("hello-print")
        captured = capsys.readouterr()
        assert "hello-print" in captured.out

    def test_print_parts_emits_text(self, console_channel, capsys):
        parts = [TextContent(text="abc")]
        console_channel._print_parts(parts, "message.created")
        captured = capsys.readouterr()
        assert "abc" in captured.out

    def test_print_parts_handles_refusal(self, console_channel, capsys):
        parts = [RefusalContent(refusal="nope")]
        console_channel._print_parts(parts)
        out = capsys.readouterr().out
        assert "nope" in out

    def test_print_parts_handles_media(self, console_channel, capsys):
        parts = [
            ImageContent(image_url="http://x/a.png"),
            VideoContent(video_url="http://x/v.mp4"),
        ]
        console_channel._print_parts(parts)
        out = capsys.readouterr().out
        assert "a.png" in out
        assert "v.mp4" in out


# ---------------------------------------------------------------------------
# Lifecycle: start / stop / health_check
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_when_enabled(self, console_channel):
        await console_channel.start()
        # Idempotent: second start does nothing harmful
        await console_channel.start()

    @pytest.mark.asyncio
    async def test_stop_when_enabled(self, console_channel):
        await console_channel.stop()

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, disabled_console_channel):
        await disabled_console_channel.start()

    @pytest.mark.asyncio
    async def test_stop_when_disabled(self, disabled_console_channel):
        await disabled_console_channel.stop()

    @pytest.mark.asyncio
    async def test_health_check_enabled(self, console_channel):
        h = await console_channel.health_check()
        assert h["channel"] == "console"
        assert h["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, disabled_console_channel):
        h = await disabled_console_channel.health_check()
        assert h["status"] == "disabled"


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


class TestSend:
    @pytest.mark.asyncio
    async def test_send_prints_text(self, console_channel, capsys):
        await console_channel.send("u1", "hello there")
        out = capsys.readouterr().out
        assert "hello there" in out
        assert "u1" in out

    @pytest.mark.asyncio
    async def test_send_disabled_noop(self, disabled_console_channel, capsys):
        await disabled_console_channel.send("u1", "should not print")
        out = capsys.readouterr().out
        assert out == ""

    @pytest.mark.asyncio
    async def test_send_with_bot_prefix(self, console_channel, capsys):
        console_channel.bot_prefix = "Bot:"
        await console_channel.send("u1", "hi", {"bot_prefix": "Bot:"})
        out = capsys.readouterr().out
        assert "Bot:hi" in out.replace(" ", "") or "Bot:" in out


# ---------------------------------------------------------------------------
# No-text debounce
# ---------------------------------------------------------------------------


class TestNoTextDebounce:
    def test_text_passes_through(self, console_channel):
        parts = [TextContent(text="hello")]
        ok, merged = console_channel._apply_no_text_debounce(
            "console:u1",
            parts,
        )
        assert ok is True
        assert merged == parts

    def test_no_text_buffers(self, console_channel):
        parts = [ImageContent(image_url="http://x/a.png")]
        ok, merged = console_channel._apply_no_text_debounce(
            "console:u1",
            parts,
        )
        assert ok is False
        assert merged == []
        assert "console:u1" in console_channel._pending_content_by_session

    def test_text_after_buffer_merges(self, console_channel):
        img = ImageContent(image_url="http://x/a.png")
        console_channel._apply_no_text_debounce("console:u1", [img])
        ok, merged = console_channel._apply_no_text_debounce(
            "console:u1",
            [TextContent(text="now text")],
        )
        assert ok is True
        assert len(merged) == 2
        assert merged[0].type == ContentType.IMAGE
        assert merged[1].type == ContentType.TEXT

    def test_audio_bypasses_debounce(self, console_channel):
        from qwenpaw.schemas import AudioContent

        audio = AudioContent(data="http://x/a.mp3")
        ok, merged = console_channel._apply_no_text_debounce(
            "console:u1",
            [audio],
        )
        assert ok is True
        assert len(merged) == 1
