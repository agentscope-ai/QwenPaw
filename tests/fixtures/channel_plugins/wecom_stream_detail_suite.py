"""Legacy stream-detail effects on real platform/native TLS, plus timeout seam."""

import asyncio

import pytest

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import ingress, prepare, send

pytest_plugins = ["wecom_native_support"]


async def test_new_stream_id_is_generated(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    route = driver._route_attrs(event["response_handle"])
    await driver._platform.send_stream_detail(route, "body")
    reply = server.rows("aibot_respond_msg")[-1]
    stream = reply["body"]["stream"]
    assert stream["content"] == "body"
    assert stream["finish"] is True
    assert reply["headers"] == {"req_id": "cb-native-msg"}
    assert stream["id"]


async def test_processing_stream_id_is_reused_and_popped(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    handle = event["response_handle"]
    await prepare(wecom_native, handle)
    route = driver._route_attrs(handle)
    processing = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    await driver._platform.send_stream_detail(route, "body")
    stream = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    assert stream["id"] == processing["id"]
    assert stream["content"] == "body" and stream["finish"] is True
    assert processing["id"] not in driver._platform._keepalive_tasks
    # The old mutable send_meta marker is now a worker-local consumed state.
    assert driver._platform._processing[handle]["final"] is True


async def test_no_keepalive_entry_is_fine(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    route = driver._route_attrs(event["response_handle"])
    assert driver._platform._keepalive_tasks == {}
    await driver._platform.send_stream_detail(route, "body")
    stream = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    assert stream["content"] == "body" and stream["finish"] is True
    assert driver._platform._keepalive_tasks == {}


async def test_native_force_timeout_finalizes_old_sid_and_first_reply_uses_new_sid(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    handle = event["response_handle"]
    await prepare(wecom_native, handle)
    platform, route = driver._platform, driver._route_attrs(handle)
    state = platform._processing[handle]
    old_sid = state["stream_id"]
    task = platform._keepalive_tasks[old_sid]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # Exercise the existing max-duration boundary directly; SDK timeouts and
    # production defaults remain unchanged, and all effects use real TLS.
    await platform._keepalive_processing(handle, route, state, max_duration=0)
    assert state["final"] is True
    assert server.rows("aibot_respond_msg")[-1]["body"]["stream"] == {
        "id": old_sid, "finish": True, "content": "🤔 Thinking...",
    }
    result = await send(wecom_native, handle, operation="stream.start", stream_type="message", sequence=0, accumulated_text="after timeout")
    assert result["state"] == "acknowledged"
    fresh = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    assert fresh["id"] != old_sid
    assert fresh["content"] == "after timeout" and fresh["finish"] is False
