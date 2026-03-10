# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.ws_client import (
    build_ping_payload,
    build_subscribe_payload,
)


def test_build_subscribe_payload() -> None:
    payload = build_subscribe_payload("req-1", "bot-1", "secret-1")

    assert payload["cmd"] == "aibot_subscribe"
    assert payload["headers"]["req_id"] == "req-1"
    assert payload["body"]["bot_id"] == "bot-1"
    assert payload["body"]["secret"] == "secret-1"


def test_build_ping_payload() -> None:
    payload = build_ping_payload("req-ping")

    assert payload == {
        "cmd": "ping",
        "headers": {"req_id": "req-ping"},
    }
