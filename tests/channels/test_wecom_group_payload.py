# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel


def test_group_payload_uses_chat_id_as_session() -> None:
    channel = WeComChannel()
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m1",
            "chatid": "room1",
            "chattype": "group",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "@bot hello"},
        },
    }

    req = channel.build_agent_request_from_native(payload)

    assert req is not None
    assert req.session_id == "wecom:chat:room1"
    assert req.channel_meta["chat_id"] == "room1"
    assert req.channel_meta["chat_type"] == "group"

