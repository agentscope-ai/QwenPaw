"""Remaining QQ legacy duties through the real private transport boundary."""

import time
from pathlib import Path

import pytest

from qq_native_support import eventually

pytest_plugins = ["qq_native_support"]


async def test_same_id_higher_seq_and_invalid_sources_do_not_enqueue(
    native_driver,
):
    driver, peer, _, server = native_driver
    platform = driver._platform
    original = {
        "id": "msg_replay_1",
        "author": {"user_openid": "sender_1"},
        "content": "hello",
        "attachments": [],
    }
    for sequence, event, data in [
        (2, "C2C_MESSAGE_CREATE", original),
        (3, "C2C_MESSAGE_CREATE", original),
        (4, "C2C_MESSAGE_CREATE", {**original, "id": "missing", "author": {}}),
        (5, "UNRECOGNIZED_EVENT", {**original, "id": "unknown"}),
        (6, "C2C_MESSAGE_CREATE", {**original, "id": "empty", "content": ""}),
        (7, "C2C_MESSAGE_CREATE", {**original, "id": "msg_b"}),
    ]:
        server.push({"op": 0, "s": sequence, "t": event, "d": data})
        await eventually(lambda: platform._state.last_seq == sequence)
        assert len(peer.batches) == (2 if sequence == 7 else 1)
    events = [batch["events"][0] for batch in peer.batches]
    assert [event["event_id"] for event in events] == [
        "message:msg_replay_1",
        "message:msg_b",
    ]
    assert all(
        event["sender_id"] == event["acl_sender_id"] == "sender_1"
        for event in events
    )
    assert all(
        event["metadata"]["session_id"] == "qq:c2c:sender_1"
        for event in events
    )


def test_reconnect_original_delays_limit_and_refresh_state(native_driver):
    from qwenpaw_channel_qq.platform import (
        _WSState,
        RECONNECT_DELAYS,
        MAX_QUICK_DISCONNECT_COUNT,
        RATE_LIMIT_DELAY,
    )

    platform = native_driver[0]._platform
    state = _WSState()
    assert platform._compute_reconnect_delay(state) == RECONNECT_DELAYS[0]
    for attempt in range(3):
        state.reconnect_attempts = attempt
        assert (
            platform._compute_reconnect_delay(state)
            == RECONNECT_DELAYS[attempt]
        )
    state.last_connect_time = time.time()
    state.session_id, state.last_seq = "old-session", 8
    for _ in range(MAX_QUICK_DISCONNECT_COUNT - 1):
        platform._compute_reconnect_delay(state)
    assert platform._compute_reconnect_delay(state) == RATE_LIMIT_DELAY
    assert state.session_id is None and state.last_seq is None
    assert state.should_refresh_token is True
    assert state.quick_disconnect_count == 0
    state.reconnect_attempts = 2
    platform.config["max_reconnect_attempts"] = 3
    assert platform._wait_and_check_reconnect(state) is False
    assert state.reconnect_attempts == 3


async def test_actual_token_401_preserves_typed_failure_without_retry(
    native_driver,
):
    from qwenpaw_channel_qq.errors import QQDeliveryError

    driver, _, _, server = native_driver
    platform = driver._platform
    platform._clear_token_cache()
    before = len(server.rows("/token"))
    server.queue(
        "POST",
        "/token",
        (401, {"message": "Unauthorized secret-not-for-wire"}),
    )
    with pytest.raises(QQDeliveryError, match="^QQ_TOKEN_REJECTED$"):
        await platform._get_access_token_async()
    assert len(server.rows("/token")) == before + 1
    assert platform._token_cache is None
    assert server.rows("/token")[-1]["body"] == {
        "appId": "local-app",
        "clientSecret": "local-secret",
    }


async def test_download_empty_traversal_and_failure_keep_original_contract(
    native_driver,
):
    driver, _, _, server = native_driver
    media = driver._platform.media
    server.assets["/secret.txt"] = b"file content"
    url = server.base + "/secret.txt"
    assert await media._download(url, "") is None
    assert server.rows("/secret.txt") == []
    result = await media._download(url, "../../../etc/passwd")
    assert result is not None
    assert "passwd" in result and "../../../etc/" not in result
    path = Path(result)
    assert path == media.directory / "passwd"
    assert path.read_bytes() == b"file content"
    server.queue("GET", "/failure.jpg", (503, {"message": "unavailable"}))
    assert (
        await media.parse_attachments(
            [{"url": server.base + "/failure.jpg", "filename": "file.jpg"}]
        )
        == []
    )
    assert len(server.rows("/failure.jpg")) == 1
    assert not (media.directory / "file.jpg").exists()
    assert not list(media.directory.glob(".qq-download-*"))


def test_original_extension_mime_and_voice_inputs(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "plugins/channel/qq")
    )
    from qwenpaw_channel_qq.media import _resolve_attachment_type

    for name in ("photo.jpg", "photo.png", "photo.gif", "photo.webp"):
        assert _resolve_attachment_type("", name) == "image"
    for name in ("video.mp4", "video.avi", "video.mov"):
        assert _resolve_attachment_type("", name) == "video"
    for name in ("audio.mp3", "audio.wav", "audio.ogg"):
        assert _resolve_attachment_type("", name) == "audio"
    for mime, expected in (
        ("image/jpeg", "image"),
        ("video/mp4", "video"),
        ("audio/mpeg", "audio"),
    ):
        assert _resolve_attachment_type(mime, "file") == expected
    assert _resolve_attachment_type("voice", "audio.silk") == "audio"
    assert _resolve_attachment_type("", "document.pdf") == "file"
    assert _resolve_attachment_type("application/pdf", "doc") == "file"
