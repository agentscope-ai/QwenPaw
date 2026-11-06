# -*- coding: utf-8 -*-
"""QQ native gateway, routing, media and heartbeat with local wire peers."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import pytest
import pytest_asyncio
from websockets.sync.server import serve
from qwenpaw.channel_protocol.models import ResponseFinishParams, SendParams
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from tests.channel_support.driver import bind, module


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


class Gateway:
    def __init__(self):
        self.calls, self.frames, self.connections = [], [], []
        self.drop_next = 0
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
        if not self.reject_prefix_rewrites or not isinstance(payload, dict):
            return False
        text = str(payload.get("content_raw") or "")
        key = str(
            payload.get("stream_msg_id") or payload.get("msg_id") or "",
        )
        previous = self.delivered.get(key)
        self.delivered[key] = text
        return previous is not None and not text.startswith(previous)

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
                if owner.drop_next:
                    # Accept the request, then lose the response: the native
                    # side has already applied it while the worker cannot know.
                    owner.drop_next -= 1
                    self.close_connection = True
                    return
                if owner.prefix_conflict(payload):
                    self.respond(
                        400,
                        {"code": 40007, "message": "prefix rewritten"},
                    )
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
    finish = ResponseFinishParams.from_mapping(
        {**identity, "response_handle": handle, "outcome": outcome},
    )
    await peer.methods["channel.response.finish"](finish, None)
    rows = server.api_rows()
    assert len(rows) == 2
    closing = rows[-1]["body"]
    assert closing == {
        "input_mode": "replace",
        "input_state": 10,
        "index": 1,
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


async def test_empty_stream_closes_with_placeholder_text(native_driver):
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
    # A response that produces no text still has to open and close its stream,
    # and QQ rejects an empty ``content_raw``.
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
    rows = [row["body"] for row in server.api_rows()]
    assert [row["content_raw"] for row in rows] == ["...", "..."]
    assert [row["input_state"] for row in rows] == [1, 10]


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
