"""QQ native transports and real Driver; host boundary is not Core proof."""

import asyncio
import hashlib
import json

import pytest

pytest.register_assert_rewrite("qq_native_support")

from qwenpaw.channel_protocol.models import (
    ResponseFinishParams,
    ResponseOutcome,
)

from qq_native_support import (
    eventually,
    open_route,
    send,
)

pytest_plugins = ["qq_native_support"]
TEXT = [{"type": "text", "text": "  exact answer  "}]


@pytest.mark.parametrize(
    "target,path,sequenced",
    [
        ("qq:c2c:user-A", "/v2/users/user-A/messages", True),
        ("qq:group:group-A", "/v2/groups/group-A/messages", True),
        ("qq:guild:channel-A", "/channels/channel-A/messages", False),
        ("qq:dm:guild-A", "/dms/guild-A/messages", False),
    ],
)
async def test_native_four_route_reply_bytes_and_no_bot_prefix(
    native_driver, target, path, sequenced
):
    driver, peer, identity, server = native_driver
    handle = await open_route(
        peer, identity, target, message_id="original-msg"
    )
    result = await send(peer, identity, handle, TEXT)
    assert result["state"] == "acknowledged"
    expected = {
        "markdown": {"content": "exact answer"},
    }
    if sequenced:
        expected.update(msg_type=2, msg_seq=1)
    expected["msg_id"] = "original-msg"
    assert server.api_rows() == [
        {
            "method": "POST",
            "path": path,
            "body": expected,
            "raw": json.dumps(
                expected, ensure_ascii=False, separators=(",", ":")
            ).encode(),
            "content_type": "application/json",
            "auth": "QQBot native-token",
        }
    ]
    assert len(server.rows("/token")) == 1
    assert server.rows("/token")[0]["body"] == {
        "appId": "local-app",
        "clientSecret": "local-secret",
    }
    policy = driver.response_policy(handle).to_mapping()
    assert policy["streaming"] is False and policy["prepare"] is False
    assert policy["completion_reaction"] is False
    assert policy["send_format"] == {
        "direct_prefix": False,
        "parts_configured_prefix": False,
        "parts_metadata_prefix": False,
        "stream_prefix": False,
    }
    assert driver.response_policy(handle).send_format.parts_strip_text is True


@pytest.mark.parametrize(
    "target,path",
    [
        ("qq:legacy-user", "/v2/users/legacy-user/messages"),
        ("group:legacy-group", "/v2/groups/legacy-group/messages"),
        ("channel:legacy-channel", "/channels/legacy-channel/messages"),
    ],
)
async def test_legacy_handles_send_to_original_native_target(
    native_driver, target, path
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, target)
    assert (await send(peer, identity, handle, TEXT))[
        "state"
    ] == "acknowledged"
    assert [r["path"] for r in server.api_rows()] == [path]


async def test_durable_recipient_and_trusted_logical_session_are_independent(
    native_driver,
):
    driver, peer, identity, server = native_driver
    handle = await open_route(
        peer,
        identity,
        "qq:group:group-A",
        message_type="c2c",
        sender_id="wrong-user",
        group_openid="wrong-group",
        session_id="qq:c2c:wrong-user",
    )
    assert (await send(peer, identity, handle, TEXT))[
        "state"
    ] == "acknowledged"
    assert [r["path"] for r in server.api_rows()] == [
        "/v2/groups/group-A/messages"
    ]
    route = driver._route_attrs(handle)
    assert route["message_type"] == "group"
    assert route["group_openid"] == "group-A"
    assert route["session_id"] == "qq:c2c:wrong-user"
    assert route["root_session_id"] == "qq:c2c:wrong-user"


async def test_definite_markdown_then_url_rejection_is_only_fallback_chain(
    native_driver,
):
    _, peer, identity, server = native_driver
    path = "/v2/users/user-A/messages"
    server.queue(
        "POST",
        path,
        (400, {"code": 50056}),
        (400, {"code": 304003}),
        (200, {"id": "final-native"}),
    )
    handle = await open_route(peer, identity, message_id="reply-A")
    result = await send(
        peer,
        identity,
        handle,
        [
            {
                "type": "text",
                "text": "see https://example.org/x and example.com",
            }
        ],
    )
    assert result["state"] == "acknowledged"
    assert [r["body"] for r in server.rows(path)] == [
        {
            "markdown": {
                "content": "see https://example.org/x and example.com"
            },
            "msg_type": 2,
            "msg_seq": 1,
            "msg_id": "reply-A",
        },
        {
            "content": "see [链接已省略] and example.com",
            "msg_type": 0,
            "msg_seq": 2,
            "msg_id": "reply-A",
        },
        {
            "content": "see [链接已省略] and [链接已省略]",
            "msg_type": 0,
            "msg_seq": 3,
            "msg_id": "reply-A",
        },
    ]


@pytest.mark.parametrize(
    "action,state",
    [
        ("disconnect", "unknown"),
        ((503, {"code": 50056, "message": "markdown URL 304003"}), "unknown"),
        ((403, {"message": "permission denied"}), "failed"),
    ],
)
async def test_native_uncertainty_and_nonvalidation_errors_never_replay(
    native_driver, action, state
):
    driver, peer, identity, server = native_driver
    path = "/v2/users/user-A/messages"
    server.queue("POST", path, action)
    handle = await open_route(peer, identity, message_id="reply-A")
    first = await send(peer, identity, handle, TEXT)
    assert first["state"] == state
    assert await send(peer, identity, handle, TEXT) == first
    assert len(server.rows(path)) == 1
    row = server.rows(path)[0]
    native = [
        ref
        for ref in driver._routes.snapshot(handle).resource_refs
        if ref.kind == "qq.native"
    ]
    assert len(native) == 1
    attrs = dict(native[0].attributes)
    assert attrs["body_sha256"] == hashlib.sha256(row["raw"]).hexdigest()
    assert attrs["body_bytes"] == str(len(row["raw"]))
    assert attrs["msg_seq"] == "1" and attrs["msg_id"] == "reply-A"
    await peer.methods["channel.response.finish"](
        ResponseFinishParams(
            **identity,
            response_handle=handle,
            outcome=ResponseOutcome.COMPLETED,
        ),
        None,
    )
    after_finish = await send(peer, identity, handle, TEXT)
    if state == "unknown":
        assert after_finish == first
    else:
        assert after_finish == {
            "delivery_id": "delivery-A",
            "state": "failed",
            "reason_code": "RESPONSE_CLOSED",
            "retryable": False,
        }
    assert len(server.rows(path)) == 1
    if state == "unknown":
        from qwenpaw.channel_protocol.response_receipts import receipt_key

        archived = (await peer.call("host.receipt.get", {
            "key": receipt_key("qq.shared.responses", handle),
        }))["value"]
        assert archived["cleanup_state"] == "complete"
        assert any(
            ref["kind"] == "qq.native"
            and ref["attributes"]["body_sha256"] == attrs["body_sha256"]
            for ref in archived["resource_refs"]
        )


async def test_successful_first_chunk_then_unknown_keeps_two_effects(
    native_driver,
):
    _, peer, identity, server = native_driver
    path = "/v2/users/user-A/messages"
    server.queue("POST", path, (200, {"id": "first"}), (503, {"code": 50056}))
    handle = await open_route(peer, identity)
    parts = [{"type": "text", "text": "x" * 3001}]
    result = await send(peer, identity, handle, parts)
    assert result["state"] == "unknown"
    assert [r["body"]["markdown"]["content"] for r in server.rows(path)] == [
        "x" * 3000,
        "x",
    ]
    assert await send(peer, identity, handle, parts) == result
    assert len(server.rows(path)) == 2


async def test_reply_sequences_share_msgid_but_proactive_responses_are_separate(
    native_driver,
):
    _, peer, identity, server = native_driver
    for index in range(2):
        handle = await open_route(peer, identity, message_id="same-original")
        assert (
            await send(peer, identity, handle, TEXT, delivery=f"reply-{index}")
        )["state"] == "acknowledged"
    for index in range(2):
        handle = await open_route(peer, identity)
        assert (
            await send(
                peer, identity, handle, TEXT, delivery=f"proactive-{index}"
            )
        )["state"] == "acknowledged"
    assert [r["body"]["msg_seq"] for r in server.api_rows()] == [1, 2, 1, 1]


@pytest.mark.parametrize(
    "source,parts,want_ids,want_text",
    [
        (
            "direct",
            [
                {
                    "type": "text",
                    "text": " hi [Image: https://cdn.example/p.png] ",
                }
            ],
            [None],
            "hi",
        ),
        (
            "content_parts",
            [
                {"type": "text", "text": " hi "},
                {"type": "text", "text": "no"},
                {"type": "image", "image_url": "https://cdn.example/p.png"},
            ],
            [None],
            "hi \nno",
        ),
        (
            "content_parts",
            [
                {"type": "image", "image_url": "https://cdn.example/1.png"},
                {"type": "image", "image_url": "https://cdn.example/2.png"},
            ],
            ["reply-A", None],
            None,
        ),
        (
            "media",
            [{"type": "image", "image_url": "https://cdn.example/p.png"}],
            [None],
            None,
        ),
    ],
)
async def test_three_sources_preserve_text_and_first_media_reply_rule(
    native_driver, source, parts, want_ids, want_text
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, message_id="reply-A")
    assert (await send(peer, identity, handle, parts, source=source))[
        "state"
    ] == "acknowledged"
    rows = server.api_rows()
    uploads = [r for r in rows if r["path"].endswith("/files")]
    assert len(uploads) == len(want_ids)
    assert all(
        r["body"]["file_type"] == 1 and r["body"]["srv_send_msg"] is False
        for r in uploads
    )
    messages = [r["body"] for r in rows if r["path"].endswith("/messages")]
    media = [body for body in messages if body.get("msg_type") == 7]
    assert [body.get("msg_id") for body in media] == want_ids
    assert all(
        body["media"] == {"file_info": "native-file-info"} for body in media
    )
    text = [
        body["markdown"]["content"] for body in messages if "markdown" in body
    ]
    assert text == ([] if want_text is None else [want_text])
    if source == "direct":
        assert "content" not in media[0]
    else:
        assert all(body.get("content", "").endswith(".png") for body in media)


async def test_plain_direct_sanitizes_before_image_tag_extraction(
    native_driver,
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, markdown_enabled=False)
    assert (
        await send(
            peer,
            identity,
            handle,
            [
                {
                    "type": "text",
                    "text": "hi [Image: https://cdn.example/p.png]",
                }
            ],
        )
    )["state"] == "acknowledged"
    assert [r["body"] for r in server.api_rows()] == [
        {"content": "hi [Image: [链接已省略]", "msg_type": 0, "msg_seq": 1}
    ]


@pytest.mark.parametrize(
    "target,path",
    [
        ("qq:guild:channel-A", "/channels/channel-A/messages"),
        ("qq:dm:guild-A", "/dms/guild-A/messages"),
    ],
)
async def test_guild_and_dm_preserve_video_url_support(
    native_driver, target, path
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, target, message_id="reply-A")
    assert (
        await send(
            peer,
            identity,
            handle,
            [{"type": "video", "video_url": "https://cdn.example/v.mp4"}],
            source="content_parts",
        )
    )["state"] == "acknowledged"
    assert [(r["path"], r["body"]) for r in server.api_rows()] == [
        (path, {"image": "https://cdn.example/v.mp4", "msg_id": "reply-A"})
    ]


async def test_real_data_url_upload_bytes_multipart_and_temp_cleanup(
    native_driver,
):
    driver, peer, identity, server = native_driver
    parts = [
        {"type": "image", "image_url": "data:image/png;base64,cG5nLWRhdGE="}
    ]
    first = await open_route(peer, identity)
    assert (await send(peer, identity, first, parts, source="media"))[
        "state"
    ] == "acknowledged"
    assert server.rows("/v2/users/user-A/files")[0]["body"] == {
        "file_type": 1,
        "srv_send_msg": False,
        "file_data": "cG5nLWRhdGE=",
        "file_name": "file.png",
    }
    second = await open_route(
        peer, identity, "qq:guild:channel-A", message_id="reply-A"
    )
    assert (
        await send(
            peer,
            identity,
            second,
            parts,
            source="content_parts",
            delivery="guild-data",
        )
    )["state"] == "acknowledged"
    row = server.rows("/channels/channel-A/messages")[0]
    assert row["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="file_image"; filename="image.png"' in row["raw"]
    assert b"\r\n\r\npng-data\r\n" in row["raw"]
    assert b'name="msg_id"\r\n\r\nreply-A\r\n' in row["raw"]
    assert not list(driver._platform.media.directory.glob("qq-media-*"))


@pytest.mark.parametrize(
    "target,part",
    [
        (
            "qq:group:group-A",
            {"type": "file", "file_url": "https://cdn.example/f.pdf"},
        ),
        (
            "qq:group:group-A",
            {"type": "audio", "data": "https://cdn.example/s.mp3"},
        ),
        (
            "qq:guild:channel-A",
            {"type": "audio", "data": "https://cdn.example/s.amr"},
        ),
        (
            "qq:dm:guild-A",
            {"type": "file", "file_url": "https://cdn.example/f.pdf"},
        ),
    ],
)
async def test_unsupported_media_is_explicit_failure_with_zero_native_effect(
    native_driver, target, part
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, target)
    result = await send(peer, identity, handle, [part], source="media")
    assert (
        result["state"] == "failed"
        and result["reason_code"] == "MEDIA_TYPE_UNSUPPORTED"
    )
    assert server.api_rows() == []


async def test_group_voice_is_type3_and_workspace_symlink_cannot_escape(
    native_driver, tmp_path
):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity, "qq:group:group-A")
    assert (
        await send(
            peer,
            identity,
            handle,
            [{"type": "audio", "data": "https://cdn.example/v.silk"}],
            source="media",
        )
    )["state"] == "acknowledged"
    assert server.rows("/v2/groups/group-A/files")[0]["body"]["file_type"] == 3
    outside = tmp_path.parent / (tmp_path.name + "-outside.png")
    outside.write_bytes(b"must not upload")
    link = tmp_path / "escaped.png"
    link.symlink_to(outside)
    before = len(server.api_rows())
    result = await send(
        peer,
        identity,
        handle,
        [{"type": "image", "image_url": str(link)}],
        source="media",
        delivery="escape",
    )
    assert (
        result["state"] == "failed"
        and result["reason_code"] == "MEDIA_PATH_UNAUTHORIZED"
    )
    assert len(server.api_rows()) == before


@pytest.mark.parametrize(
    "event,author,coordinates,session,conversation",
    [
        (
            "C2C_MESSAGE_CREATE",
            {"user_openid": "actor-A"},
            {},
            "qq:c2c:actor-A",
            "actor-A",
        ),
        (
            "GROUP_AT_MESSAGE_CREATE",
            {"member_openid": "actor-A"},
            {"group_openid": "group-A"},
            "qq:group:group-A",
            "group-A",
        ),
        (
            "AT_MESSAGE_CREATE",
            {"id": "actor-A"},
            {"channel_id": "channel-A", "guild_id": "guild-A"},
            "qq:guild:channel-A",
            "channel-A",
        ),
        (
            "DIRECT_MESSAGE_CREATE",
            {"id": "actor-A"},
            {"channel_id": "channel-A", "guild_id": "guild-A"},
            "qq:dm:guild-A",
            "guild-A",
        ),
    ],
)
async def test_real_ws_four_sources_preserve_actor_session_and_no_thread_fork(
    native_driver, event, author, coordinates, session, conversation
):
    driver, peer, _, server = native_driver
    server.push(
        {
            "op": 0,
            "s": 2,
            "t": event,
            "d": {
                "id": "incoming-A",
                "content": " hello ",
                "author": author,
                "thread_id": "untrusted-thread",
                **coordinates,
            },
        }
    )
    await eventually(lambda: driver._platform._state.last_seq == 2)
    assert len(peer.batches) == 1
    actual = peer.batches[0]["events"][0]
    assert actual["event_id"] == "message:incoming-A"
    assert actual["sender_id"] == actual["acl_sender_id"] == "actor-A"
    assert actual["conversation"] == {
        "id": conversation,
        "type": (
            "group"
            if event in {"GROUP_AT_MESSAGE_CREATE", "AT_MESSAGE_CREATE"}
            else "dm"
        ),
        "thread_id": None,
    }
    assert (
        actual["metadata"]["session_id"]
        == actual["metadata"]["debounce_key"]
        == session
    )
    assert actual["content_parts"] == [{"type": "text", "text": "hello"}]
    server.push(
        {
            "op": 0,
            "s": 2,
            "t": event,
            "d": {
                "id": "different-id-at-old-seq",
                "content": "replayed",
                "author": author,
                **coordinates,
            },
        }
    )
    pong = server.connections[-1].ping(b"native-control-ping")
    assert await asyncio.to_thread(pong.wait, 1)
    assert len(peer.batches) == 1
    server.push(
        {
            "op": 0,
            "s": 3,
            "t": event,
            "d": {
                "id": "next-A",
                "content": "newer",
                "author": author,
                **coordinates,
            },
        }
    )
    await eventually(lambda: driver._platform._state.last_seq == 3)
    assert len(peer.batches) == 2
    assert peer.batches[1]["events"][0]["event_id"] == "message:next-A"


async def test_ws_watermark_and_dedup_commit_only_after_host_admission(
    native_driver,
):
    driver, peer, _, server = native_driver
    platform = driver._platform
    peer.admission_release = asyncio.Event()
    server.push(
        {
            "op": 0,
            "s": 2,
            "t": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "held-A",
                "content": "held",
                "author": {"user_openid": "actor-A"},
            },
        }
    )
    await peer.admission_entered.wait()
    assert platform._state.last_seq == 1
    assert "message:held-A" not in platform._seen_event_ids
    server.push(
        {
            "op": 0,
            "s": 3,
            "t": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "later-A",
                "content": "later",
                "author": {"user_openid": "actor-A"},
            },
        }
    )
    assert len(peer.batches) == 1
    peer.admission_release.set()
    await eventually(lambda: platform._state.last_seq == 3)
    assert [b["events"][0]["event_id"] for b in peer.batches] == [
        "message:held-A",
        "message:later-A",
    ]
    assert list(platform._seen_event_ids) == [
        "message:held-A",
        "message:later-A",
    ]


async def test_rejected_dispatch_resumes_from_committed_seq_then_accepts_replay(
    native_driver,
):
    driver, peer, _, server = native_driver
    peer.admissions.append(
        {
            "rejected_events": [
                {
                    "event_id": "message:retry-A",
                    "reason_code": "ACL_DENIED",
                    "retryable": False,
                }
            ]
        }
    )
    payload = {
        "op": 0,
        "s": 2,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "retry-A",
            "content": "retry",
            "author": {"user_openid": "actor-A"},
        },
    }
    server.push(payload)
    await eventually(lambda: any(frame["op"] == 6 for frame in server.frames))
    assert next(frame for frame in server.frames if frame["op"] == 6)["d"] == {
        "token": "QQBot native-token",
        "session_id": "native-session",
        "seq": 1,
    }
    assert driver._platform._state.last_seq == 1
    assert "message:retry-A" not in driver._platform._seen_event_ids
    await eventually(lambda: driver._connected)
    server.push(payload)
    await eventually(lambda: driver._platform._state.last_seq == 2)
    assert len(peer.batches) == 2


async def test_inbound_asr_wav_quote_and_prefix_use_real_downloads(
    native_driver,
):
    driver, peer, _, server = native_driver
    server.assets["/voice.wav"] = b"RIFF-real-wave"
    payload = {
        "op": 0,
        "s": 2,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "media-A",
            "content": "now",
            "author": {"user_openid": "actor-A"},
            "message_scene": {"ext": ["ref_msg_idx=old", "msg_idx=new"]},
            "msg_elements": [{"msg_idx": "old", "content": "quoted text"}],
            "attachments": [
                {
                    "type": "voice",
                    "filename": "asr.amr",
                    "asr_refer_text": "recognized speech",
                    "url": server.base + "/unused.amr",
                },
                {
                    "type": "voice",
                    "filename": "voice.silk",
                    "voice_wav_url": server.base + "/voice.wav",
                    "url": server.base + "/unused.silk",
                },
            ],
        },
    }
    server.push(payload)
    await eventually(lambda: driver._platform._state.last_seq == 2)
    parts = peer.batches[0]["events"][0]["content_parts"]
    assert parts[:2] == [
        {"type": "text", "text": "[quoted message: quoted text]\nnow"},
        {"type": "text", "text": "recognized speech"},
    ]
    from pathlib import Path

    assert (
        parts[2]["type"] == "audio"
        and Path(parts[2]["data"]).name == "voice.wav"
    )
    assert Path(parts[2]["data"]).read_bytes() == b"RIFF-real-wave"
    assert [r["path"] for r in server.api_rows()] == ["/voice.wav"]
    server.push(
        {
            "op": 0,
            "s": 3,
            "t": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "echo",
                "content": " [Bot] echo ",
                "author": {"user_openid": "actor-A"},
            },
        }
    )
    await eventually(lambda: driver._platform._state.last_seq == 3)
    assert len(peer.batches) == 1


async def test_native_heartbeat_control_pong_and_confirmed_owned_stop(
    native_driver,
):
    driver, _, _, server = native_driver
    platform = driver._platform
    await eventually(lambda: any(frame["op"] == 1 for frame in server.frames))
    assert next(frame for frame in server.frames if frame["op"] == 1)["d"] == 1
    identify = next(frame for frame in server.frames if frame["op"] == 2)
    assert identify["d"] == {
        "token": "QQBot native-token",
        "intents": (1 << 30) | (1 << 12) | (1 << 25) | (1 << 1) | (1 << 26),
        "shard": [0, 1],
    }
    pong = server.connections[-1].ping(b"independent-native-ping")
    assert await asyncio.to_thread(pong.wait, 1)
    thread, client, sync_client, socket = (
        platform._ws_thread,
        platform._http,
        platform._sync_http,
        platform._ws,
    )
    timers = [
        timer
        for heartbeat in platform._heartbeats
        for timer in heartbeat._timers
    ]
    await driver.stop()
    assert not thread.is_alive() and client.is_closed and sync_client.is_closed
    assert not socket.connected and all(
        not timer.is_alive() for timer in timers
    )
    assert (
        not platform._tasks
        and not platform._io_tasks
        and not platform._ack_tasks
        and not platform._callbacks
    )
    assert platform._ws_thread is None and driver._platform is None
    await driver.stop()


async def test_native_parts_merges_refusal_before_real_http_send(
    native_driver,
):
    driver, peer, identity, server = native_driver
    handle = await open_route(peer, identity)
    result = await driver._platform.send_parts(
        driver._route_attrs(handle),
        [
            {"type": "text", "text": " first "},
            {"type": "refusal", "refusal": "second"},
        ],
        "content_parts",
    )
    assert json.loads(result["message_ids"])
    assert [r["body"]["markdown"]["content"] for r in server.api_rows()] == [
        "first \nsecond"
    ]


@pytest.mark.parametrize(
    "result_actor,privileged",
    [("real-clicker", True), ("forged-actor", False)],
)
async def test_native_clicker_and_typed_result_match_confirmed_card_source(
    native_driver, result_actor, privileged
):
    """DTO consumption only; the test does not claim actual Core resolve."""
    driver, peer, identity, server = native_driver
    source = await open_route(
        peer, identity, "qq:group:group-A", message_id="source-message"
    )
    card = await send(
        peer,
        identity,
        source,
        [{"type": "text", "text": "approval prompt"}],
        source="content_parts",
        delivery="card-source",
        approval={
            "request_id": "request-A",
            "tool_name": "stored-tool",
            "severity": "high",
        },
    )
    assert card["state"] == "acknowledged"
    row = server.rows("/v2/groups/group-A/messages")[0]
    buttons = row["body"]["keyboard"]["content"]["rows"][0]["buttons"]
    assert [button["render_data"]["visited_label"] for button in buttons] == [
        "Received",
        "Received",
    ]
    data = json.loads(buttons[0]["action"]["data"])
    nonce = data["bid"]
    binding = driver._platform._cards.bindings[nonce]
    assert (
        binding.source_response_handle == source
        and binding.source_delivery_id == "card-source"
    )
    data.update(
        sender="forged-sender", sid="qq:c2c:wrong-user", tool="forged-tool"
    )
    server.push(
        {
            "op": 0,
            "s": 2,
            "t": "INTERACTION_CREATE",
            "d": {
                "id": "callback-A",
                "group_member_openid": "real-clicker",
                "group_openid": "group-A",
                "message_id": binding.message_id,
                "data": {"resolved": {"button_data": json.dumps(data)}},
            },
        }
    )
    await eventually(lambda: driver._platform._state.last_seq == 2)
    event = peer.batches[0]["events"][0]
    assert event["sender_id"] == event["acl_sender_id"] == "real-clicker"
    assert event["metadata"]["session_id"] == "qq:group:group-A"
    assert event["content_parts"] == [
        {"type": "text", "text": "/approval approve request-A"}
    ]
    assert server.rows("/interactions/callback-A")[0]["body"] == {"code": 0}
    assert len(server.rows("/v2/groups/group-A/messages")) == 1
    result = await send(
        peer,
        identity,
        event["response_handle"],
        [{"type": "text", "text": "ordinary-result"}],
        delivery="card-result",
        approval_resolution={
            "request_id": "request-A",
            "outcome": "approved",
            "actor_user_id": result_actor,
            "tool_name": "authoritative-tool",
        },
    )
    assert result["state"] == "acknowledged"
    messages = server.rows("/v2/groups/group-A/messages")
    assert len(messages) == 2
    assert messages[1]["body"]["markdown"]["content"] == (
        "✅ **Approved** by **licker**\nTool: `authoritative-tool`"
        if privileged
        else "ordinary-result"
    )
    assert messages[1]["body"]["msg_id"] == "source-message"


async def test_native_sequence_registry_keeps_original_eviction_and_instance_isolation(
    native_driver,
):
    from qwenpaw_channel_qq.platform import SequenceRegistry

    first, second = SequenceRegistry(), SequenceRegistry()
    assert first.next("message-A") == 1
    assert first.next("message-A") == 2
    assert first.next("message-A") == 3
    assert first.next("message-B") == 1
    assert first.next("message-B") == 2
    assert second.next("message-A") == 1
    bounded = SequenceRegistry()
    for i in range(1001):
        assert bounded.next(str(i)) == 1
    assert len(bounded._msg_seq) == 501
    assert bounded.next("500") == 2
    assert bounded.next("0") == 1


async def test_real_invalid_session_refreshes_token_and_identifies_without_resume(
    native_driver,
):
    driver, _, _, server = native_driver
    server.push({"op": 9, "d": False})
    await eventually(
        lambda: len([f for f in server.frames if f["op"] == 2]) == 2
    )
    await eventually(lambda: driver._connected)
    assert not [frame for frame in server.frames if frame["op"] == 6]
    assert len(server.rows("/token")) == 2
    assert driver._platform._state.last_seq == 1
    assert driver._platform._state.session_id == "native-session"
