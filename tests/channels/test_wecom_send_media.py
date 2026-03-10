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

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
    ImageContent,
)

from copaw.app.channels.wecom.channel import WeComChannel
from copaw.app.channels.wecom.sender import build_file_message, build_image_message


def test_build_image_message() -> None:
    payload = build_image_message("media-1")

    assert payload["msgtype"] == "image"
    assert payload["image"]["media_id"] == "media-1"


def test_build_file_message() -> None:
    payload = build_file_message("media-2")

    assert payload["msgtype"] == "file"
    assert payload["file"]["media_id"] == "media-2"


def test_send_content_parts_sends_media_payloads() -> None:
    channel = WeComChannel()
    parts = [
        ImageContent(type=ContentType.IMAGE, image_url="img-1"),
        FileContent(type=ContentType.FILE, file_id="file-1"),
    ]

    asyncio.run(channel.send_content_parts("wecom:user:alice", parts, meta={}))

    payloads = [payload for _, payload in channel._sender.sent_messages]
    assert payloads[0]["msgtype"] == "image"
    assert payloads[1]["msgtype"] == "file"
