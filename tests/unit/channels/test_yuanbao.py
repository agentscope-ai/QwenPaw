# -*- coding: utf-8 -*-
"""Yuanbao signs HTTP credentials and uses native protobuf WebSocket frames."""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path

from aiohttp import web, WSMsgType
from google.protobuf import json_format
import pytest
from qwenpaw.utils.media_paths import file_url_to_path
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import eventually, finish, send


def decode(codec, name, data):
    message = codec._get_message_class(name)()
    message.ParseFromString(data)
    return json_format.MessageToDict(message, preserving_proto_field_name=True)


@pytest.fixture
async def yuanbao(tmp_path):
    codec = module("yuanbao", "codec")
    frames, sends, signatures, connections = [], [], [], []

    async def token(request):
        body = await request.json()
        expected = hmac.new(
            b"local-secret",
            (
                body["nonce"]
                + body["timestamp"]
                + "local-app"
                + "local-secret"
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        signatures.append(body)
        assert body["app_key"] == "local-app" and hmac.compare_digest(
            body["signature"],
            expected,
        )
        return web.json_response(
            {
                "code": 0,
                "data": {
                    "bot_id": "native-bot",
                    "token": "native-token",
                    "source": "bot",
                    "duration": 7200,
                    "product": "yuanbao",
                },
            },
        )

    async def gateway(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        connections.append(ws)
        async for message in ws:
            assert message.type == WSMsgType.BINARY
            frame = codec.decode_conn_msg(message.data)
            frames.append(frame)
            head, data = frame["head"], frame["data"]
            name, body = None, {}
            if head["cmd"] == codec.CMD_AUTH_BIND:
                assert decode(codec, codec.AUTH_BIND_REQ, data)[
                    "authInfo"
                ] == {
                    "uid": "native-bot",
                    "source": "bot",
                    "token": "native-token",
                }
                name, body = codec.AUTH_BIND_RSP, {"code": 0, "message": "ok"}
            elif head["cmd"] == codec.CMD_PING:
                name, body = codec.PING_RSP, {"heartInterval": 7}
            elif head["cmd"] in (
                codec.BIZ_CMD_SEND_C2C,
                codec.BIZ_CMD_SEND_GROUP,
            ):
                name = (
                    codec.SEND_C2C_REQ
                    if head["cmd"] == codec.BIZ_CMD_SEND_C2C
                    else codec.SEND_GROUP_REQ
                )
                sends.append(decode(codec, name, data))
                name, body = codec.SEND_C2C_RSP, {"code": 0, "message": "ok"}
            if name:
                await ws.send_bytes(
                    codec.encode_conn_msg(
                        {**head, "cmdType": codec.CMD_TYPE_RESPONSE},
                        codec.encode_pb(name, body),
                    ),
                )
        return ws

    async def image(request):
        return web.Response(body=b"native-image", content_type="image/png")

    app = web.Application()
    app.router.add_post("/api/v5/robotLogic/sign-token", token)
    app.router.add_get("/ws", gateway)
    app.router.add_get("/image.png", image)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    driver = module("yuanbao").YuanbaoDriver()
    peer, identity = bind("yuanbao", driver, tmp_path)
    try:
        await driver.start(
            dict(
                enabled=True,
                app_id="local-app",
                app_secret="local-secret",
                api_domain=base,
                ws_url=f"ws://127.0.0.1:{port}/ws",
                workspace_dir=str(tmp_path),
                media_dir=str(tmp_path / "media"),
            ),
        )
        await eventually(lambda: driver._connected)
        yield (
            driver,
            peer,
            identity,
            codec,
            frames,
            sends,
            signatures,
            connections,
            base,
        )
    finally:
        await driver.stop()
        for ws in connections:
            await ws.close()
        await runner.cleanup()


async def receive(value, group=None, media=False):
    _, peer, _, codec, _, _, _, connections, base = value
    body = [{"msg_type": "TIMTextElem", "msg_content": {"text": "hello"}}]
    if media:
        body.append(
            {
                "msg_type": "TIMImageElem",
                "msg_content": {
                    "image_info_array": [{"url": base + "/image.png"}],
                },
            },
        )
    payload = {
        "callback_command": (
            "Group.AfterSendMsg" if group else "C2C.AfterSendMsg"
        ),
        "from_account": "native-user-12345678",
        "sender_nickname": "灰",
        "msg_id": "message-A",
        "group_code": group or "",
        "msg_body": body,
    }
    head = {
        "cmdType": codec.CMD_TYPE_PUSH,
        "cmd": "native.push",
        "seqNo": 17,
        "msgId": "push-frame",
        "module": codec.MODULE_BIZ,
        "needAck": True,
    }
    await connections[0].send_bytes(
        codec.encode_conn_msg(head, json.dumps(payload).encode()),
    )
    await eventually(lambda: bool(peer.batches))
    return peer.batches[-1]["events"][0]


async def test_signed_token_and_binary_authenticate_before_connected(yuanbao):
    driver, _, _, codec, frames, _, signatures, _, _ = yuanbao
    assert len(signatures) == 1
    assert (
        datetime.fromisoformat(signatures[0]["timestamp"])
        .utcoffset()
        .total_seconds()
        == 28800
    )
    assert frames[0]["head"]["cmd"] == codec.CMD_AUTH_BIND
    assert driver._platform._bot_id == "native-bot" and driver._connected


@pytest.mark.parametrize("group", [None, "native-group"])
async def test_dm_group_identity_and_reply_target_retain_full_native_id(
    yuanbao,
    group,
):
    driver, peer, identity, _, _, sends, _, _, _ = yuanbao
    event = await receive(yuanbao, group)
    assert (
        event["acl_sender_id"] == "native-user-12345678"
        and event["sender_id"] == "灰#5678"
    )
    assert event["conversation"] == {
        "id": group or "native-user-12345678",
        "type": "group" if group else "dm",
        "thread_id": None,
    }
    assert event["metadata"]["session_id"] == (group or "12345678")
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    route = driver._route_attrs(event["response_handle"])
    assert route["sender_id"] == "native-user-12345678"
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    assert sends[0]["msgBody"] == [
        {"msgType": "TIMTextElem", "msgContent": {"text": "native answer"}},
    ]
    assert sends[0]["groupCode" if group else "toAccount"] == (
        group or "native-user-12345678"
    )


async def test_group_typing_sends_running_and_finish_native_heartbeats(
    yuanbao,
):
    driver, peer, identity, codec, frames, _, _, _, _ = yuanbao
    handle = (await receive(yuanbao, "native-group"))["response_handle"]
    result = await peer.methods["channel.response.prepare"](
        {
            **identity.to_mapping(),
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode(),
            ).hexdigest(),
        },
        None,
    )
    assert (
        result["state"] == "acknowledged"
        and handle in driver._platform._typing_tasks
    )
    await finish(peer, identity, handle)
    await eventually(
        lambda: len(
            [f for f in frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB],
        )
        == 2,
    )
    heartbeats = [
        decode(codec, codec.SEND_GROUP_HB_REQ, f["data"])
        for f in frames
        if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB
    ]
    assert [(f["groupCode"], f["heartbeat"]) for f in heartbeats] == [
        ("native-group", "HEARTBEAT_RUNNING"),
        ("native-group", "HEARTBEAT_FINISH"),
    ]
    assert not driver._platform._typing_tasks


async def test_native_image_download_keeps_bytes_in_workspace(yuanbao):
    driver, _, _, _, _, _, _, _, _ = yuanbao
    event = await receive(yuanbao, media=True)
    part = event["content_parts"][1]
    assert part["type"] == "image"
    path = Path(file_url_to_path(part["image_url"]))
    assert path.read_bytes() == b"native-image" and path.is_relative_to(
        driver._platform._media_dir,
    )


async def test_stop_closes_binary_socket_sessions_and_owned_tasks(yuanbao):
    driver, _, _, _, _, _, _, _, _ = yuanbao
    platform = driver._platform
    ws, session = platform._ws, platform._session
    tasks = [platform._receive_task, platform._heartbeat_task]
    await driver.stop()
    assert ws.closed and session.closed and all(task.done() for task in tasks)
    assert platform._ws is None and not platform._pending_requests
    assert driver._platform is None
