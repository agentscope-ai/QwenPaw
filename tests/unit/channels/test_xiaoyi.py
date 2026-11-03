# -*- coding: utf-8 -*-
"""XiaoYi socket authentication and routed A2A replies."""

import asyncio
import base64
import hashlib
import hmac
import json

from aiohttp import web, WSMsgType
import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import eventually, finish, send


def inbound(message="message-A", session="session-A"):
    return {
        "agentId": "local-agent",
        "method": "message/stream",
        "id": "request-A",
        "params": {
            "sessionId": session,
            "id": "task-A",
            "message": {
                "messageId": message,
                "parts": [{"kind": "text", "text": "hello"}],
            },
        },
    }


@pytest.fixture
async def xiaoyi(tmp_path, monkeypatch):
    connections, headers, frames = {}, {}, []

    async def gateway(request):
        name = request.match_info["name"]
        headers[name] = dict(request.headers)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        connections[name] = ws
        async for frame in ws:
            if frame.type == WSMsgType.TEXT:
                frames.append((name, json.loads(frame.data)))
        return ws

    app = web.Application()
    app.router.add_get("/ws/{name}", gateway)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    native = module("xiaoyi", "platform")
    monkeypatch.setattr(
        native,
        "DEFAULT_WS_URL",
        f"ws://127.0.0.1:{port}/ws/primary",
    )
    monkeypatch.setattr(
        native,
        "DEFAULT_WS_URL_BACKUP",
        f"ws://127.0.0.1:{port}/ws/backup",
    )
    driver = module("xiaoyi").XiaoYiDriver()
    peer, identity = bind("xiaoyi", driver, tmp_path)
    try:
        await driver.start(
            dict(
                enabled=True,
                ak="local-ak",
                sk="local-sk",
                agent_id="local-agent",
                workspace_dir=str(tmp_path),
            ),
        )
        await eventually(lambda: len(connections) == 2)
        yield driver, peer, identity, connections, headers, frames
    finally:
        await driver.stop()
        for ws in connections.values():
            await ws.close()
        await runner.cleanup()


def results(value):
    return [
        (server, json.loads(frame["msgDetail"])["result"])
        for server, frame in value[5]
        if frame.get("msgType") == "agent_response"
    ]


async def receive(value, server="primary", **kwargs):
    _, peer, _, connections, _, _ = value
    await connections[server].send_json(inbound(**kwargs))
    await eventually(lambda: bool(peer.batches))
    return peer.batches[-1]["events"][0]


async def test_both_connections_authenticate_with_hmac_and_native_init(xiaoyi):
    _, _, _, _, headers, frames = xiaoyi
    for name in ("primary", "backup"):
        fields = {key.lower(): val for key, val in headers[name].items()}
        expected = base64.b64encode(
            hmac.new(
                b"local-sk",
                fields["x-ts"].encode(),
                hashlib.sha256,
            ).digest(),
        ).decode()
        assert (
            fields["x-access-key"] == "local-ak"
            and fields["x-agent-id"] == "local-agent"
        )
        assert fields["x-sign"] == expected and fields["x-ts"].isdigit()
    await eventually(
        lambda: len(
            [f for _, f in frames if f.get("msgType") == "clawd_bot_init"],
        )
        == 2,
    )
    assert all(
        json.loads(f["msgDetail"])["agentId"] == "local-agent"
        for _, f in frames
        if f.get("msgType") == "clawd_bot_init"
    )


@pytest.mark.parametrize("server", ["primary", "backup"])
async def test_native_text_keeps_session_task_and_same_server_reply(
    xiaoyi,
    server,
):
    driver, peer, identity, _, _, _ = xiaoyi
    event = await receive(xiaoyi, server)
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert event["metadata"]["session_id"] == "xiaoyi:session-A"
    assert event["metadata"]["task_id"] == "task-A"
    assert (
        driver._route_attrs(event["response_handle"])["server_name"] == server
    )
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    await eventually(lambda: len(results(xiaoyi)) == 1)
    actual_server, result = results(xiaoyi)[0]
    assert actual_server == server and result["taskId"] == "task-A"
    assert result["artifact"]["parts"] == [
        {"kind": "text", "text": "native answer"},
    ]


async def test_completed_response_sends_status_then_final_empty_artifact_once(
    xiaoyi,
):
    _, peer, identity, _, _, _ = xiaoyi
    event = await receive(xiaoyi)
    await send(peer, identity, event["response_handle"])
    await finish(peer, identity, event["response_handle"])
    await eventually(lambda: len(results(xiaoyi)) == 3)
    rows = [result for _, result in results(xiaoyi)]
    assert [result["kind"] for result in rows] == [
        "artifact-update",
        "status-update",
        "artifact-update",
    ]
    assert (
        rows[1]["status"]["state"] == "completed" and rows[1]["final"] is False
    )
    assert rows[2]["final"] is True and rows[2]["artifact"]["parts"] == [
        {"kind": "text", "text": ""},
    ]
    await finish(peer, identity, event["response_handle"])
    assert len(results(xiaoyi)) == 3


async def test_one_primary_disconnect_falls_back_to_backup_for_reply(xiaoyi):
    driver, peer, identity, connections, _, _ = xiaoyi
    event = await receive(xiaoyi)
    await connections["primary"].close()
    await eventually(lambda: not driver._platform._conn_primary.connected)
    assert driver._platform._conn_backup.connected
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    await eventually(lambda: len(results(xiaoyi)) == 1)
    assert results(xiaoyi)[0][0] == "backup"


async def test_stop_releases_both_socket_readers_and_sessions(xiaoyi):
    driver, _, _, _, _, _ = xiaoyi
    platform = driver._platform
    connections = [platform._conn_primary, platform._conn_backup]
    tasks = [
        task
        for conn in connections
        for task in (conn._receive_task, conn._heartbeat_task)
    ]
    sessions = [conn._session for conn in connections]
    await driver.stop()
    assert all(task.done() for task in tasks)
    assert all(session.closed for session in sessions)
    assert all(
        conn._ws is None and conn._session is None for conn in connections
    )
    assert driver._platform is None


def test_local_media_authorizes_workspace_and_rejects_outside(tmp_path):
    from types import SimpleNamespace

    native = module("xiaoyi", "platform")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = workspace / "media"
    media.mkdir()
    allowed = workspace / "附件 with space.txt"
    allowed.write_text("local attachment")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    platform = SimpleNamespace(_media_dir=media, _workspace_dir=workspace)
    for uri in (str(allowed), allowed.as_uri()):
        part = {"type": "file", "file_url": uri, "filename": allowed.name}
        assert native.XiaoYiPlatform._media_part(platform, part)["file"] == {
            "name": allowed.name,
            "mimeType": "application/octet-stream",
            "uri": uri,
        }
    for uri in (str(outside), outside.as_uri()):
        with pytest.raises(
            native.XiaoYiDeliveryError,
            match="MEDIA_PATH_UNAUTHORIZED",
        ):
            native.XiaoYiPlatform._media_part(
                platform,
                {"type": "file", "file_url": uri},
            )
    for part in (
        {"type": "image", "image_url": "https://example.test/image.png"},
        {"type": "audio", "data": "YWJjZA=="},
        {"type": "audio", "data": "data:audio/mpeg;base64,YWJjZA=="},
    ):
        assert native.XiaoYiPlatform._media_part(platform, part)["file"][
            "uri"
        ] == next(value for key, value in part.items() if key != "type")
