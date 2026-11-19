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
from qwenpaw.agents.context.scroll.serialize import strip_headline
from qwenpaw.app.channels.isolated_proxy import (
    ChannelDeliveryError,
    IsolatedChannelProxy,
)
from qwenpaw.app.channels.process_supervisor import LaunchSpec
from qwenpaw.app.channels.unified_queue_manager import EnqueueResult
from qwenpaw.channel_protocol.models import ResponseFinishParams, SendParams
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
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
        self.drop_next = 0
        self.reject_next_stream = None
        # QQ answers ``40007`` when a ``replace`` slice does not start with the
        # content it already delivered, so a test can opt into that contract.
        self.reject_prefix_rewrites = False
        self.delivered = {}

    def rows(self, path):
        return [r for r in self.calls if r["path"] == path]

    def api_rows(self):
        return [
            r for r in self.calls if r["path"] not in {"/token", "/gateway"}
        ]

    def prefix_conflict(self, payload):
        if (
            not self.reject_prefix_rewrites
            or not isinstance(payload, dict)
            or payload.get("input_mode") != "replace"
        ):
            return False
        text = payload["content_raw"]
        key = (payload["msg_id"], payload["msg_seq"])
        if not text.startswith(self.delivered.get(key, "")):
            return True
        self.delivered[key] = text
        return False

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                raw = self.rfile.read(
                    int(self.headers.get("Content-Length", 0)),
                )
                payload = json.loads(raw) if raw else None
                owner.calls.append(
                    {
                        "path": self.path,
                        "body": payload,
                        "raw": raw,
                        "auth": self.headers.get("Authorization"),
                        "method": self.command,
                        "content_type": self.headers.get("Content-Type", ""),
                    },
                )
                if (
                    self.path.endswith("/stream_messages")
                    and owner.reject_next_stream is not None
                ):
                    status = owner.reject_next_stream
                    owner.reject_next_stream = None
                    self.respond(status, {"message": "slice rejected"})
                    return
                if owner.prefix_conflict(payload):
                    self.respond(
                        400,
                        {"code": 40007, "message": "prefix rewritten"},
                    )
                    return
                if owner.drop_next:
                    # Accept the request, then lose the response: the native
                    # side has already applied it while the worker cannot know.
                    owner.drop_next -= 1
                    self.close_connection = True
                    return
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
                self.respond(200, value)

            def respond(self, status, value):
                body = json.dumps(value).encode()
                self.send_response(status)
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
    monkeypatch,
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
    call = peer.call
    acks = []

    async def host_call(name, params):
        if name == f"event.batch":
            peer.batches.append(params)
            ack = await host._event_batch(params, None)
            acks.append(ack)
            return ack
        return await call(name, params)

    monkeypatch.setattr(peer, f"call", host_call)
    data = {
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
    }
    server.push({f"op": 0, f"s": 2, f"t": event, f"d": data})
    await eventually(lambda: bool(acks))
    actual = peer.batches[0][f"events"][0]
    ack = acks[0]
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
    await eventually(lambda: driver._platform._state.last_seq == 2)
    server.push(
        {
            f"op": 0,
            f"s": 3,
            f"t": f"GROUP_MESSAGE_CREATE",
            f"d": {
                **data,
                f"id": f"incoming-B",
                f"content": f"<@bot-A> next message",
                f"mentions": [{f"id": f"bot-A", f"is_you": True}],
            },
        },
    )
    await eventually(lambda: driver._platform._state.last_seq == 3)
    assert len(server.connections) == 1
    assert len(queued) == int(allowed) + 1
    assert queued[-1][f"content_parts"][0].text == f"next message"
    followup = peer.batches[-1][f"events"][0]
    result = await send(
        peer,
        identity,
        followup[f"response_handle"],
        TEXT,
    )
    assert result[f"state"] == f"acknowledged"
    reply = server.api_rows()[-1]
    assert reply[f"path"] == f"/v2/groups/group-A/messages"
    assert reply[f"body"][f"msg_id"] == f"incoming-B"


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


async def send_stream(
    peer,
    identity,
    handle,
    *,
    operation,
    sequence,
    accumulated_text,
    delivery="delivery-A",
    target_delivery_id=None,
    stream_type="message",
):
    fields = {
        **identity,
        "to_handle": handle,
        "delivery_id": delivery,
        "operation": operation,
        "stream_type": stream_type,
        "sequence": sequence,
        "accumulated_text": accumulated_text,
    }
    if target_delivery_id is not None:
        fields["target_delivery_id"] = target_delivery_id
    params = SendParams.from_mapping(fields)
    return await peer.methods["channel.send"](params, None)


async def test_stream_slices_extend_the_delivered_prefix(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    server.reject_prefix_rewrites = True
    handle = await open_route(
        peer,
        identity,
        "qq:c2c:user-A",
        message_id="original-msg",
    )
    start = await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    assert start["state"] == "acknowledged"
    # The host opens every stream with a placeholder slice. QQ rejects a later
    # ``replace`` slice that does not start with what it already delivered, so
    # the placeholder must never reach the wire: the stream opens with real
    # text instead.
    assert server.api_rows() == []
    first = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="first",
    )
    assert first["state"] == "acknowledged"
    second = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.delta",
        sequence=2,
        target_delivery_id="delivery-A",
        accumulated_text="first more",
    )
    assert second["state"] == "acknowledged"
    end = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-D",
        operation="stream.end",
        sequence=3,
        target_delivery_id="delivery-A",
        accumulated_text="first more now",
    )
    assert end["state"] == "acknowledged"

    rows = server.api_rows()
    assert [row["path"] for row in rows] == [
        "/v2/users/user-A/stream_messages",
    ] * 3
    assert [row["auth"] for row in rows] == ["QQBot native-token"] * 3
    first_row, middle, last = (row["body"] for row in rows)
    assert first_row == {
        "input_mode": "replace",
        "input_state": 1,
        "index": 0,
        "content_type": "markdown",
        "content_raw": "first",
        "msg_id": "original-msg",
        "msg_seq": 1,
    }
    assert middle == {
        "input_mode": "replace",
        "input_state": 1,
        "index": 1,
        "content_type": "markdown",
        "content_raw": "first more",
        "msg_id": "original-msg",
        "msg_seq": 1,
        "stream_msg_id": "sent",
    }
    assert last == {
        "input_mode": "replace",
        "input_state": 10,
        "index": 2,
        "content_type": "markdown",
        "content_raw": "first more now",
        "msg_id": "original-msg",
        "msg_seq": 1,
        "stream_msg_id": "sent",
    }


@pytest.mark.parametrize("first_operation", ["delta", "end"])
@pytest.mark.parametrize("status", [400, 500])
async def test_host_falls_back_only_when_qq_rejects_opening(
    native_driver,
    monkeypatch,
    first_operation,
    status,
):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    code_root = ROOT / "plugins" / "channel" / "qq"
    descriptor_path = code_root / "channel.json"
    descriptor = SharedChannelDescriptor.load(descriptor_path)
    proxy = IsolatedChannelProxy(
        None,
        descriptor=descriptor,
        launch_spec=LaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT,
            code_root=code_root,
            descriptor_path=descriptor_path,
            source_revision="test",
            descriptor=descriptor,
            requirements=(),
            qwenpaw_version="1.0.0",
            config={"streaming_enabled": True},
            **identity,
        ),
    )

    async def call(method, params):
        if method == "channel.send":
            params = SendParams.from_mapping(params)
        return await peer.methods[method](params, None)

    monkeypatch.setattr(proxy.channel_process, "call", call)
    monkeypatch.setattr(
        proxy.channel_process,
        "health_snapshot",
        lambda: {"state": "ready", "platform_state": "connected", **identity},
    )
    handle = await open_route(peer, identity, message_id="original-msg")
    meta = {"response_handle": handle}
    args = (None, handle, None, meta, "message")
    await proxy.on_streaming_start(*args)
    server.reject_next_stream = status

    async def deliver():
        if first_operation == "delta":
            await proxy.on_streaming_delta(*args, accumulated_text="first")
        await proxy.on_streaming_end(*args, accumulated_text="full answer")

    rows = server.api_rows
    if status == 500:
        with pytest.raises(ChannelDeliveryError) as rejected:
            await deliver()
        assert rejected.value.side_effect_possible
        assert len(rows()) == 1
        assert rows()[0]["path"].endswith("/stream_messages")
    else:
        await deliver()
        assert [row["path"].rsplit("/", 1)[-1] for row in rows()] == [
            "stream_messages",
            "messages",
        ]
        assert rows()[-1]["body"]["markdown"] == {"content": "full answer"}
        assert meta["_isolated_streams"] == {}


@pytest.mark.parametrize(
    ("first", "suffix"),
    [("answer  ", ""), ("  answer\n\n\n", "more")],
)
async def test_stream_end_preserves_prefix_after_scroll_cleanup(
    native_driver,
    first,
    suffix,
):
    _, peer, identity, server = native_driver
    server.reject_prefix_rewrites = True
    handle = await open_route(peer, identity, message_id="original-msg")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.delta",
        sequence=1,
        accumulated_text=first,
        delivery="delivery-B",
        target_delivery_id="delivery-A",
    )
    final = await send_stream(
        peer,
        identity,
        handle,
        operation="stream.end",
        sequence=2,
        accumulated_text=strip_headline(f"{first}{suffix}\n⟦ title ⟧"),
        delivery="delivery-C",
        target_delivery_id="delivery-A",
    )
    assert final["state"] == "acknowledged"
    rows = [row["body"] for row in server.api_rows()]
    assert [row["content_raw"] for row in rows] == [first, f"{first}{suffix}"]
    assert [row["input_state"] for row in rows] == [1, 10]


async def test_stream_policy_is_c2c_only(native_driver):
    driver, peer, identity, _ = native_driver
    anchored = await open_route(
        peer,
        identity,
        "qq:c2c:user-A",
        message_id="original-msg",
    )
    group = await open_route(
        peer,
        identity,
        "qq:group:group-A",
        message_id="original-msg",
    )
    assert driver.response_policy(anchored).streaming is False
    driver._config["streaming_enabled"] = True
    assert driver.response_policy(anchored).streaming is True
    assert driver.response_policy(group).streaming is False
    # A stream is a passive reply: without the inbound ``msg_id`` anchor QQ
    # would reject every slice, so such routes stay on the message path.
    unanchored = await open_route(peer, identity, "qq:c2c:user-B")
    assert driver.response_policy(unanchored).streaming is False


async def test_stream_start_rejects_non_c2c_route(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    platform = driver._platform
    route = {"message_type": "group", "group_openid": "group-A"}
    with pytest.raises(Exception) as excinfo:
        await platform.start_stream(route, "text")
    assert getattr(excinfo.value, "reason_code", "") == (
        "STREAM_ROUTE_UNSUPPORTED"
    )
    assert server.api_rows() == []


async def test_lost_slice_response_keeps_index_monotonic(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(
        peer,
        identity,
        "qq:c2c:user-A",
        message_id="original-msg",
    )
    assert (
        await send_stream(
            peer,
            identity,
            handle,
            operation="stream.start",
            sequence=0,
            accumulated_text="...",
        )
    )["state"] == "acknowledged"
    assert (
        await send_stream(
            peer,
            identity,
            handle,
            delivery="delivery-B",
            operation="stream.delta",
            sequence=1,
            target_delivery_id="delivery-A",
            accumulated_text="first",
        )
    )["state"] == "acknowledged"
    server.drop_next = 1
    lost = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.delta",
        sequence=2,
        target_delivery_id="delivery-A",
        accumulated_text="first more",
    )
    assert lost["state"] == "unknown"
    recovered = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-D",
        operation="stream.delta",
        sequence=3,
        target_delivery_id="delivery-A",
        accumulated_text="first more still",
    )
    assert recovered["state"] == "acknowledged"
    # QQ accepted index 1 even though its response was lost, so the next
    # slice continues at 2 instead of resending an index QQ already saw.
    assert [row["body"]["index"] for row in server.api_rows()] == [0, 1, 2]
    assert server.api_rows()[-1]["body"]["content_raw"] == "first more still"


async def test_stream_type_is_preserved_and_validated(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    start = await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
        stream_type="reasoning",
    )
    assert start["state"] == "acknowledged"
    reasoning = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="thinking more",
        stream_type="reasoning",
    )
    assert reasoning["state"] == "acknowledged"
    mismatch = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.delta",
        sequence=2,
        target_delivery_id="delivery-A",
        accumulated_text="answer",
    )
    assert mismatch["state"] == "failed"
    assert mismatch["reason_code"] == "STREAM_TYPE_MISMATCH"
    assert [row["body"]["content_raw"] for row in server.api_rows()] == [
        "thinking more",
    ]


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
async def test_cleanup_closes_unfinished_stream(native_driver, outcome):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(
        peer,
        identity,
        "qq:c2c:user-A",
        message_id="original-msg",
    )
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="first more",
    )
    closing_index = 1
    if outcome == "failed":
        server.reject_next_stream = 400
        rejected = await send_stream(
            peer,
            identity,
            handle,
            operation="stream.end",
            sequence=2,
            accumulated_text="first more final",
            delivery="delivery-C",
            target_delivery_id="delivery-A",
        )
        assert rejected["state"] == "failed"
        closing_index = 2
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": outcome},
    )
    await peer.methods["channel.response.finish"](finish, None)
    rows = server.api_rows()
    assert [row["body"]["index"] for row in rows] == list(
        range(closing_index + 1),
    )
    closing = rows[-1]["body"]
    assert closing == {
        "input_mode": "replace",
        "input_state": 10,
        "index": closing_index,
        "content_type": "markdown",
        "content_raw": "first more",
        "msg_id": "original-msg",
        "msg_seq": 1,
        "stream_msg_id": "sent",
    }
    snapshot = driver._routes.snapshot(handle)
    assert snapshot is None or all(
        dict(ref.attributes).get("final") == "true"
        for ref in snapshot.resource_refs
        if ref.kind == "qq.delivery"
    )


async def test_lost_end_slice_is_not_closed_twice(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="first",
    )
    server.drop_next = 1
    lost = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.end",
        sequence=2,
        target_delivery_id="delivery-A",
        accumulated_text="first final",
    )
    assert lost["state"] == "unknown"
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": "completed"},
    )
    await peer.methods["channel.response.finish"](finish, None)
    # The end slice may already be applied on QQ, so cleanup records unknown
    # evidence instead of appending a second closing slice.
    assert [row["body"]["input_state"] for row in server.api_rows()] == [
        1,
        10,
    ]


async def test_cleanup_skips_already_ended_stream(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="first",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.end",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="final answer",
    )
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": "completed"},
    )
    await peer.methods["channel.response.finish"](finish, None)
    assert [row["body"]["input_state"] for row in server.api_rows()] == [
        1,
        10,
    ]


async def test_empty_stream_finishes_without_native_message(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    ended = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.end",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="",
    )
    assert ended["state"] == "acknowledged"
    late_delta = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.delta",
        sequence=2,
        target_delivery_id="delivery-A",
        accumulated_text="late text",
    )
    assert late_delta["state"] == "failed"
    assert late_delta["reason_code"] == "STREAM_SEQUENCE_STALE"
    assert server.api_rows() == []


async def test_cleanup_closes_each_unfinished_stream(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
        stream_type="reasoning",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="thinking",
        stream_type="reasoning",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-C",
        operation="stream.start",
        sequence=0,
        accumulated_text="...",
    )
    await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-D",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-C",
        accumulated_text="answer",
    )
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": "cancelled"},
    )
    await peer.methods["channel.response.finish"](finish, None)
    rows = [row["body"] for row in server.api_rows()]
    # Each stream keeps its own message and closes with its own next index.
    assert [
        (row["msg_seq"], row["index"], row["input_state"]) for row in rows
    ] == [
        (1, 0, 1),
        (2, 0, 1),
        (1, 1, 10),
        (2, 1, 10),
    ]
    assert [row["content_raw"] for row in rows[2:]] == ["thinking", "answer"]


async def test_slice_without_recorded_stream_type_still_streams(native_driver):
    driver, peer, identity, server = native_driver
    driver._config["streaming_enabled"] = True
    handle = await open_route(peer, identity, "qq:c2c:user-A")
    await send_stream(
        peer,
        identity,
        handle,
        operation="stream.start",
        sequence=0,
        accumulated_text="first",
    )
    # Resources persisted before ``stream_type`` was recorded carry no kind,
    # so they must keep streaming instead of failing every later slice.
    ref = driver._delivery_resource(handle, "delivery-A")
    driver._routes.record_delivery(
        handle,
        [
            ResponseResourceRef.create(
                "qq.delivery",
                "delivery-A",
                {
                    key: value
                    for key, value in dict(ref.attributes).items()
                    if key != "stream_type"
                },
            ),
        ],
    )
    delta = await send_stream(
        peer,
        identity,
        handle,
        delivery="delivery-B",
        operation="stream.delta",
        sequence=1,
        target_delivery_id="delivery-A",
        accumulated_text="first more",
        stream_type="reasoning",
    )
    assert delta["state"] == "acknowledged"
    assert [row["body"]["index"] for row in server.api_rows()] == [0]
