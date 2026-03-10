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


def test_mixed_payload_splits_into_multiple_parts() -> None:
    channel = WeComChannel()
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "mixed",
            "mixed": {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image", "sdkfileid": "f1", "aeskey": "k1"},
                ]
            },
        },
    }

    req = channel.build_agent_request_from_native(payload)

    assert req is not None
    assert len(req.input[0].content) == 2
    assert req.input[0].content[0].text == "hello"
    assert "image" in req.input[0].content[1].text.lower()

