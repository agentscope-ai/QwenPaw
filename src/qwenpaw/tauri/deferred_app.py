# -*- coding: utf-8 -*-
"""Lightweight desktop ASGI shell with deferred full-app loading."""

from __future__ import annotations

import asyncio
import importlib
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..__version__ import __version__
from .startup_coordinator import StartupCoordinator


_PHASES = (
    "api_ready",
    "chat_core_ready",
    "browser_ready",
    "memory_ready",
    "channels_ready",
    "plugins_ready",
)
_INDEX_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _load_full_app() -> FastAPI:
    """Import and return the complete QwenPaw application."""
    from ..browser.runtime.managed_playwright import (
        configure_desktop_playwright_cache,
    )

    configure_desktop_playwright_cache()
    module = importlib.import_module("qwenpaw.app._app")
    return module.app


def _resolve_console_dir() -> Path:
    """Resolve packaged console assets without importing the full app."""
    configured = os.environ.get("QWENPAW_CONSOLE_STATIC_DIR", "").strip()
    if configured:
        return Path(configured)

    package_dir = Path(__file__).resolve().parent.parent
    candidates = (
        package_dir / "console",
        package_dir.parent.parent / "console" / "dist",
        Path.cwd() / "console" / "dist",
        Path.cwd() / "console_dist",
    )
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0]


class DeferredRuntime:
    """Own the complete app lifespan outside the desktop critical path."""

    def __init__(self, app_loader: Callable[[], FastAPI]) -> None:
        self.coordinator = StartupCoordinator(_PHASES)
        self.full_app: FastAPI | None = None
        self.load_error: str | None = None
        self.ready = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._app_loader = app_loader

    def start(self, shell_app: FastAPI) -> None:
        """Start importing and initializing the complete app."""
        self.coordinator.mark_ready("api_ready")
        self.coordinator.mark_running("chat_core_ready")
        self._task = asyncio.create_task(
            self._run(shell_app),
            name="desktop-startup:full-app",
        )

    async def stop(self) -> None:
        """Exit the complete app lifespan and stop readiness monitors."""
        self._stop_requested.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        await self.coordinator.stop()

    async def _run(self, shell_app: FastAPI) -> None:
        try:
            full_app = await asyncio.to_thread(self._app_loader)
            self._copy_desktop_state(shell_app, full_app)
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
    def _copy_desktop_state(shell_app: FastAPI, full_app: FastAPI) -> None:
        """Copy state installed by the desktop entry point."""
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


class DeferredDesktopApp:
    """Dispatch early shell requests before the complete app is ready."""

    def __init__(
        self,
        app_loader: Callable[[], FastAPI] = _load_full_app,
        console_dir: Path | None = None,
    ) -> None:
        self.runtime = DeferredRuntime(app_loader)
        self.shell_app = self._create_shell_app(
            console_dir or _resolve_console_dir(),
        )
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
                    or "Desktop runtime failed to start",
                },
            )
            await response(scope, receive, send)
            return
        await self.runtime.full_app(scope, receive, send)

    @staticmethod
    def _is_shell_request(scope: dict[str, Any]) -> bool:
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return not path.startswith("/api/") or path in {
            "/api/version",
            "/api/startup/status",
        }

    def _create_shell_app(self, console_dir: Path) -> FastAPI:
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

        index_path = console_dir / "index.html"
        assets_dir = console_dir / "assets"
        if assets_dir.is_dir():
            shell_app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="desktop-assets",
            )

        def serve_index() -> FileResponse:
            if not index_path.is_file():
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_path, headers=_INDEX_HEADERS)

        @shell_app.get("/console")
        @shell_app.get("/console/")
        @shell_app.get("/console/{full_path:path}")
        def get_console(full_path: str = "") -> FileResponse:
            _ = full_path
            return serve_index()

        @shell_app.get("/{full_path:path}")
        def get_static_or_index(full_path: str) -> FileResponse:
            if full_path and ".." not in full_path:
                candidate = console_dir / full_path
                if not Path(full_path).is_absolute() and candidate.is_file():
                    return FileResponse(candidate)
            return serve_index()

        return shell_app


app = DeferredDesktopApp()
