# -*- coding: utf-8 -*-
"""Integration test for the NocoBase auth plugin lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.helpers import (
    LOADER_READY_TIMEOUT,
    PLUGIN_HTTP_TIMEOUT,
    wait_until_plugin_loader_ready,
)

PLUGIN_ID = "nocobase-auth"
PLUGIN_SOURCE = (
    Path(__file__).parents[2] / "plugins" / "bundle" / "nocobase_auth"
)


def _install_local_plugin(app_server, source_path: Path) -> dict:
    wait_until_plugin_loader_ready(app_server)
    resp = app_server.api_request(
        "POST",
        "/api/plugins/install",
        json={"source": str(source_path), "force": False},
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"install failed: {resp.status_code} | {resp.text} | "
        f"logs: {app_server.logs_tail()}"
    )
    return resp.json()


def _delete_plugin(app_server, plugin_id: str):
    import time

    deadline = time.time() + LOADER_READY_TIMEOUT
    while True:
        wait_until_plugin_loader_ready(app_server)
        resp = app_server.api_request(
            "DELETE",
            f"/api/plugins/{plugin_id}",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        if resp.status_code != 503 or time.time() >= deadline:
            return resp
        time.sleep(0.5)


@pytest.mark.integration
@pytest.mark.p1
def test_nocobase_plugin_install_status_uninstall(app_server) -> None:
    """Verify the NocoBase auth plugin installs, exposes routes,
    and uninstalls."""
    assert PLUGIN_SOURCE.is_dir(), f"missing plugin source: {PLUGIN_SOURCE}"

    try:
        payload = _install_local_plugin(app_server, PLUGIN_SOURCE)
        assert payload.get("id") == PLUGIN_ID
        assert payload.get("loaded") is True

        status_resp = app_server.api_request(
            "GET",
            f"/api/plugins/{PLUGIN_ID}/status",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert status_resp.status_code == 200, app_server.logs_tail()
        assert status_resp.json().get("loaded") is True

        # The plugin status endpoint should report disabled by default.
        auth_status = app_server.api_request(
            "GET",
            "/api/nocobase-auth/status",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert auth_status.status_code == 200, app_server.logs_tail()
        body = auth_status.json()
        assert body.get("enabled") is False
        assert body.get("configured") is False

        delete_resp = _delete_plugin(app_server, PLUGIN_ID)
        assert delete_resp.status_code == 200, app_server.logs_tail()
    finally:
        try:
            _delete_plugin(app_server, PLUGIN_ID)
        except AssertionError:
            pass
