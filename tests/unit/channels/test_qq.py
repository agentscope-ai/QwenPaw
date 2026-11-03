# -*- coding: utf-8 -*-
"""QQ native gateway, routing, media and heartbeat with local wire peers."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import pytest
import pytest_asyncio
from websockets.sync.server import serve
from qwenpaw.channel_protocol.models import SendParams
from tests.channel_support.driver import bind, module


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class Gateway:
    def __init__(self):
        self.calls, self.frames, self.connections = [], [], []

    def rows(self, path):
        return [r for r in self.calls if r["path"] == path]

    def api_rows(self):
        return [
            r for r in self.calls if r["path"] not in {"/token", "/gateway"}
        ]

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                raw = self.rfile.read(
                    int(self.headers.get("Content-Length", 0)),
                )
                owner.calls.append(
                    {
                        "path": self.path,
                        "body": json.loads(raw) if raw else None,
                        "raw": raw,
                        "auth": self.headers.get("Authorization"),
                        "method": self.command,
                        "content_type": self.headers.get("Content-Type", ""),
                    },
                )
                value = (
                    {"access_token": "native-token", "expires_in": 7200}
                    if self.path == "/token"
                    else (
                        {"url": owner.ws_url}
                        if self.path == "/gateway"
                        else (
                            {"file_info": "native-file-info"}
                            if self.path.endswith("/files")
                            else {"id": "sent"}
                        )
                    )
                )
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET = handle_request

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever)
        self.http_thread.start()
        self.ws = serve(self.gateway, "127.0.0.1", 0, close_timeout=1)
        self.ws_thread = threading.Thread(target=self.ws.serve_forever)
        self.ws_thread.start()
        self.ws_url = f"ws://127.0.0.1:{self.ws.socket.getsockname()[1]}"
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        return self

    def gateway(self, connection):
        self.connections.append(connection)
        connection.send(
            json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}),
        )
        for raw in connection:
            value = json.loads(raw)
            self.frames.append(value)
            if value["op"] == 2:
                self.push(
                    {
                        "op": 0,
                        "s": 1,
                        "t": "READY",
                        "d": {"session_id": "native-session"},
                    },
                )
            elif value["op"] == 1:
                self.push({"op": 11})

    def push(self, payload):
        self.connections[-1].send(json.dumps(payload))

    def stop(self):
        for connection in self.connections:
            connection.close()
        self.ws.shutdown()
        self.http.shutdown()
        self.http.server_close()
        for thread in (self.ws_thread, self.http_thread):
            thread.join(3)
            assert not thread.is_alive()


@pytest_asyncio.fixture
async def native_driver(tmp_path, monkeypatch):
    server = Gateway().start()
    monkeypatch.setenv("QQ_API_BASE", server.base)
    monkeypatch.setenv("QQ_TOKEN_URL", server.base + "/token")
    driver = module("qq").QQDriver()
    peer, identity = bind("qq", driver, tmp_path)
    try:
        await driver.start(
            {
                "app_id": "local-app",
                "client_secret": "local-secret",
                "workspace_dir": str(tmp_path),
                "bot_prefix": "[Bot] ",
                "markdown_enabled": True,
            },
        )
        await eventually(lambda: driver._connected)
        yield driver, peer, identity.to_mapping(), server
    finally:
        await driver.stop()
        server.stop()


async def open_route(peer, identity, target="qq:c2c:user-A", **meta):
    result = await peer.methods["channel.response.open"](
        {**identity, "to_handle": target, "meta": meta},
        None,
    )
    return result["response_handle"]


async def send(
    peer,
    identity,
    handle,
    parts,
    *,
    delivery="delivery-A",
    source="direct",
    **fields,
):
    params = SendParams.from_mapping(
        {
            **identity,
            "to_handle": handle,
            "delivery_id": delivery,
            "operation": "message.create",
            "content_parts": parts,
            "content_source": source,
            **fields,
        },
    )
    return await peer.methods["channel.send"](params, None)


TEXT = [{"type": "text", "text": "  exact answer  "}]


@pytest.mark.parametrize(
    "target,path",
    [
        ("qq:c2c:user-A", "/v2/users/user-A/messages"),
        ("qq:group:group-A", "/v2/groups/group-A/messages"),
        ("qq:guild:channel-A", "/channels/channel-A/messages"),
        ("qq:dm:guild-A", "/dms/guild-A/messages"),
    ],
)
async def test_native_text_targets(native_driver, target, path):
    driver, peer, identity, server = native_driver
    handle = await open_route(
        peer,
        identity,
        target,
        message_id="original-msg",
    )
    result = await send(peer, identity, handle, TEXT)
    assert result["state"] == "acknowledged"
    row = server.api_rows()[0]
    assert row["path"] == path
    assert row["body"]["markdown"] == {"content": "exact answer"}
    assert row["body"]["msg_id"] == "original-msg"
    assert row["auth"] == "QQBot native-token"
    assert len(server.rows("/token")) == 1
    assert server.rows("/token")[0]["body"] == {
        "appId": "local-app",
        "clientSecret": "local-secret",
    }


async def test_image_upload_then_native_media_reply(native_driver):
    _, peer, identity, server = native_driver
    handle = await open_route(peer, identity)
    result = await send(
        peer,
        identity,
        handle,
        [{"type": "image", "image_url": "https://cdn.example/p.png"}],
        source="media",
    )
    assert result["state"] == "acknowledged"
    upload, message = server.api_rows()
    assert upload["path"] == "/v2/users/user-A/files"
    assert upload["body"] == {
        "file_type": 1,
        "srv_send_msg": False,
        "url": "https://cdn.example/p.png",
    }
    assert message["path"] == "/v2/users/user-A/messages"
    assert message["body"]["msg_type"] == 7
    assert message["body"]["media"] == {"file_info": "native-file-info"}


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
async def test_native_events_map_sender_and_conversation(
    native_driver,
    event,
    author,
    coordinates,
    session,
    conversation,
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
        },
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


async def test_heartbeat_and_stop_close_native_resources(
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
    await driver.stop()
    assert not thread.is_alive() and client.is_closed and sync_client.is_closed
    assert not socket.connected
    assert platform._ws_thread is None and driver._platform is None
    await driver.stop()
