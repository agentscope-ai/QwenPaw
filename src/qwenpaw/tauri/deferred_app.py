# -*- coding: utf-8 -*-
"""Desktop ASGI shell built on the shared deferred application runtime."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..app.deferred_app import DeferredApp


_INDEX_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _load_full_app() -> FastAPI:
    """Configure desktop browser state and load the complete application."""
    from ..browser.runtime.managed_playwright import (
        configure_desktop_playwright_cache,
    )

    configure_desktop_playwright_cache()
    from ..app.deferred_app import load_full_app

    return load_full_app()


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


class DeferredDesktopApp(DeferredApp):
    """Serve the desktop console while the complete app starts."""

    def __init__(
        self,
        app_loader: Callable[[], FastAPI] = _load_full_app,
        console_dir: Path | None = None,
    ) -> None:
        super().__init__(app_loader=app_loader)
        self._install_console_routes(
            console_dir or _resolve_console_dir(),
        )

    @staticmethod
    def _is_shell_request(scope: dict[str, Any]) -> bool:
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return not path.startswith("/api/") or path in {
            "/api/healthz",
            "/api/startup/status",
            "/api/version",
        }

    def _install_console_routes(self, console_dir: Path) -> None:
        index_path = console_dir / "index.html"
        assets_dir = console_dir / "assets"
        if assets_dir.is_dir():
            self.shell_app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="desktop-assets",
            )

        def serve_index() -> FileResponse:
            if not index_path.is_file():
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_path, headers=_INDEX_HEADERS)

        @self.shell_app.get("/console")
        @self.shell_app.get("/console/")
        @self.shell_app.get("/console/{full_path:path}")
        def get_console(full_path: str = "") -> FileResponse:
            _ = full_path
            return serve_index()

        @self.shell_app.get("/{full_path:path}")
        def get_static_or_index(full_path: str) -> FileResponse:
            if full_path and ".." not in full_path:
                candidate = console_dir / full_path
                if not Path(full_path).is_absolute() and candidate.is_file():
                    return FileResponse(candidate)
            return serve_index()


app = DeferredDesktopApp()
