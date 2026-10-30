# -*- coding: utf-8 -*-
"""Behavioral contract for Console lifecycle, input and output."""

from __future__ import annotations

import json

import pytest

from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    Event,
    FileContent,
    ImageContent,
    Message,
    RefusalContent,
    RunStatus,
    TextContent,
    VideoContent,
)

from tests.contract.channels import ChannelContractTest


async def reply(_request):
    yield Event(
        object="message",
        status=RunStatus.Completed,
        type="message.completed",
        id="console-reply",
        created_at=1,
        message=Message(role="assistant", content=[TextContent(text="hello")]),
    )


class TestConsoleChannelContract(ChannelContractTest):
    """Ensure ConsoleChannel satisfies the common and Console contracts."""

    @pytest.fixture(autouse=True)
    def isolated_media(self, tmp_path):
        self.media = tmp_path / "media"

    def create_instance(self):
        """Provide a ConsoleChannel instance for contract testing."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        return ConsoleChannel(
            process=reply,
            enabled=True,
            bot_prefix="[TEST] ",
            media_dir=str(self.media),
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )

    def test_default_config_and_policy(self):
        from qwenpaw.app.channels.console.channel import ConsoleChannel
        from qwenpaw.config.config import ConsoleConfig

        channel = ConsoleChannel.from_config(
            reply,
            ConsoleConfig(media_dir=str(self.media)),
        )
        assert channel.enabled is True
        assert channel.bot_prefix == ""
        assert channel.media_dir == self.media
        assert channel.uses_manager_queue is True
        assert channel.dm_policy == channel.group_policy == "open"
        assert channel.allow_from == set()
        assert channel._no_text_debounce is False
        assert channel._display_config.show_tool_calls is True
        assert channel._display_config.show_tool_results is True

    async def test_start_send_and_stop(self, instance, capsys):
        await instance.stop()
        await instance.start()
        await instance.start()
        health = await instance.health_check()
        assert health["channel"] == "console"
        assert health["status"] == "healthy"
        await instance.send("alice", "hello")
        output = capsys.readouterr().out
        assert "[TEST] hello" in output
        assert "alice" in output
        await instance.send("alice", "hi", {"bot_prefix": "Meta:"})
        assert "Meta:hi" in capsys.readouterr().out
        await instance.stop()
        await instance.stop()

    async def test_disabled_channel_does_not_send(self, instance, capsys):
        instance.enabled = False
        await instance.start()
        await instance.send("alice", "hidden")
        await instance.stop()
        assert capsys.readouterr().out == ""
        assert (await instance.health_check())["status"] == "disabled"

    @pytest.mark.parametrize(
        "sender,meta,expected",
        [
            ("u1", None, "console:u1"),
            ("u1", {}, "console:u1"),
            ("u1", {"session_id": "custom-sid"}, "custom-sid"),
            ("", None, "console:"),
        ],
    )
    def test_session_id(self, instance, sender, meta, expected):
        assert instance.resolve_session_id(sender, meta) == expected

    def test_native_request_preserves_metadata(self, instance):
        request = instance.build_agent_request_from_native(
            {
                "channel_id": "console",
                "sender_id": "u1",
                "content_parts": [TextContent(text="hi")],
                "meta": {"k": "v", "request_context": {"foo": "bar"}},
                "message_metadata": {"qwenpaw_client_message_id": "client-2"},
            },
        )
        assert request.channel == "console"
        assert request.user_id == "u1"
        assert request.session_id == "console:u1"
        assert request.channel_meta == {
            "k": "v",
            "request_context": {"foo": "bar"},
        }
        assert request.request_context == {"foo": "bar"}
        empty_request = instance.build_agent_request_from_native(
            {
                "sender_id": "u1",
                "content_parts": [],
                "meta": {"request_context": {"foo": "bar"}},
            },
        )
        assert empty_request.request_context == {"foo": "bar"}
        assert request.input[0].metadata == {
            "qwenpaw_client_message_id": "client-2",
        }
        assert (
            instance.build_agent_request_from_native(None).channel == "console"
        )

    def test_parts_text_and_prefix_override(self, instance):
        instance.bot_prefix = ""
        assert instance._parts_to_text([]) == ""
        parts = [TextContent(text="hello"), TextContent(text="world")]
        assert instance._parts_to_text(parts) == "hello\nworld"
        assert (
            instance._parts_to_text(
                [TextContent(text="msg"), RefusalContent(refusal="refused")],
            )
            == "msg\nrefused"
        )
        instance.bot_prefix = "Bot:"
        assert instance._parts_to_text(parts[:1], {}) == "Bot:  hello"
        assert (
            instance._parts_to_text(
                parts[:1],
                {"bot_prefix": "Meta:"},
            )
            == "Meta:  hello"
        )

    async def test_content_parts_are_output(self, instance, capsys):
        instance._safe_print("hello-print")
        assert "hello-print" in capsys.readouterr().out
        instance._print_parts(
            [
                TextContent(text="abc"),
                RefusalContent(refusal="nope"),
                ImageContent(image_url="http://x/a.png"),
                VideoContent(video_url="http://x/v.mp4"),
            ],
            "message.created",
        )
        output = capsys.readouterr().out
        assert all(
            text in output
            for text in (
                "abc",
                "nope",
                "a.png",
                "v.mp4",
                "message.created",
            )
        )
        await instance.send_content_parts(
            "alice",
            [TextContent(text="first"), TextContent(text="second")],
        )
        output = capsys.readouterr().out
        assert "first" in output and "second" in output
        assert output.index("first") < output.index("second")

    @pytest.mark.parametrize(
        "part",
        [
            TextContent(text="hello"),
            ImageContent(image_url="http://x/a.png"),
            FileContent(file_url="http://x/a.txt"),
            AudioContent(data="http://x/a.mp3"),
        ],
        ids=["text", "image", "file", "audio"],
    )
    def test_complete_submissions_bypass_debounce(self, instance, part):
        parts = [part]
        ok, merged = instance._apply_no_text_debounce("console:u1", parts)
        assert ok is True
        assert merged == parts
        assert not instance._pending_content_by_session
        ok, merged = instance._apply_no_text_debounce(
            "console:u1",
            [TextContent(text="now text")],
        )
        assert ok is True
        assert len(merged) == 1
        assert merged[0].type == ContentType.TEXT

    async def test_inbound_message_streams_final_reply(self, instance):
        events = [
            json.loads(frame.removeprefix("data: "))
            async for frame in instance.stream_one(
                {
                    "sender_id": "alice",
                    "content_parts": [TextContent(text="question")],
                    "meta": {},
                },
            )
        ]
        completed = next(e for e in events if e.get("id") == "console-reply")
        assert completed["status"] == "completed"
        assert completed["message"]["content"][0]["text"] == "hello"
