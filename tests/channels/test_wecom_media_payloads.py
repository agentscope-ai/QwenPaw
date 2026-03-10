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


def test_image_payload_degrades_when_media_unavailable() -> None:
    channel = WeComChannel()
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "image",
            "image": {"sdkfileid": "f1", "aeskey": "k1"},
        },
    }

    req = channel.build_agent_request_from_native(payload)

    assert req is not None
    assert len(req.input[0].content) >= 1
    assert "image" in req.input[0].content[0].text.lower()


def test_voice_payload_degrades_to_text() -> None:
    channel = WeComChannel()
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m2",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "voice",
            "voice": {"sdkfileid": "f2", "aeskey": "k2"},
        },
    }

    req = channel.build_agent_request_from_native(payload)

    assert req is not None
    assert "voice" in req.input[0].content[0].text.lower()

