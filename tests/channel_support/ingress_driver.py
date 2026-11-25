# -*- coding: utf-8 -*-
"""Loopback HTTP/WS peer for host forwarding and lifecycle regression tests."""

import asyncio
import hashlib
import hmac
import os
import socket
from dataclasses import replace

from aiohttp import web

from qwenpaw.plugins import SDKAccessError, StaleContextError
from qwenpaw.plugins.channel_ingress import ChannelIngressSpec
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelSendResult


class Driver(ChannelDriver):
    async def start(self, ch):
        self.ch, self.sockets = ch, set()
        self.binding = None
        app = web.Application()
        for path, callback in (("/echo", self.echo), ("/hold", self.hold)):
            app.router.add_post(ch.ingress.path + path, callback)
        app.router.add_get(ch.ingress.path + "/ws", self.websocket)
        listener = socket.socket()
        ch.resources.defer(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        runner = web.AppRunner(
            app,
            handler_cancellation=True,
            shutdown_timeout=1,
        )
        await runner.setup()
        ch.resources.defer(runner.cleanup)
        ch.resources.defer(self.close_sockets)
        await web.SockSite(runner, listener).start()
        self.spec = ChannelIngressSpec(
            "127.0.0.1",
            listener.getsockname()[1],
            public_base_url=ch.config["public_origin"],
        )
        self.binding = await ch.ingress.register(self.spec)
        await self.save_binding()
        await ch.report_status("connected")

    async def save_binding(self):
        await self.ch.storage.awrite_json(
            "binding.json",
            {
                "pid": os.getpid(),
                "port": self.spec.port,
                "workspace": self.ch.workspace_id,
                "urls": {
                    path.rsplit("/", 1)[1]: self.binding.url(path)
                    for path in self.binding.paths
                },
            },
        )

    async def authorize(self, request):
        if self.binding is None:
            raise web.HTTPServiceUnavailable()
        try:
            original = self.binding.verify(request.headers)
        except (SDKAccessError, StaleContextError) as exc:
            raise web.HTTPForbidden() from exc
        body = await request.read()
        expected = hmac.new(
            self.ch.config["secret"].encode(),
            original.encode() + body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(
            expected,
            request.headers.get("X-Platform-Signature", ""),
        ):
            raise web.HTTPForbidden()
        return original, body

    async def echo(self, request):
        original, body = await self.authorize(request)
        return web.json_response(
            {
                "workspace": self.ch.workspace_id,
                "body": body.decode(),
                "original": original,
            },
        )

    async def hold(self, request):
        await self.authorize(request)
        await self.ch.storage.awrite_json("http-open.json", True)
        try:
            await asyncio.Event().wait()
        finally:
            await self.ch.storage.awrite_json("http-closed.json", True)

    async def websocket(self, request):
        await self.authorize(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        try:
            async for message in ws:
                if message.type == web.WSMsgType.TEXT:
                    await ws.send_str(
                        self.ch.workspace_id + ":" + message.data,
                    )
        finally:
            self.sockets.discard(ws)
            await self.ch.storage.awrite_json("ws-closed.json", True)
        return ws

    async def close_sockets(self):
        await asyncio.gather(*(ws.close() for ws in tuple(self.sockets)))

    async def send(self, ch, response):
        operation = response.content[0].text
        if operation == "close":
            await ch.ingress.close()
        else:
            previous = self.binding
            self.binding = await ch.ingress.update(
                replace(
                    self.spec,
                    readiness="degraded" if operation == "pause" else "ready",
                ),
            )
            try:
                previous.url(previous.paths[0])
            except StaleContextError:
                await ch.storage.awrite_json("old-binding-invalid.json", True)
            await self.save_binding()
        return ChannelSendResult("local-control")
