# -*- coding: utf-8 -*-

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel


class RecordingTransport:
    def __init__(self):
        self.payloads = []

    async def send_json(self, payload):
        self.payloads.append(payload)


def test_send_uses_active_send_command_when_transport_present() -> None:
    transport = RecordingTransport()
    channel = WeComChannel(sender=None, transport=transport, bot_prefix="")

    asyncio.run(channel.send("wecom:user:alice", "hello", meta={}))

    assert transport.payloads[0]["cmd"] == "aibot_send_msg"
    assert transport.payloads[0]["body"]["chatid"] == "alice"
    assert transport.payloads[0]["body"]["chat_type"] == 1
    assert transport.payloads[0]["body"]["msgtype"] == "markdown"


def test_send_response_uses_respond_command_when_req_id_present() -> None:
    transport = RecordingTransport()
    channel = WeComChannel(sender=None, transport=transport, bot_prefix="")
    channel._new_request_id = lambda: "stream-1"

    asyncio.run(
        channel.send(
            "wecom:user:alice",
            "reply",
            meta={"req_id": "req-5"},
        )
    )

    assert transport.payloads[0]["cmd"] == "aibot_respond_msg"
    assert transport.payloads[0]["headers"]["req_id"] == "req-5"
    assert transport.payloads[0]["body"]["msgtype"] == "stream"
    assert transport.payloads[0]["body"]["stream"]["id"] == "stream-1"
    assert transport.payloads[0]["body"]["stream"]["finish"] is True
    assert transport.payloads[0]["body"]["stream"]["content"].endswith("reply")


def test_consume_one_preserves_req_id_for_reply_command() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="reply")],
        )

    channel = WeComChannel(process=process, sender=None, transport=transport, bot_prefix="")
    channel._new_request_id = lambda: "stream-2"
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-from-wecom"},
        "body": {
            "msgid": "msg-1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert transport.payloads[0]["cmd"] == "aibot_respond_msg"
    assert transport.payloads[0]["headers"]["req_id"] == "req-from-wecom"
    assert transport.payloads[0]["body"]["msgtype"] == "stream"
    assert transport.payloads[0]["body"]["stream"]["id"] == "stream-2"


def test_consume_one_streaming_reply_starts_with_waiting_then_finishes() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="final reply")],
        )

    channel = WeComChannel(
        process=process,
        sender=None,
        transport=transport,
        bot_prefix="",
        show_streaming_reply=True,
    )
    channel._new_request_id = lambda: "stream-shared"
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-streaming"},
        "body": {
            "msgid": "msg-stream",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert len(transport.payloads) == 2
    first_payload, last_payload = transport.payloads
    assert first_payload["cmd"] == "aibot_respond_msg"
    assert first_payload["headers"]["req_id"] == "req-streaming"
    assert first_payload["body"]["msgtype"] == "stream"
    assert first_payload["body"]["stream"]["id"] == "stream-shared"
    assert first_payload["body"]["stream"]["finish"] is False
    assert last_payload["cmd"] == "aibot_respond_msg"
    assert last_payload["headers"]["req_id"] == "req-streaming"
    assert last_payload["body"]["msgtype"] == "stream"
    assert last_payload["body"]["stream"]["id"] == "stream-shared"
    assert last_payload["body"]["stream"]["finish"] is True
    assert last_payload["body"]["stream"]["content"].endswith("final reply")


def test_consume_one_without_streaming_reply_sends_single_final_reply() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="final reply")],
        )

    channel = WeComChannel(
        process=process,
        sender=None,
        transport=transport,
        bot_prefix="",
        show_streaming_reply=False,
    )
    channel._new_request_id = lambda: "stream-disabled"
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-no-stream"},
        "body": {
            "msgid": "msg-no-stream",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert len(transport.payloads) == 1
    only_payload = transport.payloads[0]
    assert only_payload["cmd"] == "aibot_respond_msg"
    assert only_payload["headers"]["req_id"] == "req-no-stream"
    assert only_payload["body"]["msgtype"] == "stream"
    assert only_payload["body"]["stream"]["id"] == "stream-disabled"
    assert only_payload["body"]["stream"]["finish"] is True
    assert only_payload["body"]["stream"]["content"].endswith("final reply")


def test_consume_one_sends_tool_message_as_independent_reply() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.FUNCTION_CALL_OUTPUT,
            role=Role.ASSISTANT,
            content=[
                SimpleNamespace(
                    type=ContentType.DATA,
                    data={"name": "search", "output": "tool output"},
                )
            ],
        )
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="final reply")],
        )

    channel = WeComChannel(
        process=process,
        sender=None,
        transport=transport,
        bot_prefix="",
        show_streaming_reply=True,
        show_tool_details=True,
    )
    stream_ids = iter(["main-stream", "tool-stream"])
    channel._new_request_id = lambda: next(stream_ids)
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-tool"},
        "body": {
            "msgid": "msg-tool",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert len(transport.payloads) == 3
    waiting_payload, tool_payload, final_payload = transport.payloads
    assert waiting_payload["body"]["stream"]["id"] == "main-stream"
    assert waiting_payload["body"]["stream"]["finish"] is False
    assert tool_payload["body"]["stream"]["id"] == "tool-stream"
    assert tool_payload["body"]["stream"]["finish"] is True
    assert "search" in tool_payload["body"]["stream"]["content"]
    assert final_payload["body"]["stream"]["id"] == "main-stream"
    assert final_payload["body"]["stream"]["finish"] is True
    assert final_payload["body"]["stream"]["content"].endswith("final reply")


def test_consume_one_sends_reasoning_as_independent_reply() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.REASONING,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="reasoning text")],
        )
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="final reply")],
        )

    channel = WeComChannel(
        process=process,
        sender=None,
        transport=transport,
        bot_prefix="",
        show_streaming_reply=True,
        filter_thinking=False,
    )
    stream_ids = iter(["main-stream", "thinking-stream"])
    channel._new_request_id = lambda: next(stream_ids)
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-thinking"},
        "body": {
            "msgid": "msg-thinking",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert len(transport.payloads) == 3
    waiting_payload, thinking_payload, final_payload = transport.payloads
    assert waiting_payload["body"]["stream"]["id"] == "main-stream"
    assert waiting_payload["body"]["stream"]["finish"] is False
    assert thinking_payload["body"]["stream"]["id"] == "thinking-stream"
    assert thinking_payload["body"]["stream"]["finish"] is True
    assert thinking_payload["body"]["stream"]["content"].endswith(
        "reasoning text"
    )
    assert final_payload["body"]["stream"]["id"] == "main-stream"
    assert final_payload["body"]["stream"]["finish"] is True
    assert final_payload["body"]["stream"]["content"].endswith("final reply")


def test_consume_one_filters_reasoning_when_filter_thinking_enabled() -> None:
    transport = RecordingTransport()

    async def process(_request):
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.REASONING,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="reasoning text")],
        )
        yield SimpleNamespace(
            object="message",
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[TextContent(type=ContentType.TEXT, text="final reply")],
        )

    channel = WeComChannel(
        process=process,
        sender=None,
        transport=transport,
        bot_prefix="",
        show_streaming_reply=True,
        filter_thinking=True,
    )
    channel._new_request_id = lambda: "main-stream"
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-thinking-filtered"},
        "body": {
            "msgid": "msg-thinking-filtered",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))

    assert len(transport.payloads) == 2
    waiting_payload, final_payload = transport.payloads
    assert waiting_payload["body"]["stream"]["id"] == "main-stream"
    assert waiting_payload["body"]["stream"]["finish"] is False
    assert final_payload["body"]["stream"]["id"] == "main-stream"
    assert final_payload["body"]["stream"]["finish"] is True
    assert final_payload["body"]["stream"]["content"].endswith("final reply")
