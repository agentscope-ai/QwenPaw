"""Native Yuanbao protocol effects; full host/worker proof belongs to the next phase."""

import asyncio
import hashlib
import hmac
import json

import pytest

pytest.register_assert_rewrite("yuanbao_native_support")
from yuanbao_native_support import codec, eventually, inbound

from qwenpaw_channel_yuanbao.errors import YuanbaoDeliveryError

pytest_plugins = ["yuanbao_native_support"]


async def test_sign_token_hmac_auth_bind_and_binary_c2c_group_business_receipts(native_platform):
    platform, events, states, external = native_platform
    assert external.signatures_valid == [True]
    assert states == ["connecting", "connected"]
    assert external.frames[0]["head"]["cmd"] == codec.CMD_AUTH_BIND
    for group in (None, "native-group-完整"):
        await external.push(inbound(group=group, msg_id="message-" + str(group)))
        await eventually(lambda: len(events) == (2 if group else 1))
        route = events[-1]["route"]
        receipt = await platform.send_parts(route, [{"type": "text", "text": "原文答复"}], "direct", "delivery-" + str(group))
        assert receipt["scope"] == "business.response"
        assert receipt["business_accepted"] == "true"
        assert receipt["transport_written"] == "true" and receipt["messages"] == "1"
        native = external.sends[-1]
        assert native["body"]["msgBody"] == [{"msgType": "TIMTextElem", "msgContent": {"text": "原文答复"}}]
        assert native["body"]["fromAccount"] == "native-bot"
        expected_id = hashlib.sha256(("delivery-" + str(group) + ":0").encode()).hexdigest()[:32]
        assert json.loads(receipt["native_message_ids"]) == [expected_id]
        assert native["head"]["msgId"] == expected_id
        if group:
            assert native["head"]["cmd"] == codec.BIZ_CMD_SEND_GROUP
            assert native["body"]["groupCode"] == group
        else:
            assert native["head"]["cmd"] == codec.BIZ_CMD_SEND_C2C
            assert native["body"]["toAccount"] == "native-user-12345678"


async def test_native_need_ack_does_not_commit_denied_host_admission(native_platform):
    platform, events, _, external = native_platform
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def admission(value):
        calls.append(value)
        entered.set()
        await release.wait()
        return len(calls) > 1
    platform.on_event = admission
    value = inbound(msg_id="stable-business-id")
    value["cloud_custom_data"] = json.dumps({"quote": {"type": 3, "desc": "voice.mp3"}})
    await external.push(value, frame_id="transport-frame-1")
    await entered.wait()
    await eventually(lambda: any(f["head"].get("cmdType") == codec.CMD_TYPE_PUSH_ACK for f in external.frames))
    assert "stable-business-id" not in platform._seen_message_ids
    assert calls[0]["event_id"] == "stable-business-id"
    assert calls[0]["raw_sender_id"] == "native-user-12345678"
    assert calls[0]["sender_id"] == "灰#5678"
    assert calls[0]["session_id"] == "12345678"
    assert calls[0]["content_parts"] == [{"type": "text", "text": "[quoted audio: voice.mp3]\nhello"}]
    release.set()
    await eventually(lambda: not platform._operations)
    assert "stable-business-id" not in platform._seen_message_ids
    await external.push(value, frame_id="transport-frame-2")
    await eventually(lambda: "stable-business-id" in platform._seen_message_ids)
    await external.push(value, frame_id="transport-frame-3")
    await eventually(lambda: len([f for f in external.frames if f["head"].get("cmdType") == codec.CMD_TYPE_PUSH_ACK]) == 3)
    assert len(calls) == 2 and events == []
    assert [c["event_id"] for c in calls] == ["stable-business-id", "stable-business-id"]


async def test_only_matching_business_response_confirms_transport_write(native_platform):
    platform, _, _, external = native_platform
    external.behaviors.append("hold")
    route = {"chat_type": "c2c", "sender_id": "long-native-target", "group_code": "", "msg_id": "original"}
    task = asyncio.create_task(platform.send_parts(route, [{"type": "text", "text": "one"}], "direct", "held-delivery"))
    try:
        await eventually(lambda: len(external.sends) == 1)
        head = external.sends[0]["head"]
        await external.respond(head, codec.SEND_C2C_RSP, {"code": 0}, msgId="different-message")
        await external.respond(head, codec.SEND_C2C_RSP, {"code": 0}, cmd=codec.BIZ_CMD_SEND_GROUP)
        # A loopback ping response is a wire barrier after both wrong receipts.
        await external.respond({"cmd": codec.CMD_PING, "msgId": "barrier"}, codec.PING_RSP, {"heartInterval": 9})
        await eventually(lambda: platform._heartbeat_interval == 9)
        assert not task.done()
        await external.respond(head, codec.SEND_C2C_RSP, {"code": 0, "message": "ok"})
        assert (await task)["business_accepted"] == "true"
        assert len(external.sends) == 1
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("mode,reason,written,accepted,possible", [
    ("reject", "YUANBAO_BUSINESS_REJECTED", True, False, False),
    ("invalid", "YUANBAO_RESPONSE_INVALID", True, None, True),
    ("close", "YUANBAO_CONNECTION_LOST", True, None, True),
])
async def test_business_rejection_invalid_or_lost_response_are_not_acknowledged(native_platform, mode, reason, written, accepted, possible):
    platform, _, _, external = native_platform
    external.behaviors.append(mode)
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "original"}
    with pytest.raises(YuanbaoDeliveryError) as caught:
        await platform.send_parts(route, [{"type": "text", "text": "one"}], "direct", "result-" + mode)
    error = caught.value
    assert error.reason_code == reason
    assert error.receipt.transport_written is written
    assert error.receipt.business_accepted is accepted
    assert error.side_effect_possible is possible and error.retryable is False
    assert len(external.sends) == 1


async def test_cos_real_verified_tls_upload_keeps_headers_signature_and_native_file(native_platform):
    platform, _, _, external = native_platform
    platform._media_session = await external.enable_verified_cos()
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "original"}
    result = await platform.send_parts(route, [{"type": "file", "file_url": "data:application/pdf;base64,cGRmLWRhdGE=", "filename": "ignored-legacy-name.pdf"}], "parts", "cos-delivery")
    assert result["business_accepted"] == "true" and result["messages"] == "1"
    assert len(external.uploads) == 1
    upload = external.uploads[0]
    assert upload["raw"] == b"pdf-data"
    assert upload["headers"]["x-cos-security-token"] == "cos-token"
    assert upload["headers"]["Content-Type"] == "application/octet-stream"
    auth = dict(field.split("=", 1) for field in upload["headers"]["Authorization"].split("&"))
    assert auth["q-ak"] == "cos-id" and auth["q-sign-time"] == "1700000000;1700003600"
    # Independently verify the signature actually placed on the TLS PUT request.
    from urllib.parse import quote
    headers = {"host": "test-bucket.cos.test-region.myqcloud.com", "content-length": "8", "x-cos-security-token": "cos-token"}
    header_string = "&".join(quote(k, safe="") + "=" + quote(v, safe="") for k, v in sorted(headers.items()))
    http_string = "put\n" + upload["path"] + "\n\n" + header_string + "\n"
    sign_key = hmac.new(b"cos-key", b"1700000000;1700003600", hashlib.sha1).hexdigest()
    sign_text = "sha1\n1700000000;1700003600\n" + hashlib.sha1(http_string.encode()).hexdigest() + "\n"
    expected = hmac.new(sign_key.encode(), sign_text.encode(), hashlib.sha1).hexdigest()
    assert auth["q-signature"] == expected
    request = next(r for r in external.calls if r["path"] == "/api/resource/genUploadInfo")
    assert {k: request["headers"][k] for k in ("X-ID", "X-Token", "X-Source")} == {"X-ID": "native-bot", "X-Token": "native-token", "X-Source": "bot"}
    assert request["body"]["fileName"] == "file.pdf"
    body = external.sends[-1]["body"]["msgBody"]
    assert body == [{"msgType": "TIMFileElem", "msgContent": {
        "uuid": hashlib.md5(b"pdf-data").hexdigest(), "fileName": "file.pdf", "fileSize": 8, "url": external.base + "/assets/uploaded",
    }}]


async def test_cos_preparation_failure_sends_exact_legacy_link_fallback(native_platform):
    platform, _, _, external = native_platform
    external.upload_info_status = 503
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "original"}
    source = external.base + "/assets/image.jpg"
    result = await platform.send_parts(route, [{"type": "image", "image_url": source}], "parts", "fallback-delivery")
    assert result["business_accepted"] == "true" and result["messages"] == "1"
    assert external.uploads == []
    assert external.sends[-1]["body"]["msgBody"] == [{"msgType": "TIMTextElem", "msgContent": {"text": "[图片: " + source + "]"}}]


async def test_legacy_standalone_media_has_explicit_zero_effect_failure(native_platform):
    platform, _, _, external = native_platform
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "original"}
    before = len(external.calls)
    with pytest.raises(YuanbaoDeliveryError) as caught:
        await platform.send_parts(route, [{"type": "image", "image_url": "data:image/png;base64,eA=="}], "media", "legacy-media")
    assert caught.value.reason_code == "LEGACY_MEDIA_ENTRYPOINT_UNSUPPORTED"
    assert caught.value.side_effect_possible is False and caught.value.retryable is False
    assert len(external.calls) == before and external.sends == []
