# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.sender import (
    build_active_markdown_command,
    build_respond_command,
    build_stream_reply_command,
    build_welcome_command,
)


def test_build_respond_command_uses_req_id() -> None:
    payload = build_respond_command(
        "req-1",
        {
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    )

    assert payload["cmd"] == "aibot_respond_msg"
    assert payload["headers"]["req_id"] == "req-1"
    assert payload["body"]["text"]["content"] == "hello"


def test_build_stream_reply_command() -> None:
    payload = build_stream_reply_command(
        "req-2",
        stream_id="stream-1",
        content="working",
        finish=False,
    )

    assert payload["cmd"] == "aibot_respond_msg"
    assert payload["body"]["msgtype"] == "stream"
    assert payload["body"]["stream"]["id"] == "stream-1"
    assert payload["body"]["stream"]["content"] == "working"
    assert payload["body"]["stream"]["finish"] is False


def test_build_welcome_command() -> None:
    payload = build_welcome_command(
        "req-3",
        {
            "msgtype": "text",
            "text": {"content": "welcome"},
        },
    )

    assert payload["cmd"] == "aibot_respond_welcome_msg"
    assert payload["headers"]["req_id"] == "req-3"


def test_build_active_markdown_command_for_group() -> None:
    payload = build_active_markdown_command(
        "req-4",
        chat_id="room-1",
        chat_type=2,
        content="**done**",
    )

    assert payload["cmd"] == "aibot_send_msg"
    assert payload["headers"]["req_id"] == "req-4"
    assert payload["body"]["chatid"] == "room-1"
    assert payload["body"]["chat_type"] == 2
    assert payload["body"]["msgtype"] == "markdown"
