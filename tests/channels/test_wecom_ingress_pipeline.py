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


def test_duplicate_msgid_is_skipped(tmp_path) -> None:
    channel = WeComChannel(
        processed_ids_path=tmp_path / "processed.json",
        route_store_path=tmp_path / "routes.json",
    )
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "dup-1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    req1 = channel.build_agent_request_from_native(payload)
    req2 = channel.build_agent_request_from_native(payload)

    assert req1 is not None
    assert req2 is None


def test_route_saved_during_ingress(tmp_path) -> None:
    channel = WeComChannel(
        processed_ids_path=tmp_path / "processed.json",
        route_store_path=tmp_path / "routes.json",
    )
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "m-route",
            "chattype": "group",
            "chatid": "room1",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    req = channel.build_agent_request_from_native(payload)
    route = channel._route_store.get_route("wecom:chat:room1")

    assert req is not None
    assert route is not None
    assert route.target_type == "chat"
    assert route.target_id == "room1"


def test_consume_one_skips_duplicate_without_error(tmp_path) -> None:
    calls = []

    async def process(request):
        calls.append(request.session_id)
        if False:
            yield request

    channel = WeComChannel(
        process=process,
        processed_ids_path=tmp_path / "processed.json",
        route_store_path=tmp_path / "routes.json",
    )
    payload = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgid": "dup-consume-1",
            "chattype": "single",
            "from": {"userid": "alice"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }

    asyncio.run(channel.consume_one(payload))
    asyncio.run(channel.consume_one(payload))

    assert calls == ["wecom:user:alice"]
