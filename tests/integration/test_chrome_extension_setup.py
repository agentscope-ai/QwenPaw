# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def test_install_status_reports_plugin_owned_installation_state() -> None:
    app = FastAPI()
    app.include_router(api_router)
    body = TestClient(app).get("/install-status").json()
    assert "connected" not in body
    assert "readiness_state" not in body
    assert "installed" in body
    assert body["bridge_endpoint"].endswith("/api/ws/chrome")


# test_chrome_setup_home_isolation.py

TESTS_DIR = Path("tests/integration")


# test_chrome_setup_hygiene.py


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
