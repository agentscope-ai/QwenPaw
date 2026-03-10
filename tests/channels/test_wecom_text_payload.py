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


def test_build_request_from_text_payload() -> None:
    channel = WeComChannel()
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    req = channel.build_agent_request_from_native(payload)

    assert req is not None
    assert req.session_id == "wecom:user:alice"
    assert req.input[0].content[0].text == "hello"
    assert req.channel_meta["req_id"] == "r1"
    assert req.channel_meta["message_id"] == "m1"
    assert req.channel_meta["msg_type"] == "text"

