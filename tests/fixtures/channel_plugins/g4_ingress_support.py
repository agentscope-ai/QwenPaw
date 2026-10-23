"""Actual Loader/Manager worker listener and production ASGI relay fixtures."""

import asyncio
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import aiohttp
from fastapi import FastAPI, Request, WebSocket
import pytest_asyncio
import uvicorn

from extension_process_suite import eventually
from extension_sample import sample_source

PATHS = (
    "/sample/http",
    "/sample/hold",
    "/sample/redirect",
    "/sample/target",
    "/sample/signature",
    "/sample/ws",
    "/sample/ws-reject",
)


def listener_source(directory, key, *, capabilities=None):
    source = sample_source(directory, key, capabilities=capabilities)
    descriptor = source / "channel.json"
    value = json.loads(descriptor.read_text())
    value["capabilities"] = sorted(
        {*value["capabilities"], "ingress_endpoint"}
    )
    descriptor.write_text(json.dumps(value))
    (source / "requirements.txt").write_text("aiohttp>=3.9.0\ntwilio>=9.0.0\n")
    (source / key / "listener.py").write_bytes(
        Path(__file__).with_name("g4_ingress_child.py").read_bytes()
    )
    path = source / key / "driver.py"
    body = path.read_text()
    start = body.index("    async def start(self, config):")
    end = body.index("    def _check_connection", start)
    body = body[:start] + """    async def start(self, config):
        from .listener import Listener

        self._config = dict(config)
        self._stopping = False
        self._connected = False
        self._platform = self
        self._connection_generation += 1
        await self._restore_responses()
        await self._context.set_platform_state("connecting")
        self.listener = Listener(self)
        self._context.peer.register_method(
            "fixture.listener", self.listener.control,
        )
        await self.listener.start()
        self._connected = True
        await self._context.set_platform_state("connected")

    async def stop(self):
        self._stopping = True
        if hasattr(self, "listener"):
            await self.listener.stop()
        await self._checkpoint()
        self._connected = False
        await self._context.set_platform_state("disconnected")

""" + body[end:]
    path.write_text(body)
    return source


async def listener(rt, action="inspect", **params):
    return await rt.process.call(
        "fixture.listener",
        {"action": action, **params},
    )


@pytest_asyncio.fixture
async def ingress(runtime):
    from qwenpaw.app.channels.ingress import ChannelIngressService
    from qwenpaw.app.auth import is_trusted_proxy
    from qwenpaw.plugins.registry import PluginRegistry

    # Runtime fixture resets the singleton before this fixture creates service.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    registry = PluginRegistry()
    rules = {
        ("sample_chat", "sample_chat"): tuple(
            ("WEBSOCKET" if path.startswith("/sample/ws") else "POST", path)
            for path in PATHS
        )
    }
    service = ChannelIngressService(
        registry,
        host_port=port,
        routes=rules,
        trusted_proxy=is_trusted_proxy,
    )
    app = FastAPI()

    async def http(request: Request):
        return await service.forward_http(request)

    async def websocket(websocket: WebSocket):
        await service.forward_websocket(websocket)

    for method, path in rules[("sample_chat", "sample_chat")]:
        if method == "WEBSOCKET":
            app.add_api_websocket_route(path, websocket)
        else:
            app.add_api_route(path, http, methods=[method])
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            proxy_headers=False,
            log_level="error",
            ws="wsproto",
            ws_max_size=64 * 1024 * 1024,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        await eventually(lambda: server.started)
        async with aiohttp.ClientSession(trust_env=False) as client:
            yield SimpleNamespace(
                runtime=runtime,
                service=service,
                registry=registry,
                client=client,
                base=f"http://127.0.0.1:{port}",
                port=port,
            )
    finally:
        await service.aclose()
        server.should_exit = True
        await asyncio.wait_for(task, 8)
        sock.close()


async def start(ingress, **kwargs):
    rt = await ingress.runtime(source_factory=listener_source, **kwargs)
    health = rt.process.health_snapshot()
    assert (
        health["state"] == "ready" and health["platform_state"] == "connected"
    )
    info = await listener(rt)
    assert info["pid"] == health["pid"]
    assert info["forwarding"]["host_port"] == ingress.port
    return rt, info
