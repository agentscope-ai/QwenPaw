"""Private cache/thread confinement and media failure effects on actual SDK."""

import threading

import pytest

pytest.register_assert_rewrite("wecom_native_support")
from wecom_native_support import (  # noqa: E402
    ingress,
    send,
    text_frame,
    eventually,
)  # noqa: E402

pytest_plugins = ["wecom_native_support"]


async def test_original_cache_bound_and_thread_ingress_on_actual_platform(
    wecom_native, tmp_path, monkeypatch
):
    import qwenpaw_channel_wecom.inbound as inbound
    from qwenpaw_channel_wecom.platform import WeComPlatform
    from qwenpaw_channel_wecom.errors import WeComDeliveryError

    fresh = WeComPlatform({"workspace_dir": str(tmp_path)}, None, None)
    assert isinstance(fresh._processed_message_ids, dict)
    assert fresh._client is fresh._ws_thread is None
    with pytest.raises(WeComDeliveryError) as caught:
        await fresh.start()
    assert caught.value.reason_code == "CREDENTIALS_REQUIRED"
    assert fresh._client is fresh._ws_thread is None
    # Old private threading.Lock moves to one owner event loop. Exercise the
    # real SDK callback's thread-safe posting entry, not a copied cache helper.
    driver, peer, identity, server = wecom_native
    platform = driver._platform
    accepted = []

    async def accept(event):
        accepted.append((event["event_id"], threading.get_ident()))
        return True

    monkeypatch.setattr(platform, "on_event", accept)
    monkeypatch.setattr(inbound.logger, "disabled", True)
    threads = [
        threading.Thread(
            target=platform._post,
            args=(
                platform._native,
                "message",
                text_frame("thread-" + str(i)),
                platform._epoch,
            ),
        )
        for i in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    await eventually(lambda: len(accepted) == 10)
    assert {event_id for event_id, _ in accepted} == {
        "wecom:thread-" + str(i) for i in range(10)
    }
    assert {tid for _, tid in accepted} == {threading.get_ident()}
    before = len(accepted)
    assert await platform._on_message(text_frame("thread-0")) is True
    assert len(accepted) == before
    # Original bound was2000; retain old max+100 workload exactly.
    for i in range(2000 + 100):
        assert await platform._on_message(text_frame("msg_" + str(i))) is True
    assert len(platform._processed_message_ids) <= 2000
    assert len(accepted) == 2110
    assert "wecom:msg_0" not in platform._processed_message_ids
    assert "wecom:msg_2099" in platform._processed_message_ids
    assert peer.batches == []
    assert server.rows("aibot_respond_msg") == []


async def test_media_failures_and_image_audio_each_have_exact_effects(
    wecom_native, tmp_path
):
    from PIL import Image

    driver, peer, identity, server = wecom_native
    event = await ingress(wecom_native)
    handle = event["response_handle"]
    result = await send(
        wecom_native,
        handle,
        delivery="missing",
        content_parts=[
            {"type": "file", "file_url": str(tmp_path / "missing.bin")}
        ],
    )
    assert result == {
        "delivery_id": "missing",
        "state": "failed",
        "reason_code": "MEDIA_FILE_UNAVAILABLE",
        "retryable": False,
    }
    assert server.rows("aibot_upload_media_init") == []
    path = tmp_path / "upload.bin"
    path.write_bytes(b"data")
    server.queue("aibot_upload_media_init", {})
    fields = {
        "delivery": "bad-init",
        "content_parts": [{"type": "file", "file_url": str(path)}],
    }
    result = await send(wecom_native, handle, **fields)
    assert result == {
        "delivery_id": "bad-init",
        "state": "unknown",
        "reason_code": "UPLOAD_ACK_INVALID",
        "retryable": False,
    }
    assert len(server.rows("aibot_upload_media_init")) == 1
    assert server.rows("aibot_upload_media_chunk") == []
    assert server.rows("aibot_upload_media_finish") == []
    assert await send(wecom_native, handle, **fields) == result
    assert len(server.rows("aibot_upload_media_init")) == 1

    image = tmp_path / "image.png"
    Image.new("RGB", (1, 1), "white").save(image)
    audio = tmp_path / "audio.amr"
    audio.write_bytes(b"#!AMR\nfixture")
    for kind, part, expected_type in [
        ("image", {"type": "image", "image_url": str(image)}, "image"),
        ("audio", {"type": "audio", "data": str(audio)}, "voice"),
    ]:
        fresh = await ingress(wecom_native, text_frame("send-" + kind))
        before = len(server.rows("aibot_upload_media_init"))
        result = await send(
            wecom_native,
            fresh["response_handle"],
            delivery=kind,
            content_parts=[part],
        )
        assert result["state"] == "acknowledged"
        assert len(server.rows("aibot_upload_media_init")) == before + 1
        assert (
            server.rows("aibot_upload_media_init")[-1]["body"]["type"]
            == expected_type
        )
        assert server.rows("aibot_respond_msg")[-1]["body"] == {
            "msgtype": expected_type,
            expected_type: {"media_id": "native-media"},
        }
    platform = driver._platform
    await driver.stop()
    before = server.rows()
    assert (
        await platform._download_media("http://127.0.0.1:1/not-called") is None
    )
    from qwenpaw_channel_wecom.errors import WeComDeliveryError

    with pytest.raises(WeComDeliveryError) as stopped:
        await send(
            wecom_native,
            handle,
            delivery="stopped",
            content_parts=[{"type": "text", "text": "no effect"}],
        )
    assert stopped.value.reason_code == "NOT_CONNECTED"
    assert stopped.value.side_effect_possible is False
    assert stopped.value.retryable is False
    assert server.rows() == before
