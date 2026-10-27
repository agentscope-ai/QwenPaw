# -*- coding: utf-8 -*-
"""Hub-owned model listener, isolated from all control-plane routes."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from contextlib import asynccontextmanager, contextmanager

import uvicorn
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from ...app.exception_handlers import register_exception_handlers
from .routes import runtime_model_router


class _ModelServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        """Leave process signals to the main Hub server."""
        yield


class ModelListener:
    """Keep a stable endpoint for runtimes across Hub process restarts."""

    def __init__(self, store, catalog, gateway):
        self.store = store
        self.port = 0
        self.app = FastAPI(
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        register_exception_handlers(self.app)
        self.app.include_router(
            runtime_model_router(catalog, gateway),
            prefix="/api/hub",
        )

    def _bind(self, hosts):
        addresses = {ipaddress.IPv4Address(host) for host in hosts}
        if not addresses or any(
            address.is_unspecified or address.is_multicast or address.is_global
            for address in addresses
        ):
            raise ValueError("Model listener requires local interface IPs")
        listeners = []
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT value_json FROM hub_settings "
                    "WHERE key = 'model_listener_port'",
                ).fetchone()
                port = int(row[0]) if row else 0
                for address in sorted(addresses):
                    listener = socket.socket(
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                    )
                    listeners.append(listener)
                    option = (
                        socket.SO_EXCLUSIVEADDRUSE
                        if hasattr(socket, "SO_EXCLUSIVEADDRUSE")
                        else socket.SO_REUSEADDR
                    )
                    listener.setsockopt(socket.SOL_SOCKET, option, 1)
                    listener.bind((str(address), port))
                    port = listener.getsockname()[1]
                    listener.listen(128)
                    listener.setblocking(False)
                db.execute(
                    "INSERT OR IGNORE INTO hub_settings "
                    "(key, value_json, updated_at) VALUES "
                    "('model_listener_port', ?, datetime('now'))",
                    (f"{port}",),
                )
            self.port = port
            return listeners
        except BaseException:
            for listener in listeners:
                listener.close()
            raise

    @asynccontextmanager
    async def serve(self, hosts):
        """Run on the Hub event loop so gateway limits remain shared."""
        if not hosts:
            yield
            return
        listeners = await run_in_threadpool(self._bind, hosts)
        server = _ModelServer(
            uvicorn.Config(
                self.app,
                lifespan="off",
                access_log=False,
                log_config=None,
                proxy_headers=False,
                timeout_graceful_shutdown=10,
            ),
        )
        task = asyncio.create_task(server.serve(sockets=listeners))
        try:
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Hub model listener failed to start")
                await asyncio.sleep(0.01)
            yield
        finally:
            server.should_exit = True
            try:
                await task
            finally:
                for listener in listeners:
                    listener.close()
                self.port = 0
