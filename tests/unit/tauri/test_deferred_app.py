# -*- coding: utf-8 -*-
"""Tests for the lightweight desktop ASGI shell."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.tauri.deferred_app import DeferredDesktopApp


def _wait_for_status(
    client: TestClient,
    phase_name: str,
    expected: str,
) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get("/api/startup/status")
        phase = response.json()["phases"][phase_name]
        if phase["status"] == expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"Startup phase {phase_name} did not become {expected}",
    )


def test_shell_serves_before_full_app_is_ready(tmp_path) -> None:
    release = threading.Event()
    full_app = FastAPI()

    @asynccontextmanager
    async def full_lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(release.wait)
        app.state.startup_ready = asyncio.Event()
        app.state.startup_ready.set()
        yield

    full_app.router.lifespan_context = full_lifespan

    @full_app.get("/api/full")
    def get_full() -> dict[str, bool]:
        return {"ready": True}

    console_dir = tmp_path / "console"
    console_dir.mkdir()
    (console_dir / "index.html").write_text(
        "<html>shell</html>",
        encoding="utf-8",
    )
    deferred = DeferredDesktopApp(
        app_loader=lambda: full_app,
        console_dir=console_dir,
    )

    with TestClient(deferred) as client:
        assert client.get("/api/version").status_code == 200
        assert client.get("/console").text == "<html>shell</html>"
        status = client.get("/api/startup/status").json()
        assert status["phases"]["api_ready"]["status"] == "ready"
        assert status["phases"]["chat_core_ready"]["status"] == "running"

        release.set()
        assert client.get("/api/full").json() == {"ready": True}
        _wait_for_status(client, "chat_core_ready", "ready")


def test_full_app_failure_returns_service_unavailable(tmp_path) -> None:
    console_dir = tmp_path / "console"
    console_dir.mkdir()
    (console_dir / "index.html").write_text(
        "<html>shell</html>",
        encoding="utf-8",
    )

    def fail() -> FastAPI:
        raise RuntimeError("full app failed")

    deferred = DeferredDesktopApp(
        app_loader=fail,
        console_dir=console_dir,
    )

    with TestClient(deferred) as client:
        response = client.get("/api/private")

    assert response.status_code == 503
    assert response.json()["detail"] == "full app failed"
