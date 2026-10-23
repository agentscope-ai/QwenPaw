"""Literal legacy business assertions across real official plugin workers."""

import asyncio
from pathlib import Path
import threading

import pytest

from extension_process_suite import runtime, eventually, identity
from g2_official_process_suite import (
    broker,
    mattermost,
    forbid_host_sdk_import,
    mqtt,
    mm,
    route,
    request_text,
    typing_rows,
    BOT_USER_ID,
    BOT_USERNAME,
)


def requests_for(server, method, path):
    return [
        body
        for verb, url, body in server.requests
        if verb == method and url.split("?", 1)[0] == path
    ]


def history(*posts):
    return {
        "order": [post["id"] for post in reversed(posts)],
        "posts": {post["id"]: post for post in posts},
    }


@pytest.mark.asyncio
async def test_mqtt_empty_and_invalid_native_payloads_do_not_reach_agent(
    runtime, broker
):
    rt = await mqtt(runtime, broker)
    for payload in (
        "",
        "   ",
        "{}",
        '{"text":""}',
        "[]",
        "null",
        '{"text":42}',
        b"\xff\xfe\x00\x01",
    ):
        broker.emit("in/ignored", payload)
    broker.emit("in/fence", "valid processing fence")
    await eventually(lambda: len(broker.publishes) == 1)
    assert len(rt.ws.requests) == 1
    assert rt.ws.requests[0].session_id == "mqtt:fence"
    assert "valid processing fence" in request_text(rt.ws.requests[0])
    assert broker.publishes == [("out/fence", "host answer", 2)]


@pytest.mark.asyncio
async def test_mqtt_malformed_json_is_legacy_plain_text(runtime, broker):
    rt = await mqtt(runtime, broker)
    broker.emit("copaw/in/my-device-001", '{"unfinished":')
    await eventually(lambda: len(broker.publishes) == 1)
    assert len(rt.ws.requests) == 1
    assert rt.ws.requests[0].session_id == "mqtt:in"
    assert '{"unfinished":' in request_text(rt.ws.requests[0])
    assert broker.publishes == [("out/in", "host answer", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,meta,expected",
    [
        ("mqtt:session-device", {"client_id": "meta-device"}, "meta-device"),
        ("mqtt:session-device", {}, "session-device"),
        ("mqtt:session-device", {"client_id": ""}, "session-device"),
        ("other-session", {}, "fallback-user"),
    ],
)
async def test_mqtt_neutral_target_keeps_meta_session_user_precedence(
    runtime, broker, session, meta, expected
):
    rt = await mqtt(runtime, broker)
    target = rt.channel.to_handle_from_target(
        user_id="fallback-user", session_id=session
    )
    await rt.channel.send_content_parts(
        target, [{"type": "text", "text": "target proof"}], dict(meta)
    )
    assert broker.publishes == [("out/" + expected, "target proof", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session,meta,channel,root",
    [
        (
            "mattermost_dm:session-channel",
            {"mm_channel_id": "meta-channel", "root_id": "root-one"},
            "meta-channel",
            "root-one",
        ),
        ("mattermost_dm:session-channel", {}, "session-channel", ""),
        ("mattermost_thread:unmapped-root", {}, "fallback-channel", ""),
    ],
)
async def test_mattermost_neutral_target_keeps_original_precedence(
    runtime, mattermost, session, meta, channel, root
):
    rt = await mm(runtime, mattermost)
    target = rt.channel.to_handle_from_target(
        user_id="fallback-channel", session_id=session
    )
    await rt.channel.send_content_parts(
        target, [{"type": "text", "text": "target proof"}], dict(meta)
    )
    assert mattermost.posts == [
        {"channel_id": channel, "root_id": root, "message": "target proof"}
    ]


@pytest.mark.asyncio
async def test_mattermost_first_dm_history_is_once_and_chronological(
    runtime, mattermost
):
    path = "/api/v4/channels/dm-history/posts"
    mattermost.responses[path] = (
        200,
        history(
            {"id": "old-user", "user_id": "human", "message": "OLD USER"},
            {"id": "old-bot", "user_id": BOT_USER_ID, "message": "OLD BOT"},
        ),
    )
    rt = await mm(runtime, mattermost)
    mattermost.push_dm_post(
        text="FIRST QUESTION",
        channel_id="dm-history",
        user_id="human",
        post_id="first",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    mattermost.push_dm_post(
        text="SECOND QUESTION",
        channel_id="dm-history",
        user_id="human",
        post_id="second",
    )
    await eventually(lambda: len(mattermost.posts) == 2)
    first, second = [request_text(request) for request in rt.ws.requests]
    assert (
        first.index("User: OLD USER")
        < first.index("Bot: OLD BOT")
        < first.index("FIRST QUESTION")
    )
    assert "[Recent 20 DM context messages]" in first
    assert "OLD USER" not in second and "OLD BOT" not in second
    assert "SECOND QUESTION" in second
    assert len(requests_for(mattermost, "GET", path)) == 1


@pytest.mark.asyncio
async def test_mattermost_bot_reply_gap_excludes_processed_trigger_and_bot_sequence(
    runtime, mattermost
):
    path = "/api/v4/posts/root-gap/thread"
    posts = [
        {
            "id": "processed",
            "user_id": "human",
            "message": "PROCESSED TRIGGER",
            "create_at": 1000,
        },
        {
            "id": "bot-a",
            "user_id": BOT_USER_ID,
            "message": "BOT PART A",
            "create_at": 2000,
        },
        {
            "id": "bot-b",
            "user_id": BOT_USER_ID,
            "message": "BOT PART B",
            "create_at": 3000,
        },
        {
            "id": "gap-a",
            "user_id": "other",
            "message": "GAP A",
            "create_at": 4000,
        },
        {
            "id": "gap-b",
            "user_id": "human",
            "message": "GAP B",
            "create_at": 5000,
        },
    ]
    mattermost.responses[path] = (200, history(*posts))
    rt = await mm(runtime, mattermost)
    mattermost.push_channel_post(
        text="@" + BOT_USERNAME + " CURRENT QUESTION",
        channel_id="group",
        user_id="human",
        post_id="current",
        root_id="root-gap",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    text = request_text(rt.ws.requests[0])
    assert "[Thread context supplement (unprocessed by bot)]" in text
    assert (
        text.index("GAP A")
        < text.index("GAP B")
        < text.index("CURRENT QUESTION")
    )
    assert all(
        value not in text
        for value in ("PROCESSED TRIGGER", "BOT PART A", "BOT PART B")
    )
    assert mattermost.posts[0]["root_id"] == "root-gap"


@pytest.mark.asyncio
async def test_mattermost_concurrent_first_contact_serializes_only_same_session(
    runtime, mattermost
):
    path = "/api/v4/channels/dm-concurrent/posts"
    gate = threading.Event()
    mattermost.response_gates[path] = gate
    mattermost.responses[path] = (
        200,
        history(
            {
                "id": "history",
                "user_id": "human",
                "message": "ONE INITIAL CONTEXT",
            }
        ),
    )
    rt = await mm(runtime, mattermost)
    try:
        mattermost.push_dm_post(
            text="FIRST",
            channel_id="dm-concurrent",
            user_id="human",
            post_id="first",
        )
        await eventually(
            lambda: len(requests_for(mattermost, "GET", path)) == 1
        )
        mattermost.push_dm_post(
            text="SECOND",
            channel_id="dm-concurrent",
            user_id="human",
            post_id="second",
        )
        mattermost.push_dm_post(
            text="OTHER SESSION FENCE",
            channel_id="other-dm",
            user_id="other",
            post_id="other",
        )
        await eventually(
            lambda: any(
                "OTHER SESSION FENCE" in request_text(request)
                for request in rt.ws.requests
            )
        )
        assert [request.session_id for request in rt.ws.requests] == [
            "mattermost_dm:other-dm"
        ]
        gate.set()
        await eventually(
            lambda: len(rt.ws.requests) == len(mattermost.posts) == 3
        )
        same = [
            request_text(request)
            for request in rt.ws.requests
            if request.session_id == "mattermost_dm:dm-concurrent"
        ]
        assert len(same) == 2
        assert "FIRST" in same[0] and "ONE INITIAL CONTEXT" in same[0]
        assert "SECOND" in same[1] and "ONE INITIAL CONTEXT" not in same[1]
        assert len(requests_for(mattermost, "GET", path)) == 1
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_mattermost_acl_denial_does_not_consume_first_dm_context(
    runtime, mattermost
):
    path = "/api/v4/channels/dm-acl/posts"
    mattermost.responses[path] = (
        200,
        history(
            {
                "id": "history",
                "user_id": "human",
                "message": "INITIAL CONTEXT AFTER APPROVAL",
            }
        ),
    )
    rt = await mm(
        runtime, mattermost, access_control_dm=True, show_typing=True
    )
    mattermost.push_dm_post(
        text="DENIED FIRST",
        channel_id="dm-acl",
        user_id="human",
        post_id="denied",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert rt.ws.requests == [] and typing_rows(mattermost) == []
    assert rt.channel._get_acl_store().approve_pending("mattermost", "human")
    mattermost.push_dm_post(
        text="AUTHORIZED FIRST",
        channel_id="dm-acl",
        user_id="human",
        post_id="authorized",
    )
    await eventually(lambda: len(mattermost.posts) == 2)
    assert len(rt.ws.requests) == 1
    text = request_text(rt.ws.requests[0])
    assert (
        "INITIAL CONTEXT AFTER APPROVAL" in text and "AUTHORIZED FIRST" in text
    )
    assert "DENIED FIRST" not in text
    assert len(requests_for(mattermost, "GET", path)) == 2


@pytest.mark.asyncio
async def test_mattermost_acl_denied_thread_is_not_followed_by_whitelisted_member(
    runtime, mattermost
):
    rt = await mm(
        runtime,
        mattermost,
        access_control_group=True,
        thread_follow_without_mention=True,
    )
    rt.channel._get_acl_store().add_to_whitelist("mattermost", "allowed")
    mattermost.push_channel_post(
        text="@" + BOT_USERNAME + " DENIED SEED",
        channel_id="group",
        user_id="denied",
        post_id="denied-root",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert rt.ws.requests == []
    mattermost.push_channel_post(
        text="SHOULD NOT FOLLOW",
        channel_id="group",
        user_id="allowed",
        post_id="not-followed",
        root_id="denied-root",
    )
    mattermost.push_channel_post(
        text="@" + BOT_USERNAME + " ACCEPTED FENCE",
        channel_id="group",
        user_id="allowed",
        post_id="fence-root",
    )
    await eventually(
        lambda: len(mattermost.posts) == 2
        and any(
            "ACCEPTED FENCE" in request_text(request)
            for request in rt.ws.requests
        )
    )
    assert len(rt.ws.requests) == 1
    assert "SHOULD NOT FOLLOW" not in request_text(rt.ws.requests[0])
    assert len(mattermost.posts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,kind",
    [
        ("picture.png", "image"),
        ("document.pdf", "file"),
        ("audio.mp3", "file"),
        ("video.mp4", "file"),
    ],
)
async def test_mattermost_inbound_attachment_uses_authorized_media_and_original_classification(
    runtime, mattermost, filename, kind
):
    content = b"native attachment bytes"
    mattermost.responses["/api/v4/files/native-file"] = (200, content)
    rt = await mm(runtime, mattermost)
    mattermost.push_dm_post(
        text="ATTACHMENT QUESTION",
        channel_id="dm-media",
        user_id="human",
        post_id="with-file",
        post_fields={
            "file_ids": ["native-file"],
            "metadata": {"files": [{"id": "native-file", "name": filename}]},
        },
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    parts = [
        part
        for message in rt.ws.requests[0].input
        for part in message.content
        if part.type == kind
    ]
    assert len(parts) == 1
    path = Path(parts[0].image_url if kind == "image" else parts[0].file_url)
    assert path.resolve().is_relative_to(rt.ws.workspace_dir.resolve())
    assert path.suffix == Path(filename).suffix
    assert path.read_bytes() == content


@pytest.mark.asyncio
async def test_mattermost_failed_attachment_download_keeps_text_and_no_phantom_file(
    runtime, mattermost
):
    mattermost.responses["/api/v4/files/missing-file"] = (404, {})
    rt = await mm(runtime, mattermost)
    mattermost.push_dm_post(
        text="QUESTION WITHOUT MISSING FILE",
        channel_id="dm-media",
        user_id="human",
        post_id="missing-file-post",
        post_fields={
            "file_ids": ["missing-file"],
            "metadata": {
                "files": [{"id": "missing-file", "name": "missing.pdf"}]
            },
        },
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert len(rt.ws.requests) == 1
    assert "QUESTION WITHOUT MISSING FILE" in request_text(rt.ws.requests[0])
    assert all(
        part.type == "text"
        for message in rt.ws.requests[0].input
        for part in message.content
    )
    assert (
        len(requests_for(mattermost, "GET", "/api/v4/files/missing-file")) == 1
    )
    assert not list((rt.ws.workspace_dir / "media").rglob("*"))


@pytest.mark.asyncio
async def test_mattermost_upload_failure_preserves_original_path_fallback(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    local = rt.ws.workspace_dir / "receipt.pdf"
    local.write_bytes(b"receipt bytes")
    mattermost.responses["/api/v4/files"] = (
        503,
        {"message": "controlled upload rejection"},
    )
    await rt.channel.send_content_parts(
        "dm-one",
        [
            {
                "type": "file",
                "file_url": local.as_uri(),
                "filename": "ignored-local-display.pdf",
            }
        ],
        {},
    )
    assert mattermost.posts == [
        {
            "channel_id": "dm-one",
            "root_id": "",
            "message": f"[Attachment: {local}]",
        }
    ]
    assert len(mattermost.file_uploads) == 1
    assert b'filename="receipt.pdf"' in mattermost.file_uploads[0]
    assert local.read_bytes() == b"receipt bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["\n", " "])
async def test_mattermost_long_text_uses_original_newline_or_space_boundary(
    runtime, mattermost, boundary
):
    rt = await mm(runtime, mattermost)
    text = "a" * 2500 + boundary + "b" * 2500
    await rt.channel.send_content_parts(
        "dm-one", [{"type": "text", "text": text}], {}
    )
    assert [post["message"] for post in mattermost.posts] == [
        "a" * 2500 + boundary,
        "b" * 2500,
    ]


@pytest.mark.asyncio
async def test_mattermost_later_chunk_failure_is_unknown_and_retry_has_no_effect(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    mattermost.response_sequences["/api/v4/posts"] = [
        (201, {"id": "first-delivered"}),
        (503, {"message": "second rejected"}),
    ]
    handle = await route(rt, "dm-one")
    params = {
        **identity(rt),
        "delivery_id": "partial-long-post",
        "to_handle": handle,
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "a" * 8001}],
    }
    for _ in range(2):
        result = await rt.process.call("channel.send", params)
        assert (
            result["state"] == "unknown"
            and result["delivery_id"] == "partial-long-post"
        )
    assert len(requests_for(mattermost, "POST", "/api/v4/posts")) == 2
    assert len(mattermost.posts) == 1
    assert mattermost.posts[0]["message"] == "a" * 4000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt",
    ["disconnect", b"not JSON", {}, {"file_infos": [{"id": "created-file"}]}],
)
async def test_mattermost_upload_uncertainty_retains_receipt_without_replay(
    runtime, mattermost, receipt
):
    rt = await mm(runtime, mattermost)
    local = rt.ws.workspace_dir / "uncertain.pdf"
    local.write_bytes(b"uploaded bytes")
    mattermost.responses["/api/v4/files"] = (
        0 if receipt == "disconnect" else 201,
        receipt,
    )
    mattermost.responses["/api/v4/posts"] = (
        503,
        {"message": "post refused after upload"},
    )
    handle = await route(rt, "dm-one")
    params = {
        **identity(rt),
        "delivery_id": "uncertain-upload",
        "to_handle": handle,
        "operation": "message.create",
        "content_parts": [{"type": "file", "file_url": local.as_uri()}],
    }
    for _ in range(2):
        result = await rt.process.call("channel.send", params)
        assert (
            result["state"] == "unknown"
            and result["delivery_id"] == "uncertain-upload"
        )
    assert len(mattermost.file_uploads) == 1
    assert mattermost.posts == []
    assert len(requests_for(mattermost, "POST", "/api/v4/posts")) == (
        1 if isinstance(receipt, dict) and receipt.get("file_infos") else 0
    )
    assert local.read_bytes() == b"uploaded bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["external", "symlink"])
async def test_mattermost_unauthorized_local_media_is_rejected_before_upload(
    runtime, mattermost, tmp_path, source
):
    rt = await mm(runtime, mattermost)
    external = tmp_path / "external-secret.pdf"
    external.write_bytes(b"outside workspace secret bytes")
    value = external
    if source == "symlink":
        value = rt.ws.workspace_dir / "disguised.pdf"
        value.symlink_to(external)
    handle = await route(rt, "dm-one")
    params = {
        **identity(rt),
        "delivery_id": "unauthorized-media",
        "to_handle": handle,
        "operation": "message.create",
        "content_parts": [{"type": "file", "file_url": value.as_uri()}],
    }
    result = await rt.process.call("channel.send", params)
    assert (
        result["state"] == "failed"
        and result["reason_code"] == "MEDIA_PATH_UNAUTHORIZED"
    )
    assert mattermost.file_uploads == mattermost.posts == []
    assert external.read_bytes() == b"outside workspace secret bytes"


@pytest.mark.asyncio
async def test_mattermost_explicit_media_dir_authorizes_external_file(
    runtime, mattermost, tmp_path
):
    directory = tmp_path / "allowed-external-media"
    directory.mkdir()
    local = directory / "allowed.pdf"
    local.write_bytes(b"explicitly permitted bytes")
    rt = await mm(runtime, mattermost, media_dir=str(directory))
    mattermost.responses["/api/v4/files"] = (
        201,
        {"file_infos": [{"id": "allowed-file"}]},
    )
    await rt.channel.send_content_parts(
        "dm-one", [{"type": "file", "file_url": local.as_uri()}], {}
    )
    assert len(mattermost.file_uploads) == 1
    assert b'filename="allowed.pdf"' in mattermost.file_uploads[0]
    assert b"explicitly permitted bytes" in mattermost.file_uploads[0]
    assert mattermost.posts == [
        {
            "channel_id": "dm-one",
            "root_id": "",
            "message": "",
            "file_ids": ["allowed-file"],
        }
    ]
    assert local.read_bytes() == b"explicitly permitted bytes"
