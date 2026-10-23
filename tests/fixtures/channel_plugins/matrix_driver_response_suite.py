"""Real Driver journal/stream contract, with actual nio HTTP effects."""
import asyncio
import hashlib
import json

import pytest
from matrix_native_support import BOT, ROOM, sync_payload, text_event, until
from matrix_driver_support import hs, native_driver, open_route, send
from qwenpaw.channel_protocol.models import ResponseFinishParams
from qwenpaw.channel_protocol.errors import RpcError


@pytest.mark.asyncio
async def test_unknown_edit_cannot_replay_fallback_or_finish_new_message(native_driver):
    driver, peer, identity, server = native_driver
    handle = await open_route(peer, identity)
    started = await send(peer, identity, handle, delivery="stream-1", operation="stream.start", parts=[], stream_type="message")
    assert started["state"] == "acknowledged"
    server.send.append(({"errcode": "M_UNKNOWN", "error": "outcome unknown"}, 503))
    options = dict(delivery="edit-1", operation="stream.delta", parts=[], stream_type="message", target_delivery_id="stream-1", sequence=1, accumulated_text="private generated text")
    unknown = await send(peer, identity, handle, **options)
    assert unknown["state"] == "unknown"
    assert await send(peer, identity, handle, **options) == unknown
    later = await send(peer, identity, handle, delivery="edit-2", operation="stream.end", parts=[], stream_type="message", target_delivery_id="stream-1", sequence=2, accumulated_text="more text")
    assert later["state"] == "unknown"
    assert len(server.sent) == 2
    assert "private generated text" not in json.dumps(peer.state)
    resource = driver._delivery_resource(handle, "stream-1")
    assert dict(resource.attributes)["unsettled"] == "true"
    assert server.sent[1]["body"]["m.relates_to"]["event_id"] == dict(resource.attributes)["event_id"]
    finish = ResponseFinishParams.from_mapping({**identity, "response_handle": handle, "outcome": "completed"})
    with pytest.raises(RpcError) as failed_finish:
        await peer.methods["channel.response.finish"](finish, None)
    assert failed_finish.value.data["reason_code"] == "RESPONSE_FINISH_FAILED"
    assert driver._routes.snapshot(handle).cleanup_state.value == "pending"
    assert len(server.sent) == 2


@pytest.mark.asyncio
async def test_distinct_response_streams_and_native_finish_are_isolated(native_driver):
    driver, peer, identity, server = native_driver
    one, two = await open_route(peer, identity), await open_route(peer, identity, "!other:example.com")
    for handle, delivery in ((one, "one"), (two, "two")):
        assert (await send(peer, identity, handle, delivery=delivery, operation="stream.start", parts=[], stream_type="message"))["state"] == "acknowledged"
    for handle, delivery in ((one, "one"), (two, "two")):
        assert (await send(peer, identity, handle, delivery=delivery + "-end", operation="stream.end", parts=[], stream_type="message", target_delivery_id=delivery, sequence=1, accumulated_text="answer-" + delivery))["state"] == "acknowledged"
    assert len(server.sent) == 4
    assert server.sent[2]["body"]["m.relates_to"]["event_id"] == dict(driver._delivery_resource(one, "one").attributes)["event_id"]
    assert server.sent[3]["body"]["m.relates_to"]["event_id"] == dict(driver._delivery_resource(two, "two").attributes)["event_id"]
    assert server.sent[2]["path"] != server.sent[3]["path"]
    assert "answer-one" not in json.dumps(peer.state) and "answer-two" not in json.dumps(peer.state)


@pytest.mark.asyncio
async def test_prepare_typing_is_journaled_and_finish_releases_once(native_driver):
    driver, peer, identity, server = native_driver
    handle = await open_route(peer, identity)
    params = {**identity, "response_handle": handle, "delivery_id": hashlib.sha256((handle + ":prepare").encode()).hexdigest()}
    result = await peer.methods["channel.response.prepare"](params, None)
    assert result["state"] == "acknowledged"
    assert await peer.methods["channel.response.prepare"](params, None) == result
    assert [r["body"]["typing"] for r in server.requests if "/typing/" in r["path"]] == [True]
    assert any(ref.kind == "matrix.delivery" and dict(ref.attributes).get("typing") == "true" for ref in driver._routes.snapshot(handle).resource_refs)
    finish = ResponseFinishParams.from_mapping({**identity, "response_handle": handle, "outcome": "completed"})
    await peer.methods["channel.response.finish"](finish, None)
    await peer.methods["channel.response.finish"](finish, None)
    assert [r["body"]["typing"] for r in server.requests if "/typing/" in r["path"]] == [True, False]


@pytest.mark.asyncio
async def test_native_sync_event_preserves_stable_id_route_and_sender(native_driver):
    driver, peer, identity, server = native_driver
    server.sync.put_nowait((sync_payload("catch-up"), 200))
    await until(lambda: len(server.calls("/sync")) == 2)
    server.sync.put_nowait((sync_payload("new", [text_event("Hello bot", "$stable-id")]), 200))
    await until(lambda: len(peer.batches) == 1)
    event = peer.batches[0]["events"][0]
    assert event["event_id"] == "$stable-id"
    assert event["sender_id"] == event["acl_sender_id"] == "@user:example.com"
    assert event["metadata"]["session_id"] == "matrix:" + ROOM
    assert event["metadata"]["user_id"] == ROOM
    assert event["content_parts"] == [{"type": "text", "text": "Hello bot"}]
    assert dict(driver._routes.snapshot(event["response_handle"]).route_refs[0].attributes)["room_id"] == ROOM
