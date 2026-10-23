"""Real shared Driver and native gateway with a controlled host RPC endpoint."""

import hashlib

import pytest

pytest.register_assert_rewrite("yuanbao_native_support")
from yuanbao_native_support import codec, decode, eventually, inbound, open_route, send
from qwenpaw.channel_protocol.models import ResponseFinishParams

pytest_plugins = ["yuanbao_native_support"]


async def test_real_driver_admission_retains_acl_short_session_and_native_reply_target(native_driver):
    driver, peer, identity, external = native_driver
    await external.push(inbound(msg_id="driver-inbound"))
    await eventually(lambda: len(peer.batches) == 1)
    event = peer.batches[0]["events"][0]
    assert {key: event[key] for key in identity} == identity
    assert event["event_id"] == "driver-inbound" and event["acl_sender_id"] == "native-user-12345678"
    assert event["sender_id"] == "灰#5678" and event["metadata"]["session_id"] == "12345678"
    assert event["conversation"] == {"id": "native-user-12345678", "type": "dm", "thread_id": None}
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    handle = event["response_handle"]
    assert driver._route_attrs(handle)["sender_id"] == "native-user-12345678"
    result = await send(peer, identity, handle)
    assert result["state"] == "acknowledged"
    assert external.sends[0]["body"]["toAccount"] == "native-user-12345678"
    assert external.sends[0]["body"]["msgBody"] == [{"msgType": "TIMTextElem", "msgContent": {"text": "native answer"}}]
    resource = driver._delivery_resource(handle, "delivery-A")
    assert dict(resource.attributes)["scope"] == "business.response"
    assert dict(resource.attributes)["business_accepted"] == "true"
    assert await send(peer, identity, handle) == result
    assert len(external.sends) == 1


async def test_shared_delivery_journal_fences_unknown_without_native_replay(native_driver):
    driver, peer, identity, external = native_driver
    handle = await open_route(peer, identity, chat_type="c2c", raw_sender_id="full-native-target")
    external.behaviors.append("close")
    result = await send(peer, identity, handle)
    assert result["state"] == "unknown" and result["retryable"] is False
    assert result["reason_code"] == "YUANBAO_CONNECTION_LOST"
    assert await send(peer, identity, handle) == result
    assert len(external.sends) == 1
    saved = peer.state["yuanbao.shared.responses"]
    assert len(saved) == 1 and saved[0]["response_handle"] == handle
    assert driver._platform._pending_requests == {}


async def test_prepare_and_finish_keep_two_response_typing_routes_separate(native_driver):
    driver, peer, identity, external = native_driver
    first = await open_route(peer, identity, "one", chat_type="group", raw_sender_id="speaker-one", group_code="native-group-one")
    second = await open_route(peer, identity, "two", chat_type="group", raw_sender_id="speaker-two", group_code="native-group-two")
    for handle in (first, second):
        result = await peer.methods["channel.response.prepare"]({
            **identity, "response_handle": handle,
            "delivery_id": hashlib.sha256((handle + ":prepare").encode()).hexdigest(),
        }, None)
        assert result["state"] == "acknowledged"
        resource = driver._delivery_resource(handle, hashlib.sha256((handle + ":prepare").encode()).hexdigest())
        assert dict(resource.attributes)["scope"] == "websocket.write"
        assert "business_accepted" not in dict(resource.attributes)
    assert set(driver._platform._typing_tasks) == {first, second}
    finish = ResponseFinishParams.from_mapping({**identity, "response_handle": first, "outcome": "completed"})
    await peer.methods["channel.response.finish"](finish, None)
    assert set(driver._platform._typing_tasks) == {second}
    await eventually(lambda: len([f for f in external.frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB]) == 3)
    native = [decode(codec.SEND_GROUP_HB_REQ, f["data"]) for f in external.frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB]
    assert [(v["groupCode"], v["heartbeat"]) for v in native] == [
        ("native-group-one", "HEARTBEAT_RUNNING"),
        ("native-group-two", "HEARTBEAT_RUNNING"),
        ("native-group-one", "HEARTBEAT_FINISH"),
    ]
    assert driver._routes.snapshot(first).cleanup_state.value == "complete"
    policy = await peer.methods["channel.response.describe"]({**identity, "response_handle": second}, None)
    assert policy == {"streaming": False, "prepare": True, "completion_reaction": False,
                      "send_format": {"direct_prefix": False, "parts_configured_prefix": True}}
