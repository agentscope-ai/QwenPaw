"""Remaining original Matrix group, target and presentation responsibilities."""
import base64

import pytest

from extension_process_suite import eventually, runtime
from g2_actual_agent_suite import assert_host_and_reload
from matrix_formal_agent_suite import assert_original_archive, formal_source
from matrix_formal_delivery_suite import connected
from matrix_formal_support import (
    BOT,
    ROOM,
    SENDER,
    hs,
    matrix_host_guard,
    sync_payload,
    text_event,
)
from real_host_runtime import bind_real_runtime

__all__ = ["runtime", "hs", "matrix_host_guard"]


@pytest.mark.asyncio
@pytest.mark.parametrize("share", [True, False])
async def test_formal_group_mention_preserves_shared_or_sender_agent_identity(
    runtime, hs, monkeypatch, share
):
    hs.group = True
    rt = await runtime(
        "matrix",
        source_factory=formal_source,
        homeserver=hs.url,
        user_id=BOT,
        access_token="formal-matrix-token",
        streaming_enabled=False,
        share_session_in_group=share,
        access_control_group=True,
    )
    assert_original_archive(rt)
    host = await bind_real_runtime(rt, monkeypatch)
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    count = len(hs.calls("/sync"))
    hs.sync.put_nowait((sync_payload("catchup"), 200))
    await eventually(lambda: len(hs.calls("/sync")) > count)
    rt.channel._get_acl_store().add_to_whitelist("matrix", SENDER)
    event = text_event("group question", "$group-question")
    event["content"]["m.mentions"] = {"user_ids": [BOT]}
    payload = sync_payload("group-live", [event])
    payload["rooms"]["join"][ROOM]["state"]["events"] = [
        {
            "type": "m.room.member",
            "state_key": SENDER,
            "sender": SENDER,
            "event_id": "$member",
            "origin_server_ts": 1,
            "content": {"membership": "join", "displayname": "User"},
        }
    ]
    hs.sync.put_nowait((payload, 200))
    await eventually(lambda: len(hs.sent) == 1 and len(host.calls) == 1)
    await assert_host_and_reload(
        rt,
        host,
        "User: group question",
        "matrix:" + ROOM,
        ROOM if share else SENDER,
    )
    assert rt.ws.requests[0].channel_meta["sender_id"] == SENDER
    assert rt.ws.requests[0].channel_meta["is_group"] is True
    assert "m.mentions" not in hs.sent[0]["body"]
    assert hs.sent[0]["body"]["body"] == "actual agent answer"
    assert rt.channel._get_acl_store().get_all_pending() == []


@pytest.mark.asyncio
async def test_formal_proactive_target_precedence_matches_legacy_room_resolution(
    runtime, hs
):
    from qwenpaw.schemas import AgentRequest

    rt = await connected(runtime, hs)
    for session, meta, expected in (
        ("matrix:" + ROOM, {"room_id": ROOM}, ROOM),
        ("other_session", {"room_id": ROOM}, ROOM),
        ("matrix:" + ROOM, {}, ROOM),
        ("other_session", {}, SENDER),
    ):
        request = AgentRequest(
            channel="matrix",
            session_id=session,
            user_id=SENDER,
            channel_meta=meta,
        )
        target = rt.channel.get_to_handle_from_request(request)
        before = len(hs.sent)
        await rt.channel.send(target, "target answer", dict(meta))
        assert len(hs.sent) == before + 1
        assert f"/rooms/{expected}/send/m.room.message/" in hs.sent[-1]["path"]
        assert hs.sent[-1]["body"]["body"] == "target answer"


@pytest.mark.asyncio
async def test_formal_parts_text_image_mixed_preserve_native_presentation(
    runtime, hs
):
    rt = await connected(runtime, hs)
    data = b"matrix image bytes"
    uri = "data:image/png;base64," + base64.b64encode(data).decode()
    text, image = {"type": "text", "text": "Hello"}, {
        "type": "image",
        "image_url": uri,
    }
    target = rt.channel.to_handle_from_target(
        user_id=ROOM, session_id="matrix:" + ROOM
    )
    for parts, expected_text, media_count in (
        ([text], "Hello", 0),
        ([image], f"[Image: {uri}]", 1),
        ([text, image], f"Hello\n[Image: {uri}]", 1),
    ):
        before, uploads = len(hs.sent), len(hs.uploads)
        await rt.channel.send_content_parts(target, parts, {})
        rows = hs.sent[before:]
        assert len(rows) == 1 + media_count
        assert rows[0]["body"]["body"] == expected_text
        assert rows[0]["body"]["format"] == "org.matrix.custom.html"
        assert len(hs.uploads) == uploads + media_count
        if media_count:
            assert hs.uploads[-1]["body"] == data
            assert rows[1]["body"]["msgtype"] == "m.image"
            assert rows[1]["body"]["url"] == "mxc://example.org/media"
    await rt.channel.send(target, "**bold**", {})
    assert hs.sent[-1]["body"]["body"] == "**bold**"
    assert "<strong>bold</strong>" in hs.sent[-1]["body"]["formatted_body"]
