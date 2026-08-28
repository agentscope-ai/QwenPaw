# -*- coding: utf-8 -*-
"""Shared lightweight ASGI entry point with deferred full-app loading."""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..__version__ import __version__
from .startup_coordinator import StartupCoordinator


STARTUP_PHASES = (
    "api_ready",
    "chat_core_ready",
    "browser_ready",
    "memory_ready",
    "channels_ready",
    "plugins_ready",
    "background_ready",
)


def load_full_app() -> FastAPI:
    """Import and return the complete QwenPaw application."""
    module = importlib.import_module("qwenpaw.app._app")
    return module.app


class DeferredRuntime:
    """Own the complete app lifespan outside the server critical path."""

    def __init__(self, app_loader: Callable[[], FastAPI]) -> None:
        self.coordinator = StartupCoordinator(STARTUP_PHASES)
        self.full_app: FastAPI | None = None
        self.load_error: str | None = None
        self.ready = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._app_loader = app_loader

    def start(self, shell_app: FastAPI) -> None:
        """Start importing and initializing the complete app."""
        self.coordinator.mark_ready("api_ready")
        self._mark(shell_app, "api_ready")
        self.coordinator.mark_running("chat_core_ready")
        self._task = asyncio.create_task(
            self._run(shell_app),
            name="startup:full-app",
        )

    async def stop(self) -> None:
        """Exit the complete app lifespan and readiness monitors."""
        self._stop_requested.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        await self.coordinator.stop()

    async def _run(self, shell_app: FastAPI) -> None:
        try:
            self._mark(shell_app, "full_app_import_started")
            full_app = await asyncio.to_thread(self._app_loader)
            self._mark(shell_app, "full_app_import_done")
            self._copy_state(shell_app, full_app)
            full_app.state.startup_coordinator = self.coordinator
            async with full_app.router.lifespan_context(full_app):
                self.full_app = full_app
                self.ready.set()
                self.coordinator.start_worker(
                    "chat_core_ready",
                    lambda: self._wait_for_chat_core(full_app),
                )
                await self._stop_requested.wait()
        except Exception as exc:  # noqa: BLE001 - startup boundary
            self.load_error = str(exc)
            self.coordinator.mark_failed("chat_core_ready", exc)
            self.ready.set()

    @staticmethod
    def _mark(shell_app: FastAPI, event: str) -> None:
        metric = getattr(shell_app.state, "desktop_startup_metric", None)
        if metric is not None:
            metric(event)

    @staticmethod
    def _copy_state(shell_app: FastAPI, full_app: FastAPI) -> None:
        """Copy state installed by an outer process entry point."""
        for name in ("desktop_startup_metric", "uvicorn_server"):
            value = getattr(shell_app.state, name, None)
            if value is not None:
                setattr(full_app.state, name, value)

    @staticmethod
    async def _wait_for_chat_core(full_app: FastAPI) -> None:
        """Wait for the existing default-agent readiness primitive."""
        ready = getattr(full_app.state, "startup_ready", None)
        if ready is None:
            raise RuntimeError("Full app did not publish startup_ready")
        await ready.wait()


class DeferredApp:
    """Dispatch early readiness requests before the full app is ready."""

    def __init__(
        self,
        app_loader: Callable[[], FastAPI] = load_full_app,
    ) -> None:
        self.runtime = DeferredRuntime(app_loader)
        self.shell_app = self._create_shell_app()
        self.state = self.shell_app.state

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        """Dispatch one ASGI request to the shell or complete app."""
        if scope["type"] == "lifespan" or self._is_shell_request(scope):
            await self.shell_app(scope, receive, send)
            return

        await self.runtime.ready.wait()
        if self.runtime.full_app is None:
            response = JSONResponse(
                status_code=503,
                content={
                    "status": "failed",
                    "detail": self.runtime.load_error
                    or "QwenPaw runtime failed to start",
                },
            )
            await response(scope, receive, send)
            return

        required_phase = self._required_phase(scope)
        phase = await self.runtime.coordinator.wait_for_terminal(
            required_phase,
        )
        if phase.status != "ready":
            response = JSONResponse(
                status_code=503,
                content={
                    "status": "failed",
                    "detail": phase.error
                    or f"Startup phase failed: {required_phase}",
                },
            )
            await response(scope, receive, send)
            return
        await self.runtime.full_app(scope, receive, send)

    @staticmethod
    def _required_phase(scope: dict[str, Any]) -> str:
        """Choose the smallest safe readiness boundary for one request."""
        if scope["type"] == "http":
            method = scope.get("method", "GET").upper()
            path = scope.get("path", "")
            if method in {"GET", "HEAD", "OPTIONS"}:
                return "chat_core_ready"
            if path in {
                "/api/console/chat",
                "/api/console/chat/stop",
                "/api/console/chat/task",
            }:
                return "chat_core_ready"
        return "background_ready"

    @staticmethod
    def _is_shell_request(scope: dict[str, Any]) -> bool:
        if scope["type"] != "http":
            return False
        return scope.get("path", "") in {
            "/api/healthz",
            "/api/startup/status",
            "/api/version",
        }

    def _create_shell_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            self.runtime.start(shell_app)
            try:
                yield
            finally:
                await self.runtime.stop()

        shell_app = FastAPI(lifespan=lifespan)

        @shell_app.get("/api/version")
        def get_version() -> dict[str, str]:
            return {"version": __version__}

        @shell_app.get("/api/startup/status")
        def get_startup_status() -> dict[str, Any]:
            return self.runtime.coordinator.snapshot()

        @shell_app.get("/api/healthz")
        def get_healthz() -> Any:
            snapshot = self.runtime.coordinator.snapshot()
            chat_phase = snapshot["phases"]["chat_core_ready"]
            if chat_phase["status"] != "ready":
                status = "failed" if self.runtime.load_error else "starting"
                detail = self.runtime.load_error or (
                    "Background startup in progress"
                )
                return JSONResponse(
                    status_code=503,
                    content={"status": status, "detail": detail},
                )

            full_app = self.runtime.full_app
            registry = (
                getattr(full_app.state, "multi_agent_manager", None)
                if full_app is not None
                else None
            )
            agents = registry.list_loaded_agents() if registry else []
            start_time = (
                getattr(full_app.state, "startup_time", None)
                if full_app is not None
                else None
            )
            uptime = (
                round(time.time() - start_time, 2)
                if start_time is not None
                else None
            )
            return {
                "status": "ok",
                "agents_loaded": agents,
                "uptime_seconds": uptime,
            }

        return shell_app


app = DeferredApp()
