# -*- coding: utf-8 -*-
"""Local Matrix API transport; actual nio/client/platform remain unmocked."""
import asyncio
import json
from nio import AsyncClient
from pathlib import Path
import pytest
from qwenpaw.channel_protocol.models import SendParams
from qwenpaw.utils.media_paths import file_url_to_path
from tests.channel_support.driver import bind, module

from aiohttp import web
import pytest_asyncio

MatrixPlatform = module("matrix", "platform").MatrixPlatform

BOT = "@bot:example.com"
ROOM = "!test_room:example.com"
SENDER = "@user:example.com"


def text_event(body, event_id, sender=SENDER):
    return {
        "type": "m.room.message",
        "sender": sender,
        "event_id": event_id,
        "origin_server_ts": 1,
        "content": {"msgtype": "m.text", "body": body},
    }


def sync_payload(batch, events=()):
    room = {
        "timeline": {
            "events": list(events),
            "limited": False,
            "prev_batch": "previous",
        },
        "state": {"events": []},
        "ephemeral": {"events": []},
        "account_data": {"events": []},
        "summary": {},
        "unread_notifications": {},
    }
    return {
        "next_batch": batch,
        "rooms": {"join": {ROOM: room}, "leave": {}, "invite": {}},
        "presence": {"events": []},
        "account_data": {"events": []},
        "to_device": {"events": []},
        "device_lists": {"changed": [], "left": []},
        "device_one_time_keys_count": {},
    }


class LocalMatrixAPI:
    def __init__(self):
        self.requests = []
        self.sync = asyncio.Queue()
        self.user = BOT
        self.device = "SERVER-DEVICE"
        self.closed = asyncio.Event()
        self.download = b"native-media-bytes"

    async def handle(self, request):
        raw = await request.read()
        try:
            import json

            body = json.loads(raw) if raw else {}
        except ValueError:
            body = raw
        row = {
            "method": request.method,
            "path": request.path,
            "query": dict(request.query),
            "body": body,
            "headers": dict(request.headers),
        }
        self.requests.append(row)
        path = request.path
        if path.endswith("/whoami"):
            value, status = (
                {
                    "user_id": self.user,
                    "device_id": self.device,
                    "is_guest": False,
                },
                200,
            )
        elif path.endswith("/login"):
            value, status = (
                {
                    "user_id": self.user,
                    "device_id": self.device,
                    "access_token": "password-result-token",
                },
                200,
            )
        elif path.endswith("/sync"):
            item = asyncio.create_task(self.sync.get())
            closed = asyncio.create_task(self.closed.wait())
            try:
                done, _ = await asyncio.wait(
                    (item, closed),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if item not in done:
                    return web.json_response({}, status=503)
                value, status = item.result()
            finally:
                item.cancel()
                closed.cancel()
                await asyncio.gather(item, closed, return_exceptions=True)
        elif "/joined_members" in path:
            value, status = {
                "joined": {
                    BOT: {"display_name": "Bot"},
                    SENDER: {"display_name": "User"},
                },
            }, 200
        elif "/send/" in path:
            value, status = ({"event_id": "$sent-" + str(len(self.sent))}, 200)
        elif "/download/" in path:
            return web.Response(
                body=self.download,
                content_type="application/octet-stream",
            )
        else:
            value, status = {}, 200
        return web.json_response(value, status=status)

    @property
    def sent(self):
        return [r for r in self.requests if "/send/" in r["path"]]

    def calls(self, suffix):
        return [r for r in self.requests if r["path"].endswith(suffix)]


@pytest_asyncio.fixture
async def hs():
    server = LocalMatrixAPI()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", server.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server.url = "http://127.0.0.1:" + str(
        site._server.sockets[0].getsockname()[1],
    )
    try:
        yield server
    finally:
        server.closed.set()
        await runner.cleanup()


@pytest_asyncio.fixture
async def platform_factory(tmp_path, hs):
    made = []

    def make(**extra):
        events, states = [], []

        async def admitted(payload):
            events.append(payload)
            return True

        async def state(value):
            states.append(value)

        config = {
            "enabled": True,
            "homeserver": hs.url,
            "user_id": BOT,
            "access_token": "explicit-token",
            "workspace_dir": str(tmp_path / "A"),
            # Trusted fixture path; host projection is tested separately.
            "legacy_state_dir": str(tmp_path / "legacy"),
            **extra,
        }
        platform = MatrixPlatform(config, admitted, state)
        platform.observed_events, platform.observed_states = events, states
        made.append(platform)
        return platform

    try:
        yield make
    finally:
        for platform in reversed(made):
            await platform.stop()


async def until(predicate):
    # Bound local transport waits without arbitrary sleeps.
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_password_precedes_token_and_server_identity_is_persisted(
    hs,
    platform_factory,
):
    platform = platform_factory(
        password="explicit-password",
        device_name="  named-device  ",
    )
    await platform.start()
    assert isinstance(platform._client, AsyncClient)
    assert len(hs.calls("/login")) == 1 and not hs.calls("/whoami")
    request = hs.calls("/login")[0]["body"]
    assert request["password"] == "explicit-password"
    assert request["identifier"]["user"] == BOT
    assert request["device_id"] == "named-device"
    assert request["initial_device_display_name"] == "  named-device  "
    assert platform._client.access_token == "password-result-token"
    assert platform.device_id == "SERVER-DEVICE"
    assert platform.observed_states == ["connected"]
    assert json.loads(
        (platform._state.directory / "auth.json").read_text(),
    ) == {
        "access_token": "password-result-token",
        "user_id": BOT,
        "device_id": "SERVER-DEVICE",
    }


@pytest.mark.asyncio
async def test_token_whoami_and_catchup_suppress_only_old_events_then_resume(
    hs,
    platform_factory,
):
    hs.sync.put_nowait(
        (sync_payload("batch-old", [text_event("old", "$old")]), 200),
    )
    platform = platform_factory()
    await platform.start()
    await until(lambda: len(hs.calls("/sync")) == 2)
    assert len(hs.calls("/whoami")) == 1 and not hs.calls("/login")
    assert platform.observed_events == []
    assert platform._client.event_callbacks
    assert hs.calls("/sync")[0]["query"]["full_state"] == "true"
    assert "since" not in hs.calls("/sync")[0]["query"]
    assert hs.calls("/sync")[1]["query"]["since"] == "batch-old"
    hs.sync.put_nowait(
        (sync_payload("batch-new", [text_event("Hello", "$new")]), 200),
    )
    await until(lambda: len(platform.observed_events) == 1)
    event = platform.observed_events[0]
    assert event["sender_id"] == "@user:example.com"
    assert event["meta"]["event_id"] == "$new"
    assert event["content_parts"][0].text == "Hello"
    receipt = hs.calls("/read_markers")[0]
    assert receipt["body"] == {"m.fully_read": "$new", "m.read": "$new"}
    await until(lambda: platform._state.load_sync() == "batch-new")
    client, http, sync_task = (
        platform._client,
        platform._http_client,
        platform._sync_task,
    )
    await platform.stop()
    assert (
        sync_task.done() and client.client_session is None and http.is_closed
    )
    assert platform._client is None and not platform._state._begun
    assert platform.observed_states[-1] == "disconnected"


@pytest.mark.asyncio
async def test_saved_sync_token_resumes_and_stop_closes_typing(
    hs,
    platform_factory,
):
    first = platform_factory()
    await first.start()
    first._state.save_sync("saved-batch")
    await first.stop()
    hs.sync.put_nowait(
        (
            sync_payload("offline-batch", [text_event("offline", "$offline")]),
            200,
        ),
    )
    second = platform_factory()
    before = len(hs.calls("/sync"))
    await second.start()
    await until(lambda: len(second.observed_events) == 1)
    assert second.observed_events[0]["content_parts"][0].text == "offline"
    assert hs.calls("/sync")[before]["query"]["since"] == "saved-batch"
    assert hs.calls("/sync")[before]["query"]["full_state"] == "true"
    await second.start_typing("reply-A", {"room_id": ROOM})
    await second.start_typing("reply-B", {"room_id": ROOM})
    typing = [r for r in hs.requests if "/typing/" in r["path"]]
    assert [r["body"] for r in typing] == [{"typing": True, "timeout": 30000}]
    task = second._typing_tasks[ROOM]
    await second.stop_typing("reply-A")
    assert not task.done() and second._typing_owners == {"reply-B": ROOM}
    assert len([r for r in hs.requests if "/typing/" in r["path"]]) == 1
    await second.stop()
    assert (
        task.done() and not second._typing_owners and not second._typing_tasks
    )
    assert [
        r["body"]["typing"] for r in hs.requests if "/typing/" in r["path"]
    ] == [True, False]


async def ready(server, platform):
    server.sync.put_nowait((sync_payload("catchup"), 200))
    await platform.start()
    await until(lambda: len(server.calls("/sync")) == 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "filename"),
    [("image", "image.png"), ("file", "document.pdf")],
)
async def test_native_media_event_is_downloaded_and_admitted_once(
    hs,
    platform_factory,
    kind,
    filename,
):
    platform = platform_factory(vision_enabled=True)
    await ready(hs, platform)
    event = text_event(filename, "$abc123")
    event["content"] = {
        "msgtype": "m." + kind,
        "body": filename,
        "url": "mxc://example.org/media",
        "info": {
            "mimetype": "application/octet-stream",
            "size": len(hs.download),
        },
    }
    hs.sync.put_nowait((sync_payload("media", [event]), 200))
    await until(lambda: len(platform.observed_events) == 1)
    payload = platform.observed_events[0]
    parts = payload["content_parts"]
    assert any(getattr(p, "type", None) == kind for p in parts)
    assert len(parts) == 1 and payload["sender_id"] == "@user:example.com"
    part = parts[0]
    uri = getattr(part, "data" if kind == "audio" else kind + "_url")
    path = Path(file_url_to_path(uri))
    assert uri.startswith("file://") and path.is_relative_to(
        Path(platform.config["workspace_dir"]),
    )
    assert path.read_bytes() == hs.download
    assert len([r for r in hs.requests if "/download/" in r["path"]]) == 1
    assert hs.calls("/read_markers")[0]["body"] == {
        "m.fully_read": "$abc123",
        "m.read": "$abc123",
    }


@pytest.mark.asyncio
async def test_driver_native_text_roundtrip_reaches_original_room(
    hs,
    tmp_path,
):
    driver = module("matrix").MatrixDriver()
    peer, identity = bind("matrix", driver, tmp_path)
    hs.sync.put_nowait((sync_payload("catchup"), 200))
    try:
        await driver.start(
            {
                "enabled": True,
                "homeserver": hs.url,
                "user_id": BOT,
                "access_token": "explicit-token",
                "workspace_dir": str(tmp_path / "driver"),
                "legacy_state_dir": str(tmp_path / "legacy"),
            },
        )
        await until(lambda: len(hs.calls("/sync")) == 2)
        hs.sync.put_nowait(
            (
                sync_payload(
                    "question",
                    [text_event("question", "$question")],
                ),
                200,
            ),
        )
        await until(lambda: len(peer.batches) == 1)
        event = peer.batches[0]["events"][0]
        assert event["event_id"] == "$question"
        assert event["sender_id"] == event["acl_sender_id"] == SENDER
        assert event["conversation"] == {
            "id": ROOM,
            "type": "dm",
            "thread_id": None,
        }
        assert event["metadata"]["session_id"] == "matrix:" + ROOM
        assert event["content_parts"] == [{"type": "text", "text": "question"}]
        assert event["response_handle"].startswith("matrix:reply:")
        result = await peer.methods["channel.send"](
            SendParams.from_mapping(
                {
                    **identity.to_mapping(),
                    "to_handle": event["response_handle"],
                    "delivery_id": "answer",
                    "operation": "message.create",
                    "content_parts": [{"type": "text", "text": "answer"}],
                },
            ),
            None,
        )
        assert result["state"] == "acknowledged"
        assert len(hs.sent) == 1
        assert "/rooms/" + ROOM + "/send/m.room.message/" in hs.sent[0]["path"]
        assert hs.sent[0]["body"]["body"] == "answer"
        assert hs.sent[0]["body"]["msgtype"] == "m.text"
        platform = driver._platform
        sync_task = platform._sync_task
    finally:
        await driver.stop()
    assert driver._platform is None and not driver._connected
    assert sync_task.done() and platform._client is None


@pytest.mark.asyncio
async def test_unknown_typing_stop_retires_only_its_local_owner(
    hs,
    platform_factory,
    tmp_path,
    monkeypatch,
):
    import hashlib
    from tests.channel_support.protocol import finish, open_route

    platform = platform_factory()
    await ready(hs, platform)
    driver = module("matrix").MatrixDriver()
    peer, identity = bind("matrix", driver, tmp_path)
    driver._platform, driver._connected = platform, True
    native = platform._client.room_typing
    stops = []

    async def typing(room_id, **kwargs):
        if not kwargs["typing_state"]:
            stops.append(room_id)
            if len(stops) == 1:
                raise OSError("native stop outcome unknown")
        return await native(room_id, **kwargs)

    monkeypatch.setattr(platform._client, "room_typing", typing)

    async def prepare(room):
        handle = await open_route(peer, identity, room)
        await peer.methods["channel.response.prepare"](
            {
                **identity.to_mapping(),
                "response_handle": handle,
                "delivery_id": hashlib.sha256(
                    (handle + ":prepare").encode(),
                ).hexdigest(),
            },
            None,
        )
        return handle

    other_room = "!other:example.com"
    other = await prepare(other_room)
    other_task = platform._typing_tasks[other_room]
    handle = await prepare(ROOM)
    old_task = platform._typing_tasks[ROOM]
    await finish(peer, identity, handle)
    assert peer.receipts.list() and not driver._routes.snapshot(handle)
    assert handle not in platform._typing_owners
    assert old_task.done() and ROOM not in platform._typing_tasks
    assert platform._typing_owners == {other: other_room}
    assert platform._typing_tasks[other_room] is other_task
    assert not other_task.done()
    await finish(peer, identity, handle)
    assert stops == [ROOM]
    subsequent = await prepare(ROOM)
    subsequent_task = platform._typing_tasks[ROOM]
    # Re-retiring the archived owner must preserve a new owner in its room.
    await finish(peer, identity, handle)
    assert platform._typing_owners == {other: other_room, subsequent: ROOM}
    assert platform._typing_tasks[ROOM] is subsequent_task
    assert not subsequent_task.done() and stops == [ROOM]
    await finish(peer, identity, subsequent)
    assert stops == [ROOM, ROOM]
    assert subsequent_task.done() and ROOM not in platform._typing_tasks
    assert platform._typing_owners == {other: other_room}
    await finish(peer, identity, other)
    assert other_task.done() and not platform._typing_owners
    first, second = await prepare(ROOM), await prepare(ROOM)
    shared_task = platform._typing_tasks[ROOM]
    before = stops.copy()
    await driver._release_local_response(first)
    assert platform._typing_owners == {second: ROOM}
    assert platform._typing_tasks[ROOM] is shared_task
    assert not shared_task.done() and stops == before
    await finish(peer, identity, second)
    assert shared_task.done() and not platform._typing_owners
    assert not platform._typing_tasks and stops == [*before, ROOM]
