"""Frozen WeCom Driver + actual SDK and native TLS wire, not Core/worker proof."""

import asyncio
import base64
import hashlib
from importlib.metadata import version
import json

import pytest

pytest.register_assert_rewrite("wecom_native_support")

from wecom_native_support import eventually, ingress, prepare, send, text_frame

pytest_plugins = ["wecom_native_support"]


async def test_native_subscribe_processing_first_stream_sid_and_final(wecom_native):
    driver, peer, identity, server = wecom_native
    assert version("wecom-aibot-python-sdk") == "1.0.2"
    assert server.rows("aibot_subscribe")[0]["body"] == {"bot_id": "native-bot", "secret": "native-secret"}
    event = await ingress(wecom_native)
    assert event["acl_sender_id"] == "sender-A"
    assert event["metadata"]["session_id"] == "wecom:sender-A"
    assert "frame" not in json.dumps(peer.batches)
    handle = event["response_handle"]
    assert (await prepare(wecom_native, handle))["state"] == "acknowledged"
    processing = server.rows("aibot_respond_msg")[-1]["body"]["stream"]
    assert processing["content"] == "🤔 Thinking..." and processing["finish"] is False
    assert (await send(wecom_native, handle, operation="stream.start", stream_type="message", sequence=0, accumulated_text="first"))["state"] == "acknowledged"
    assert (await send(wecom_native, handle, delivery="end-A", operation="stream.end", target_delivery_id="delivery-A", stream_type="message", sequence=1, accumulated_text="final answer"))["state"] == "acknowledged"
    streams = [r["body"]["stream"] for r in server.rows("aibot_respond_msg")]
    assert streams == [
        {"id": processing["id"], "finish": False, "content": "🤔 Thinking..."},
        {"id": processing["id"], "finish": False, "content": "first"},
        {"id": processing["id"], "finish": True, "content": "final answer"},
    ]
    assert driver._platform._keepalive_tasks == {}


async def test_native_upload_init_chunks_finish_ack_and_reply(wecom_native, tmp_path):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    data = b"chunk-content\x00" * 41000
    path = tmp_path / "upload.bin"
    path.write_bytes(data)
    result = await send(wecom_native, event["response_handle"], content_parts=[{"type": "file", "file_url": str(path), "filename": "upload.bin"}])
    assert result["state"] == "acknowledged"
    commands = [r for r in server.rows() if r["cmd"].startswith("aibot_upload_")]
    assert [r["cmd"] for r in commands] == ["aibot_upload_media_init", "aibot_upload_media_chunk", "aibot_upload_media_chunk", "aibot_upload_media_finish"]
    assert commands[0]["body"] == {"type": "file", "filename": "upload.bin", "total_size": len(data), "total_chunks": 2, "md5": hashlib.md5(data).hexdigest()}
    assert [r["body"]["chunk_index"] for r in commands[1:3]] == [0, 1]
    assert b"".join(base64.b64decode(r["body"]["base64_data"]) for r in commands[1:3]) == data
    assert commands[-1]["body"] == {"upload_id": "native-upload"}
    assert server.rows("aibot_respond_msg")[-1]["body"] == {"msgtype": "file", "file": {"media_id": "native-media"}}
    assert driver._platform._upload_ack_futures == {}


async def test_native_card_actual_clicker_and_host_typed_resolution(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native, text_frame(group=True))
    assert event["metadata"]["user_id"] == "group"
    assert event["acl_sender_id"] == "sender-A"
    result = await send(wecom_native, event["response_handle"], content_parts=[{"type": "text", "text": "guard details"}], approval={"request_id": "rid-12345678", "tool_name": "shell", "severity": "high"})
    assert result["state"] == "acknowledged"
    card = server.rows("aibot_respond_msg")[-1]["body"]["template_card"]
    assert card["task_id"] == "tg_approval_rid-12345678"
    assert card["main_title"]["desc"] == "shell | high"
    callback = {"cmd": "aibot_event_callback", "headers": {"req_id": "click-A"}, "body": {"msgtype": "event", "event": {"eventtype": "template_card_event", "template_card_event": {"event_key": card["button_list"][0]["key"], "task_id": card["task_id"]}}, "from": {"userid": "actual-clicker"}, "chatid": "group-A", "chattype": "group"}}
    click = await ingress(wecom_native, callback)
    assert click["acl_sender_id"] == click["sender_id"] == "actual-clicker"
    assert click["metadata"]["session_id"] == "wecom:group:group-A"
    assert click["content_parts"] == [{"type": "text", "text": "/approval approve rid-12345678"}]
    assert server.rows("aibot_respond_update_msg") == []
    result = await send(wecom_native, click["response_handle"], delivery="resolve-A", content_parts=[], approval_resolution={"request_id": "rid-12345678", "outcome": "approved", "actor_user_id": "actual-clicker", "tool_name": "shell"})
    assert result["state"] == "acknowledged"
    update = server.rows("aibot_respond_update_msg")[-1]
    assert update["headers"]["req_id"] == "click-A"
    assert update["body"]["template_card"]["main_title"]["title"] == "✅ Approved"
    assert "actual-clicker" in update["body"]["template_card"]["main_title"]["desc"]


async def test_native_unknown_send_is_recorded_and_not_replayed(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    server.queue("aibot_respond_msg", "disconnect")
    first = await send(wecom_native, event["response_handle"], content_parts=[{"type": "text", "text": "one uncertain effect"}])
    assert first["state"] == "unknown"
    second = await send(wecom_native, event["response_handle"], content_parts=[{"type": "text", "text": "one uncertain effect"}])
    assert second == first
    assert len(server.rows("aibot_respond_msg")) == 1


async def test_native_stop_settles_owned_sdk_thread_loop_and_keepalive(wecom_native):
    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    await prepare(wecom_native, event["response_handle"])
    platform = driver._platform
    thread, loop, client = platform._ws_thread, platform._ws_loop, platform._client
    assert thread.is_alive() and loop.is_running()
    await driver.stop()
    assert not thread.is_alive() and loop.is_closed()
    assert platform._sdk_tasks == platform._file_tasks == platform._bridges == set()
    assert platform._keepalive_tasks == platform._processing == platform._upload_ack_futures == {}
    assert client._ws_manager._ws is None
    assert driver._platform is None
    await eventually(lambda: server.closed.is_set())
