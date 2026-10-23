"""Remaining original literals at actual platform and worker boundaries."""

import pytest

from extension_process_suite import runtime, eventually, identity
from g2_business_suite import requests_for
from g2_official_process_suite import (
    broker,
    mattermost,
    forbid_host_sdk_import,
    mqtt,
    mm,
    route,
    request_text,
    BOT_USERNAME,
    official_source,
)


@pytest.mark.asyncio
async def test_format_policy_failure_cleans_new_real_worker_route(runtime):
    from extension_process_suite import inspect
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime()
    await rt.process.call("fixture.fault", {"mode": "describe-error"})
    with pytest.raises(RpcError):
        await rt.channel.send("room-A", "no effect after bad policy", {})
    evidence = await inspect(rt)
    assert rt.ws.requests == []
    assert [row["operation"] for row in evidence["effects"]] == ["finish"]
    assert (
        len(evidence["finish_calls"]) == 1
        and evidence["finish_calls"][0]["outcome"] == "failed"
    )
    assert len(evidence["routes"]) == 1
    receipt = evidence["routes"][0]
    assert receipt["kind"] == "terminal" and receipt["outcome"] == "failed"
    assert receipt["cleanup_state"] == "complete"
    assert receipt["route_refs"] == receipt["resource_refs"] == []
    assert receipt["cleanup_completed_at_ms"] >= receipt["closed_at_ms"]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
@pytest.mark.parametrize("entry", ["send", "parts"])
async def test_reusing_caller_metadata_allows_two_sequential_real_deliveries(
    runtime, broker, mattermost, key, entry
):
    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    meta = {}
    for text in ("first delivery", "second delivery"):
        if entry == "send":
            await rt.channel.send("recipient", text, meta)
        else:
            await rt.channel.send_content_parts(
                "recipient", [{"type": "text", "text": text}], meta
            )
    assert (
        [(topic, body) for topic, body, _qos in broker.publishes]
        if key == "mqtt"
        else [
            (post["channel_id"], post["message"]) for post in mattermost.posts
        ]
    ) == [
        ("out/recipient" if key == "mqtt" else "recipient", text)
        for text in ("first delivery", "second delivery")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_reused_metadata_unknown_keeps_route_fingerprint_and_no_replay(
    runtime, broker, mattermost, key
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    if key == "mqtt":
        broker.confirm = False
    else:
        mattermost.responses["/api/v4/posts"] = (201, {})
    meta = {}
    with pytest.raises(ChannelDeliveryError) as first:
        await rt.channel.send_content_parts(
            "recipient", [{"type": "text", "text": "one unknown effect"}], meta
        )
    assert first.value.state == "unknown"
    handle, pending, policy = (
        meta["response_handle"],
        dict(meta["_pending_delivery"]),
        meta["_response_policy"],
    )
    with pytest.raises(ChannelDeliveryError) as repeated:
        await rt.channel.send_content_parts(
            "recipient", [{"type": "text", "text": "one unknown effect"}], meta
        )
    assert repeated.value.state == "unknown"
    assert (
        meta["response_handle"] == handle
        and meta["_pending_delivery"] == pending
        and meta["_response_policy"] is policy
    )
    assert (
        broker.publishes
        if key == "mqtt"
        else [post["message"] for post in mattermost.posts]
    ) == (
        [("out/recipient", "one unknown effect", 2)]
        if key == "mqtt"
        else ["one unknown effect"]
    )


@pytest.mark.asyncio
async def test_mqtt_without_authentication_and_normal_stop(runtime, broker):
    rt = await mqtt(runtime, broker, username="", password="")
    assert broker.connect_packets[0]["username"] == ""
    assert broker.connect_packets[0]["password"] == ""
    assert broker.connect_packets[0]["keepalive"] == 60
    broker.emit("in/device", "before normal close")
    await eventually(lambda: len(broker.publishes) == 1)
    receipt = await rt.manager.stop_one("mqtt")
    assert receipt.stopped and receipt.exited and not receipt.residual
    await eventually(lambda: not broker.clients)
    assert broker.connections == 1


@pytest.mark.asyncio
async def test_mqtt_original_subscription_topic_and_qos_are_on_real_wire(
    runtime, broker
):
    rt = await runtime(
        "mqtt",
        source_factory=official_source,
        host="127.0.0.1",
        port=broker.port,
        transport="tcp",
        subscribe_topic="test/topic",
        publish_topic="out/{client_id}",
        qos=2,
    )
    await eventually(lambda: bool(broker.subscription_packets))
    assert broker.subscription_packets == [{"topic": "test/topic", "qos": 2}]
    assert rt.process.health_snapshot()["platform_state"] == "connected"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_agent_reply_keeps_explicit_host_configured_prefix(
    runtime, broker, mattermost, key
):
    rt = await (
        mqtt(runtime, broker, bot_prefix="[BOT] ")
        if key == "mqtt"
        else mm(runtime, mattermost, bot_prefix="[TestBot] ")
    )
    if key == "mqtt":
        broker.emit("in/agent", "agent reply prefix")
        await eventually(lambda: len(broker.publishes) == 1)
        body = broker.publishes[0][1]
    else:
        mattermost.push_dm_post(
            text="agent reply prefix",
            channel_id="dm-agent-prefix",
            post_id="agent-prefix",
        )
        await eventually(lambda: len(mattermost.posts) == 1)
        body = mattermost.posts[0]["message"]
    assert len(rt.ws.requests) == 1
    assert body == rt.channel.bot_prefix + "  host answer"


@pytest.mark.asyncio
async def test_mqtt_refused_connack_never_subscribes_or_runs_agent(
    runtime, broker
):
    from qwenpaw.plugins.registry import PluginRegistry

    broker.connect_code = 4
    with pytest.raises(
        RuntimeError, match="Projection channel failed: CHANNEL_NOT_CONNECTED"
    ):
        await mqtt(runtime, broker)
    assert (
        broker.connect_packets
        and broker.subscriptions == broker.publishes == []
    )
    assert not PluginRegistry().runtime_owners.leases("mqtt")
    assert [ws.requests for ws in runtime.workspaces] == [[]]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [(401, {}), (0, {}), (200, {})])
async def test_mattermost_identity_failure_is_not_connected(
    runtime, mattermost, reply
):
    from qwenpaw.plugins.registry import PluginRegistry

    mattermost.responses["/api/v4/users/me"] = reply
    with pytest.raises(
        RuntimeError, match="Projection channel failed: CHANNEL_NOT_CONNECTED"
    ):
        await mm(runtime, mattermost)
    assert requests_for(mattermost, "GET", "/api/v4/users/me") == [{}]
    assert not mattermost.has_connection
    assert mattermost.posts == []
    assert not PluginRegistry().runtime_owners.leases("mattermost")
    assert [ws.requests for ws in runtime.workspaces] == [[]]


@pytest.mark.asyncio
async def test_mattermost_partial_bot_identity_keeps_dm_support(
    runtime, mattermost
):
    mattermost.responses["/api/v4/users/me"] = (200, {"id": "user_123"})
    rt = await mm(runtime, mattermost)
    mattermost.push_dm_post(
        text="partial identity DM",
        channel_id="dm-partial",
        post_id="partial-id",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert rt.process.health_snapshot()["platform_state"] == "connected"
    assert rt.ws.requests[0].session_id == "mattermost_dm:dm-partial"
    assert "partial identity DM" in request_text(rt.ws.requests[0])


@pytest.mark.asyncio
async def test_mattermost_posted_literals_and_mention_cleanup(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    mattermost.push_channel_post(
        text="Hey @" + BOT_USERNAME + " help",
        channel_id="channel_123",
        user_id="user_abc",
        post_id="post_123",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    request = rt.ws.requests[0]
    assert request.user_id == "user_abc"
    assert request.session_id == "mattermost_thread:post_123"
    assert request.channel_meta["mm_channel_id"] == "channel_123"
    assert "@" + BOT_USERNAME not in request_text(request)
    assert all(
        part.type == "text"
        for message in request.input
        for part in message.content
    )
    assert any(
        headers.get("Authorization") == "Bearer local-test-token"
        for headers in mattermost.request_headers
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["path", "file_url", "data"])
async def test_mattermost_original_display_filename_and_file_retention(
    runtime, mattermost, source
):
    rt = await mm(runtime, mattermost)
    local = rt.ws.workspace_dir / "local.pdf"
    local.write_bytes(b"pdf-data")
    values = {
        "path": str(local),
        "file_url": local.as_uri(),
        "data": "data:application/pdf;base64,cGRmLWRhdGE=",
    }
    mattermost.responses["/api/v4/files"] = (
        201,
        {"file_infos": [{"id": "file-id"}]},
    )
    await rt.channel.send_content_parts(
        "recipient",
        [
            {
                "type": "file",
                "file_url": values[source],
                "filename": "report.pdf",
            }
        ],
        {},
    )
    expected = "report.pdf" if source == "data" else "local.pdf"
    assert len(mattermost.file_uploads) == 1
    assert ('filename="' + expected + '"').encode() in mattermost.file_uploads[
        0
    ]
    assert b"pdf-data" in mattermost.file_uploads[0]
    assert mattermost.posts == [
        {
            "channel_id": "recipient",
            "root_id": "",
            "message": "",
            "file_ids": ["file-id"],
        }
    ]
    assert local.read_bytes() == b"pdf-data"
    assert not list((rt.ws.workspace_dir / "media").glob("*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,label",
    [
        ("missing.pdf", "Attachment"),
        ("https://fixture.invalid/document.pdf", "Attachment"),
    ],
)
async def test_mattermost_missing_or_remote_media_preserves_text_fallback(
    runtime, mattermost, value, label
):
    rt = await mm(runtime, mattermost)
    actual = (
        str(rt.ws.workspace_dir / value) if value == "missing.pdf" else value
    )
    part = {
        "type": "file",
        "file_url": actual,
    }
    await rt.channel.send_content_parts("recipient", [part], {})
    assert mattermost.file_uploads == []
    assert mattermost.posts[0]["message"] == f"[{label}: {actual}]"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_disabled_and_empty_target_have_no_platform_effect(
    runtime, broker, mattermost, key
):
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    rt.channel.enabled = False
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_content_parts(
            "recipient", [{"type": "text", "text": "disabled"}], {}
        )
    assert caught.value.state == "failed"
    assert caught.value.reason_code == "CHANNEL_DISABLED"
    rt.channel.enabled = True
    with pytest.raises((RpcError, ValueError)):
        await route(rt, "")
    assert broker.publishes == mattermost.posts == []


@pytest.mark.asyncio
async def test_mattermost_local_image_uses_real_upload_and_post(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    local = rt.ws.workspace_dir / "photo.png"
    local.write_bytes(b"image fixture bytes")
    mattermost.responses["/api/v4/files"] = (
        201,
        {"file_infos": [{"id": "image-id"}]},
    )
    await rt.channel.send_content_parts(
        "recipient", [{"type": "image", "image_url": local.as_uri()}], {}
    )
    assert len(mattermost.file_uploads) == len(mattermost.posts) == 1
    assert b'filename="photo.png"' in mattermost.file_uploads[0]
    assert b"image fixture bytes" in mattermost.file_uploads[0]
    assert mattermost.posts[0]["file_ids"] == ["image-id"]
    assert len(requests_for(mattermost, "POST", "/api/v4/files")) == 1
    assert len(requests_for(mattermost, "POST", "/api/v4/posts")) == 1
    assert local.read_bytes() == b"image fixture bytes"


@pytest.mark.asyncio
async def test_mattermost_show_typing_disabled_keeps_message_flow(
    runtime, mattermost
):
    from g2_official_process_suite import typing_rows

    rt = await mm(runtime, mattermost, show_typing=False)
    mattermost.push_dm_post(
        text="no typing required",
        channel_id="dm-no-typing",
        post_id="no-typing",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert len(rt.ws.requests) == 1 and typing_rows(mattermost) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
@pytest.mark.parametrize("mode", ["send", "send-meta", "parts", "parts-meta"])
async def test_original_direct_send_does_not_add_configured_prefix(
    runtime, broker, mattermost, key, mode
):
    rt = await (
        mqtt(runtime, broker, bot_prefix="[BOT] ")
        if key == "mqtt"
        else mm(runtime, mattermost, bot_prefix="[TestBot] ")
    )
    target = "device-001" if key == "mqtt" else "channel_123"
    text = "Hello device" if key == "mqtt" else "Hello World"
    if mode in {"send", "send-meta"}:
        await rt.channel.send(
            target,
            text,
            {"bot_prefix": "[META]"} if mode == "send-meta" else {},
        )
    else:
        await rt.channel.send_content_parts(
            target,
            [{"type": "text", "text": text}],
            {"bot_prefix": "[META]"} if mode == "parts-meta" else {},
        )
    expected = "[META]  " + text if mode == "parts-meta" else text
    if key == "mqtt":
        assert broker.publishes == [("out/device-001", expected, 2)]
    else:
        assert mattermost.posts[0]["message"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_disconnected_send_has_failed_receipt_and_zero_effect(
    runtime, broker, mattermost, key
):
    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    handle = await route(rt, "recipient")
    if key == "mqtt":
        broker.connect_code = 4
        broker.disconnect()
    else:
        mattermost.auth_reply = False
        mattermost._ws_conn.close()
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] != "connected"
    )
    result = await rt.process.call(
        "channel.send",
        {
            **identity(rt),
            "delivery_id": "disconnected-send",
            "to_handle": handle,
            "operation": "message.create",
            "content_parts": [
                {"type": "text", "text": "must not reach platform"}
            ],
        },
    )
    assert (
        result["state"] == "failed"
        and result["reason_code"] == "NOT_CONNECTED"
    )
    assert broker.publishes == mattermost.posts == []
