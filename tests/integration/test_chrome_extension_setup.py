# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.bundle.chrome import extension_setup
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


# test_chrome_remote_bridge_endpoint.py

REMOTE_WS_URL = "ws://192.168.31.4:8088/api/ws/chrome"


@pytest.mark.integration
@pytest.mark.p1
def test_require_bridge_endpoint_prefers_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(extension_setup.BRIDGE_WS_URL_ENV, REMOTE_WS_URL)

    assert extension_setup.require_bridge_endpoint() == REMOTE_WS_URL
    assert extension_setup.bridge_endpoint_source() == "override"
    assert extension_setup.endpoint_is_loopback(REMOTE_WS_URL) is False


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.parametrize(
    "bad_url",
    [
        "http://192.168.31.4:8088/api/ws/chrome",
        "ws:///no-host",
        "ws://user:pass@192.168.31.4:8088/api/ws/chrome",
        "not-a-url",
    ],
)
def test_validate_bridge_ws_url_rejects_invalid(bad_url: str) -> None:
    with pytest.raises(extension_setup.BridgeEndpointError):
        extension_setup.validate_bridge_ws_url(bad_url)


@pytest.mark.integration
@pytest.mark.p2
def test_endpoint_is_loopback_classification() -> None:
    assert extension_setup.endpoint_is_loopback(
        "ws://127.0.0.1:8088/api/ws/chrome",
    )
    assert extension_setup.endpoint_is_loopback(
        "ws://localhost:8088/api/ws/chrome",
    )
    assert extension_setup.endpoint_is_loopback(
        "ws://[::1]:8088/api/ws/chrome",
    )
    assert not extension_setup.endpoint_is_loopback(REMOTE_WS_URL)


@pytest.mark.integration
@pytest.mark.p1
def test_setup_writes_explicit_remote_endpoint_and_token(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)

    result = extension_setup.setup_extension_files(
        home=isolated_home,
        ws_url=REMOTE_WS_URL,
        token="shared-token",
    )

    assert result["installed"] is True
    assert result["ws_url"] == REMOTE_WS_URL
    config = json.loads(
        (isolated_home / ".qwenpaw" / "nm-bridge.json").read_text(
            encoding="utf-8",
        ),
    )
    assert config == {"ws_url": REMOTE_WS_URL, "token": "shared-token"}
    bridge_config = (
        isolated_home
        / ".qwenpaw"
        / "chrome-extension"
        / "qwenpaw-chrome"
        / "bridge_config.js"
    ).read_text(encoding="utf-8")
    assert '"localPort":8088' in bridge_config


@pytest.mark.integration
@pytest.mark.p1
def test_setup_rejects_blank_explicit_token(isolated_home: Path) -> None:
    with pytest.raises(ValueError, match="token"):
        extension_setup.setup_extension_files(
            home=isolated_home,
            ws_url=REMOTE_WS_URL,
            token="   ",
        )


@pytest.mark.integration
@pytest.mark.p1
def test_cli_main_sets_up_remote_machine(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)

    rc = extension_setup.main(
        ["--ws-url", REMOTE_WS_URL, "--token", "cli-token"],
    )

    assert rc == 0
    config = json.loads(
        (isolated_home / ".qwenpaw" / "nm-bridge.json").read_text(
            encoding="utf-8",
        ),
    )
    assert config == {"ws_url": REMOTE_WS_URL, "token": "cli-token"}


@pytest.mark.integration
@pytest.mark.p1
def test_cli_main_rejects_invalid_ws_url(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = extension_setup.main(["--ws-url", "http://example.com/ws"])

    assert rc == 2
    assert "ws://" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.p1
def test_install_status_marks_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(extension_setup.BRIDGE_WS_URL_ENV, REMOTE_WS_URL)
    app = FastAPI()
    app.include_router(api_router)

    body = TestClient(app).get("/install-status").json()

    assert body["bridge_endpoint"] == REMOTE_WS_URL
    assert body["endpoint_source"] == "override"
    assert body["remote"] is True
    assert body["secure_transport"] is False
    assert body["endpoint_error"] is None


@pytest.mark.integration
@pytest.mark.p2
def test_install_status_surfaces_invalid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(extension_setup.BRIDGE_WS_URL_ENV, "not-a-url")
    app = FastAPI()
    app.include_router(api_router)

    body = TestClient(app).get("/install-status").json()

    assert body["bridge_endpoint"] is None
    assert body["endpoint_error"]
    assert body["remote"] is False
