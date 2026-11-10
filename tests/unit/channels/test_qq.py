# -*- coding: utf-8 -*-
"""QQ native gateway, routing, media and heartbeat with local wire peers."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import pytest
import pytest_asyncio
from websockets.sync.server import serve
from qwenpaw.app.channels.unified_queue_manager import EnqueueResult
from qwenpaw.channel_protocol.models import SendParams
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from tests.channel_support.driver import ROOT, bind, module


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
            "GROUP_MESSAGE_CREATE",
            {"member_openid": "actor-A"},
            {"group_openid": "group-A"},
            "qq:group:group-A",
            "group-A",
        ),
        (
            "GROUP_MESSAGE_CREATE",
            {"id": "actor-A"},
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
            if event
            in {
                "GROUP_AT_MESSAGE_CREATE",
                "GROUP_MESSAGE_CREATE",
                "AT_MESSAGE_CREATE",
            }
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


@pytest.mark.parametrize(f"require_mention", [False, True])
@pytest.mark.parametrize(
    f"event,mentions,mentioned",
    [
        (f"GROUP_AT_MESSAGE_CREATE", None, True),
        (f"AT_MESSAGE_CREATE", None, True),
        (f"C2C_MESSAGE_CREATE", None, False),
        (f"GROUP_MESSAGE_CREATE", None, False),
        (f"GROUP_MESSAGE_CREATE", [], False),
        (
            f"GROUP_MESSAGE_CREATE",
            [{f"id": f"other-user", f"is_you": False}],
            False,
        ),
        (
            f"GROUP_MESSAGE_CREATE",
            [{f"id": f"bot-A", f"is_you": True}],
            True,
        ),
        (
            f"GROUP_MESSAGE_CREATE",
            [
                {f"id": f"other-user", f"is_you": False},
                {f"id": f"bot-A", f"is_you": True},
            ],
            True,
        ),
    ],
)
async def test_native_events_follow_host_mention_policy(
    native_driver,
    require_mention,
    event,
    mentions,
    mentioned,
):
    driver, peer, identity, server = native_driver
    content = (
        f"<@bot-A> hello"
        if mentioned and event == f"GROUP_MESSAGE_CREATE"
        else f"hello"
    )
    server.push(
        {
            f"op": 0,
            f"s": 2,
            f"t": event,
            f"d": {
                f"id": f"incoming-A",
                f"content": content,
                f"author": {
                    f"member_openid": f"actor-A",
                    f"user_openid": f"actor-A",
                    f"id": f"actor-A",
                },
                f"group_openid": f"group-A",
                f"channel_id": f"channel-A",
                f"guild_id": f"guild-A",
                **({} if mentions is None else {f"mentions": mentions}),
            },
        },
    )
    await eventually(lambda: driver._platform._state.last_seq == 2)
    batch = peer.batches[0]
    actual = batch[f"events"][0]
    source = ROOT / f"plugins" / f"channel" / f"qq"
    description = describe_channel(
        source,
        PluginManifest.from_dict(
            json.loads(
                (source / f"plugin.json").read_text(encoding=f"utf-8"),
            ),
        ),
    )
    prepared = description.prepare_proxy_config(
        {f"enabled": True, f"require_mention": require_mention},
    )
    host = description.create_proxy(
        None,
        prepared.config,
        python_executable=sys.executable,
        support_root=ROOT / f"src",
        instance_id=identity[f"instance_id"],
        generation=identity[f"generation"],
        qwenpaw_version=f"1.0.0",
        prepared_config=prepared,
    )
    queued = []

    async def enqueue(payload):
        queued.append(payload)
        return EnqueueResult(accepted=True)

    host.set_enqueue_async(enqueue)
    ack = await host._event_batch(batch, None)
    allowed = (
        not require_mention
        or actual[f"conversation"][f"type"] == f"dm"
        or mentioned
    )
    assert ack[f"accepted_event_ids"] == (
        [actual[f"event_id"]] if allowed else []
    )
    assert ack[f"rejected_events"] == (
        []
        if allowed
        else [
            {
                f"event_id": actual[f"event_id"],
                f"reason_code": f"MENTION_REQUIRED",
                f"retryable": False,
            },
        ]
    )
    assert len(queued) == int(allowed)
    assert actual[f"metadata"][f"bot_mentioned"] is mentioned
    assert actual[f"content_parts"] == [
        {f"type": f"text", f"text": f"hello"},
    ]
    assert actual[f"metadata"][f"incoming_raw"][f"content"] == content


@pytest.mark.parametrize(f"openid_key", [f"member_openid", f"id"])
@pytest.mark.parametrize(f"is_you", [False, True])
@pytest.mark.parametrize(
    f"content,expected",
    [
        (f" <@bot-A> hello ", f"hello"),
        (f"hello<@bot-A> world", f"hello world"),
        (f"<@bot-A>hello<@bot-A>", f"hello"),
        (
            f"<@bot-A><@other-user> hello <@all>",
            f"<@other-user> hello <@all>",
        ),
        (f"<@bot-A>", None),
        (f"<@bot-A>\nhello\n  world", f"hello\n  world"),
    ],
)
async def test_full_group_messages_strip_only_self_mentions(
    native_driver,
    openid_key,
    is_you,
    content,
    expected,
):
    driver, peer, _, server = native_driver
    data = {
        f"id": f"incoming-A",
        f"content": content,
        f"author": {f"member_openid": f"actor-A"},
        f"group_openid": f"group-A",
        f"mentions": [
            {openid_key: f"bot-A", f"is_you": is_you},
            {f"id": f"other-user", f"is_you": False},
        ],
    }
    server.push(
        {f"op": 0, f"s": 2, f"t": f"GROUP_MESSAGE_CREATE", f"d": data},
    )
    await eventually(lambda: driver._platform._state.last_seq == 2)
    expected_text = expected if is_you else content.strip()
    if expected_text is None:
        assert not peer.batches
        return
    actual = peer.batches[0][f"events"][0]
    assert actual[f"content_parts"] == [
        {f"type": f"text", f"text": expected_text},
    ]
    assert actual[f"metadata"][f"bot_mentioned"] is is_you
    assert actual[f"metadata"][f"incoming_raw"] == data


async def test_self_mention_only_keeps_attachments(native_driver):
    driver, peer, _, server = native_driver
    attachments = [
        {f"content_type": f"voice", f"asr_refer_text": f"voice message"},
    ]
    server.push(
        {
            f"op": 0,
            f"s": 2,
            f"t": f"GROUP_MESSAGE_CREATE",
            f"d": {
                f"id": f"incoming-A",
                f"content": f"<@bot-A>",
                f"author": {f"member_openid": f"actor-A"},
                f"group_openid": f"group-A",
                f"mentions": [{f"id": f"bot-A", f"is_you": True}],
                f"attachments": attachments,
            },
        },
    )
    await eventually(lambda: driver._platform._state.last_seq == 2)
    actual = peer.batches[0][f"events"][0]
    assert actual[f"content_parts"] == [
        {f"type": f"text", f"text": f"voice message"},
    ]
    assert actual[f"metadata"][f"bot_mentioned"] is True
    assert actual[f"metadata"][f"incoming_raw"][f"attachments"] == attachments


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
