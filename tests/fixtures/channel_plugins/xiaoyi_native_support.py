"""
Actual XiaoYi Driver/dual WebSocket/HTTP, with controlled external gateway.
"""
import asyncio
import base64
import hashlib
import hmac
import importlib
import json
from pathlib import Path

from aiohttp import WSMsgType, web
import pytest_asyncio

from g2_shared_response_suite import Peer

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "plugins/channel/xiaoyi"


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


def inbound(
    request="request-A",
    task="task-A",
    message="message-A",
    text="hello",
    session="session-A",
):
    return {
        "agentId": "local-agent",
        "method": "message/stream",
        "id": request,
        "params": {
            "sessionId": session,
            "id": task,
            "message": {
                "messageId": message,
                "parts": [{"kind": "text", "text": text}],
            },
        },
    }


class Gateway:
    """Real external peer; credentials are local test values only."""

    def __init__(self):
        self.connections, self.headers, self.frames = {}, {}, []
        self.asset = b"native-file-bytes"

    async def gateway(self, request):
        server = request.match_info["server"]
        headers = {
            name: request.headers[name]
            for name in ("x-access-key", "x-ts", "x-sign", "x-agent-id")
        }
        expected = base64.b64encode(
            hmac.new(
                b"local-sk", headers["x-ts"].encode(), hashlib.sha256
            ).digest()
        ).decode()
        assert headers == {
            "x-access-key": "local-ak",
            "x-ts": headers["x-ts"],
            "x-sign": expected,
            "x-agent-id": "local-agent",
        }
        assert headers["x-ts"].isdigit()
        self.headers[server] = headers
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections[server] = ws
        async for frame in ws:
            if frame.type == WSMsgType.TEXT:
                self.frames.append((server, json.loads(frame.data)))
        return ws

    async def asset_response(self, request):
        if request.match_info["name"] == "missing":
            return web.Response(status=404)
        return web.Response(body=self.asset, content_type="image/png")

    async def push(self, value, server="primary"):
        await self.connections[server].send_json(value)

    def results(self):
        return [
            (server, json.loads(frame["msgDetail"])["result"])
            for server, frame in self.frames
            if frame.get("msgType") == "agent_response"
        ]


@pytest_asyncio.fixture
async def gateway():
    external = Gateway()
    app = web.Application()
    app.router.add_get("/ws/{server}", external.gateway)
    app.router.add_get("/asset/{name}", external.asset_response)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    external.base = f"http://127.0.0.1:{port}"
    external.primary = f"ws://127.0.0.1:{port}/ws/primary"
    external.backup = f"ws://127.0.0.1:{port}/ws/backup"
    try:
        yield external
    finally:
        for connection in external.connections.values():
            await connection.close()
        await runner.cleanup()


@pytest_asyncio.fixture
async def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE))
    result = {}
    for name in ("platform", "connection", "driver", "errors"):
        module = importlib.import_module("qwenpaw_channel_xiaoyi." + name)
        assert Path(
            module.__file__
        ).resolve() == SOURCE / "qwenpaw_channel_xiaoyi" / (name + ".py")
        result[name] = module
    return result


class HostBoundary(Peer):
    """
    Only the real Driver's host RPC endpoint, not a Core/Agent substitute.
    """

    def __init__(self):
        super().__init__()
        self.methods, self.state = {}, {}
        self.batches, self.notifications = [], []
        self.accept = True

    def register_method(self, name, handler):
        self.methods[name] = handler

    async def call(self, method, params):
        if method.startswith("host.receipt."):
            return await super().call(method, params)
        if method == "host.state.get":
            return {"value": self.state.get(params["key"])}
        if method == "host.state.put":
            self.state[params["key"]] = json.loads(json.dumps(params["value"]))
            return {}
        assert method == "event.batch", method
        self.batches.append(params)
        return {
            "batch_id": params["batch_id"],
            "accepted_event_ids": [params["events"][0]["event_id"]]
            if self.accept
            else [],
        }

    async def notify(self, method, params):
        self.notifications.append((method, params))


@pytest_asyncio.fixture
async def native_driver(gateway, modules, tmp_path, monkeypatch):
    from qwenpaw.channel_protocol.models import IdentityParams
    from qwenpaw.channel_protocol.shared_worker import DriverContext

    monkeypatch.setattr(modules["platform"], "DEFAULT_WS_URL", gateway.primary)
    monkeypatch.setattr(
        modules["platform"], "DEFAULT_WS_URL_BACKUP", gateway.backup
    )
    driver, peer = modules["driver"].XiaoYiDriver(), HostBoundary()
    identity = IdentityParams("xiaoyi", "native-workspace", 1)
    descriptor = json.loads((SOURCE / "channel.json").read_text())
    driver.bind(DriverContext(peer, identity, descriptor["capabilities"]))
    try:
        await driver.start(
            {
                "enabled": True,
                "ak": "local-ak",
                "sk": "local-sk",
                "agent_id": "local-agent",
                "workspace_dir": str(tmp_path),
            }
        )
        assert driver._connected
        await eventually(lambda: len(gateway.connections) == 2)
        yield driver, peer, identity.to_mapping(), gateway
    finally:
        await driver.stop()


async def open_route(peer, identity, session="xiaoyi:session-A", **meta):
    result = await peer.methods["channel.response.open"](
        {**identity, "to_handle": session, "meta": meta}, None
    )
    return result["response_handle"]


async def send(
    peer,
    identity,
    handle,
    *,
    delivery="delivery-A",
    text="native answer",
    parts=None,
    source="direct",
):
    from qwenpaw.channel_protocol.models import SendParams

    params = SendParams.from_mapping(
        {
            **identity,
            "to_handle": handle,
            "delivery_id": delivery,
            "operation": "message.create",
            "content_source": source,
            "content_parts": parts
            if parts is not None
            else [{"type": "text", "text": text}],
        }
    )
    return await peer.methods["channel.send"](params, None)
