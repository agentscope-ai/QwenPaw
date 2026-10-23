"""Local Matrix API transport; actual nio/client/platform remain unmocked."""
import asyncio
from collections import deque
from pathlib import Path
import sys

from aiohttp import web
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins/channel/matrix"))
from qwenpaw_channel_matrix.platform import MatrixPlatform

BOT = "@bot:example.com"
ROOM = "!test_room:example.com"
SENDER = "@user:example.com"


def text_event(body, event_id, sender=SENDER):
    return {"type": "m.room.message", "sender": sender, "event_id": event_id,
            "origin_server_ts": 1, "content": {"msgtype": "m.text", "body": body}}


def sync_payload(batch, events=(), invite=False):
    room = {"timeline": {"events": list(events), "limited": False,
                         "prev_batch": "previous"},
            "state": {"events": []}, "ephemeral": {"events": []},
            "account_data": {"events": []}, "summary": {},
            "unread_notifications": {}}
    return {"next_batch": batch,
            "rooms": {"join": {ROOM: room}, "leave": {}, "invite":
                      {"!invite:example.com": {"invite_state": {"events": []}}} if invite else {}},
            "presence": {"events": []}, "account_data": {"events": []},
            "to_device": {"events": []}, "device_lists": {"changed": [], "left": []},
            "device_one_time_keys_count": {}}


class LocalMatrixAPI:
    def __init__(self):
        self.requests = []
        self.sync = asyncio.Queue()
        self.whoami = deque()
        self.login = deque()
        self.send = deque()
        self.user = BOT
        self.device = "SERVER-DEVICE"
        self.closed = asyncio.Event()
        self.uploads = []
        self.download = b"native-media-bytes"
        self.group = False
        self.to_device = deque()

    async def handle(self, request):
        raw = await request.read()
        try:
            import json
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = raw
        row = {"method": request.method, "path": request.path,
               "query": dict(request.query), "body": body,
               "headers": dict(request.headers)}
        self.requests.append(row)
        path = request.path
        if path.endswith("/whoami"):
            value, status = self.whoami.popleft() if self.whoami else (
                {"user_id": self.user, "device_id": self.device, "is_guest": False}, 200)
        elif path.endswith("/login"):
            value, status = self.login.popleft() if self.login else (
                {"user_id": self.user, "device_id": self.device,
                 "access_token": "password-result-token"}, 200)
        elif path.endswith("/sync"):
            item = asyncio.create_task(self.sync.get())
            closed = asyncio.create_task(self.closed.wait())
            try:
                done, _ = await asyncio.wait((item, closed), return_when=asyncio.FIRST_COMPLETED)
                if item not in done:
                    return web.json_response({}, status=503)
                value, status = item.result()
            finally:
                item.cancel()
                closed.cancel()
                await asyncio.gather(item, closed, return_exceptions=True)
        elif "/joined_members" in path:
            value, status = {"joined": {BOT: {"display_name": "Bot"}, SENDER: {"display_name": "User"}}}, 200
            if self.group:
                value["joined"]["@other:example.com"] = {"display_name": "Other"}
        elif "/join/" in path:
            value, status = {"room_id": "!invite:example.com"}, 200
        elif "/send/" in path:
            value, status = self.send.popleft() if self.send else (
                {"event_id": "$sent-" + str(len(self.sent))}, 200)
        elif path.endswith("/upload"):
            self.uploads.append(row)
            value, status = {"content_uri": "mxc://example.org/media"}, 200
        elif "/download/" in path:
            return web.Response(body=self.download, content_type="application/octet-stream")
        elif "/sendToDevice/" in path:
            value, status = self.to_device.popleft() if self.to_device else ({}, 200)
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
    server.url = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
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
        config = {"enabled": True, "homeserver": hs.url,
                  "user_id": BOT, "access_token": "explicit-token",
                  "workspace_dir": str(tmp_path / "A"),
                  # Private native boundary: trusted fixture path, not public projection proof.
                  "legacy_state_dir": str(tmp_path / "legacy"), **extra}
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
    # New native boundary tests use a 2s bound; legacy tests retain their own bounds.
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)
