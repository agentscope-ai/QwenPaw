# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.bundle.chrome.api import routes
from plugins.bundle.chrome.api.routes import api_router
from plugins.bundle.chrome.extension_setup import (
    _uninstall,
    _write_nm_config,
    native_manifest_path,
)

# test_chrome_bridge_config.py


# test_chrome_cws_coming_soon.py


# test_chrome_extension_port_injection.py

SERVICE_WORKER = Path(
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)


# test_chrome_routes_asgi.py


@pytest.mark.integration
@pytest.mark.p1
def test_install_status_reports_plugin_owned_installation_state() -> None:
    app = FastAPI()
    app.include_router(api_router)
    body = TestClient(app).get("/install-status").json()
    assert "connected" not in body
    assert "readiness_state" not in body
    assert "installed" in body
    assert body["bridge_endpoint"].endswith("/api/ws/chrome")


@pytest.mark.integration
@pytest.mark.p1
def test_setup_runs_off_event_loop_and_serializes_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    calls = 0

    def blocking_setup(**_kwargs: object) -> dict[str, str | bool]:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            release_first.wait(timeout=0.5)
        else:
            second_started.set()
        return {"installed": True}

    async def fake_status() -> dict[str, object]:
        return {}

    monkeypatch.setattr(routes, "setup_extension_files", blocking_setup)
    monkeypatch.setattr(routes, "get_extension_status", fake_status)

    async def exercise() -> None:
        first = asyncio.create_task(
            routes.extension_setup(routes.ExtensionSetupRequest()),
        )
        second: asyncio.Task[dict[str, object]] | None = None
        try:
            await asyncio.wait_for(asyncio.to_thread(first_started.wait), 0.25)

            heartbeat = asyncio.Event()
            started_at = asyncio.get_running_loop().time()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), 0.25)
            assert asyncio.get_running_loop().time() - started_at < 0.25

            second = asyncio.create_task(
                routes.extension_setup(routes.ExtensionSetupRequest()),
            )
            await asyncio.sleep(0.05)
            assert not second_started.is_set()
        finally:
            release_first.set()
            await first
            if second is not None:
                await second

        assert second_started.is_set()
        assert calls == 2

    asyncio.run(exercise())


# test_chrome_setup_home_isolation.py

TESTS_DIR = Path("tests/integration")


# test_chrome_setup_hygiene.py


@pytest.mark.integration
@pytest.mark.p1
def test_uninstall_removes_config_and_extension_dir(
    tmp_path: Path,
    isolated_home: Path,
) -> None:
    _write_nm_config(tmp_path, "token", "ws://127.0.0.1:8088/api/ws/chrome")
    extension = tmp_path / "chrome-extension"
    extension.mkdir()
    manifest = native_manifest_path(isolated_home)
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    _uninstall(tmp_path, home=isolated_home)

    assert not (tmp_path / "nm-bridge.json").exists()
    assert not extension.exists()
    assert not manifest.exists()
    assert Path.home() == isolated_home


# test_chrome_setup_repair.py
