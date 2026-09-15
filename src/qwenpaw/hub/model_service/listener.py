# -*- coding: utf-8 -*-
"""Hub-owned model listener, isolated from all control-plane routes."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager, contextmanager

import uvicorn
from fastapi import FastAPI

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

    def _bind(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_EXCLUSIVEADDRUSE,
                    1,
                )
            else:
                listener.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_REUSEADDR,
                    1,
                )
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT value_json FROM hub_settings "
                    "WHERE key = 'model_listener_port'",
                ).fetchone()
                listener.bind(("0.0.0.0", int(row[0]) if row else 0))
                port = listener.getsockname()[1]
                db.execute(
                    "INSERT OR IGNORE INTO hub_settings "
                    "(key, value_json, updated_at) VALUES "
                    "('model_listener_port', ?, datetime('now'))",
                    (f"{port}",),
                )
            listener.listen(128)
            listener.setblocking(False)
            self.port = port
            return listener
        except BaseException:
            listener.close()
            raise

    @asynccontextmanager
    async def serve(self):
        """Run on the Hub event loop so gateway limits remain shared."""
        listener = self._bind()
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
        task = asyncio.create_task(server.serve(sockets=[listener]))
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
                listener.close()
                self.port = 0
