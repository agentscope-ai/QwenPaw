# -*- coding: utf-8 -*-

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel


def test_send_supports_user_handle() -> None:
    channel = WeComChannel()

    asyncio.run(channel.send("wecom:user:alice", "hello", meta={}))

    assert channel._sender.last_target.target_type == "user"
    assert channel._sender.last_target.target_id == "alice"
    assert channel._sender.last_payload["msgtype"] == "text"


def test_send_supports_chat_handle() -> None:
    channel = WeComChannel()

    asyncio.run(channel.send("wecom:chat:room1", "hello", meta={}))

    assert channel._sender.last_target.target_type == "chat"
    assert channel._sender.last_target.target_id == "room1"


def test_send_uses_markdown_meta() -> None:
    channel = WeComChannel(bot_prefix="")

    asyncio.run(
        channel.send(
            "wecom:user:alice",
            "**hello**",
            meta={"msgtype": "markdown"},
        )
    )

    assert channel._sender.last_payload["msgtype"] == "markdown"
