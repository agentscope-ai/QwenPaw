# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
# -*- coding: utf-8 -*-
"""Integration tests for the 7 plugin types via mock sample plugins
(Sprint 3.2).

Each test builds an in-memory zip with a minimal manifest + backend.py
that exercises one PluginType registration path:

  A. Provider plugin  — api.register_provider()
  B. Hook plugin      — api.register_startup_hook() etc.
  C. Command plugin   — api.register_control_command()
  D. HTTP API plugin  — api.register_http_router()
  E. Frontend plugin  — entry.frontend served via /api/frontend_plugin
  F. Composite plugin — backend + frontend, plus error paths

The full lifecycle is exercised: upload → loaded → side-effect visible →
uninstall → side-effect gone.

Reuses _build_sample_plugin_zip pattern from test_plugins.py and the
_upload_plugin_zip / _delete_plugin helpers.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from typing import Any

import httpx
import pytest

from helpers import (
    LOADER_READY_TIMEOUT,
    PLUGIN_HTTP_TIMEOUT,
    wait_until_plugin_loader_ready,
)


# ------------------------------------------------------------------ #
# helpers (zip builders specific to each plugin type)
# ------------------------------------------------------------------ #


def _build_zip(plugin_id: str, manifest: dict, files: dict) -> bytes:
    """Build a zip with plugin.json + arbitrary additional files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{plugin_id}/plugin.json", json.dumps(manifest))
        for relpath, content in files.items():
            zf.writestr(f"{plugin_id}/{relpath}", content)
    return buf.getvalue()


def _provider_plugin_zip(plugin_id: str) -> bytes:
    """Plugin that registers a custom provider via OpenAIProvider."""
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "from qwenpaw.providers.openai_provider import OpenAIProvider\n"
        "\n"
        "\n"
        "class _MockProviderPlugin:\n"
        "    def register(self, api):\n"
        "        api.register_provider(\n"
        f'            provider_id="{plugin_id}-prov",\n'
        "            provider_class=OpenAIProvider,\n"
        f'            label="Mock {plugin_id}",\n'
        '            base_url="http://127.0.0.1:9/v1",\n'
        '            chat_model="OpenAIChatModel",\n'
        "            require_api_key=False,\n"
        "        )\n"
        "\n"
        "\n"
        "plugin = _MockProviderPlugin()\n"
    )
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "provider",
        "entry": {"backend": "plugin.py"},
        "meta": {"provider_id": f"{plugin_id}-prov"},
    }
    return _build_zip(plugin_id, manifest, {"plugin.py": backend})


def _hook_plugin_zip(plugin_id: str) -> bytes:
    """Plugin that registers startup/shutdown/uninstall hooks
    each writing a marker file under WORKING_DIR.
    """
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "class _HookPlugin:\n"
        "    def register(self, api):\n"
        "        api.register_startup_hook(\n"
        '            hook_name="mark_started",\n'
        "            callback=self._on_start,\n"
        "        )\n"
        "        api.register_shutdown_hook(\n"
        '            hook_name="mark_stopped",\n'
        "            callback=self._on_stop,\n"
        "        )\n"
        "        api.register_uninstall_hook(\n"
        '            hook_name="mark_uninstalled",\n'
        "            callback=self._on_uninstall,\n"
        "        )\n"
        "\n"
        "    async def _on_start(self):\n"
        "        marker = Path(os.environ.get('QWENPAW_WORKING_DIR', '.'))\n"
        f'        (marker / "{plugin_id}.startup").touch()\n'
        "\n"
        "    async def _on_stop(self):\n"
        "        marker = Path(os.environ.get('QWENPAW_WORKING_DIR', '.'))\n"
        f'        (marker / "{plugin_id}.shutdown").touch()\n'
        "\n"
        "    async def _on_uninstall(self, **kwargs):\n"
        "        marker = Path(os.environ.get('QWENPAW_WORKING_DIR', '.'))\n"
        f'        (marker / "{plugin_id}.uninstall").touch()\n'
        "\n"
        "\n"
        "plugin = _HookPlugin()\n"
    )
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "hook",
        "entry": {"backend": "plugin.py"},
        "meta": {"hook_type": "startup"},
    }
    return _build_zip(plugin_id, manifest, {"plugin.py": backend})


def _command_plugin_zip(plugin_id: str) -> bytes:
    """Plugin that registers a /slash control command."""
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "from qwenpaw.app.runner.control_commands.base import (\n"
        "    BaseControlCommandHandler,\n"
        ")\n"
        "\n"
        "\n"
        "class _MyCommand(BaseControlCommandHandler):\n"
        f'    command_name = "/{plugin_id}-cmd"\n'
        '    description = "Test command"\n'
        "\n"
        "    async def handle(self, context):\n"
        f'        return "ok-from-{plugin_id}"\n'
        "\n"
        "\n"
        "class _CommandPlugin:\n"
        "    def register(self, api):\n"
        "        api.register_control_command(\n"
        "            handler=_MyCommand(),\n"
        "            priority_level=0,\n"
        "        )\n"
        "\n"
        "\n"
        "plugin = _CommandPlugin()\n"
    )
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "command",
        "entry": {"backend": "plugin.py"},
        "meta": {"command_name": f"/{plugin_id}-cmd"},
    }
    return _build_zip(plugin_id, manifest, {"plugin.py": backend})


def _http_router_plugin_zip(plugin_id: str) -> bytes:
    """Plugin that registers a FastAPI APIRouter at a custom prefix."""
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "from fastapi import APIRouter\n"
        "\n"
        "router = APIRouter()\n"
        "\n"
        "\n"
        '@router.get("/ping")\n'
        "async def _ping():\n"
        f'    return {{"ok": True, "from": "{plugin_id}"}}\n'
        "\n"
        "\n"
        "class _HttpPlugin:\n"
        "    def register(self, api):\n"
        "        api.register_http_router(\n"
        "            router=router,\n"
        f'            prefix="/{plugin_id}",\n'
        f'            tags=["{plugin_id}"],\n'
        "        )\n"
        "\n"
        "\n"
        "plugin = _HttpPlugin()\n"
    )
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "general",
        "entry": {"backend": "plugin.py"},
    }
    return _build_zip(plugin_id, manifest, {"plugin.py": backend})


def _frontend_plugin_zip(plugin_id: str) -> bytes:
    """Plugin that ships only a frontend bundle."""
    js_bundle = (
        f"// {plugin_id} mock frontend bundle\n"
        f'console.log("loaded {plugin_id}");\n'
    )
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "class _FrontendPlugin:\n"
        "    def register(self, api):\n"
        "        pass\n"
        "\n"
        "\n"
        "plugin = _FrontendPlugin()\n"
    )
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "frontend",
        "entry": {
            "backend": "plugin.py",
            "frontend": "dist/index.js",
        },
    }
    return _build_zip(
        plugin_id,
        manifest,
        {"plugin.py": backend, "dist/index.js": js_bundle},
    )


# ------------------------------------------------------------------ #
# generic upload + delete helpers (copied from test_plugins.py)
# ------------------------------------------------------------------ #


def _upload(app_server, plugin_id: str, zip_bytes: bytes):
    kwargs: dict[str, Any] = {
        "files": {
            "file": (f"{plugin_id}.zip", zip_bytes, "application/zip"),
        },
        "timeout": PLUGIN_HTTP_TIMEOUT,
    }
    deadline = time.time() + LOADER_READY_TIMEOUT
    while True:
        wait_until_plugin_loader_ready(app_server)
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/upload",
                **kwargs,
            )
        except httpx.TimeoutException:
            if time.time() >= deadline:
                raise
            time.sleep(0.5)
            continue
        if resp.status_code != 503 or time.time() >= deadline:
            return resp
        time.sleep(0.5)


def _delete(app_server, plugin_id: str) -> None:
    try:
        deadline = time.time() + LOADER_READY_TIMEOUT
        while True:
            wait_until_plugin_loader_ready(app_server)
            resp = app_server.api_request(
                "DELETE",
                f"/api/plugins/{plugin_id}",
                timeout=PLUGIN_HTTP_TIMEOUT,
            )
            if resp.status_code != 503 or time.time() >= deadline:
                return
            time.sleep(0.5)
    except Exception:
        pass


def _loaded_ids(app_server) -> set[str]:
    resp = app_server.api_request(
        "GET",
        "/api/plugins",
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    items = (
        payload if isinstance(payload, list) else payload.get("plugins", [])
    )
    return {
        str(item["id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


# ------------------------------------------------------------------ #
# A. Provider plugin (3 cases)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_provider_plugin_install_loads(app_server) -> None:
    """Test purpose:
    - Verify a Provider-type plugin uploads, loads, and appears in the
      loaded plugin list.

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/plugins
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-provider-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _provider_plugin_zip(pid))
        assert (
            resp.status_code == 200
        ), f"upload failed: {resp.text} | {app_server.logs_tail()}"
        body = resp.json()
        assert body.get("loaded") is True, body
        assert body.get("id") == pid, body
        assert pid in _loaded_ids(app_server)
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p1
def test_provider_plugin_registers_provider(app_server) -> None:
    """Test purpose:
    - Verify a Provider-type plugin actually appends its provider to
      GET /api/models so the console can render the new option.

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/models
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-provider-registers"
    expected_provider_id = f"{pid}-prov"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _provider_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        # GET /api/models should now contain our provider id.
        models_resp = app_server.api_request(
            "GET",
            "/api/models",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert models_resp.status_code == 200, app_server.logs_tail()
        provider_ids = {p.get("id") for p in models_resp.json()}
        assert (
            expected_provider_id in provider_ids
        ), f"provider not registered: {provider_ids}"
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p2
def test_provider_plugin_uninstall_removes_provider(app_server) -> None:
    """Test purpose:
    - Verify uninstalling the plugin removes its provider from
      GET /api/models.

    API endpoints:
    - POST /api/plugins/upload
    - DELETE /api/plugins/{plugin_id}
    - GET /api/models
    """
    pid = "integ-provider-uninstall"
    expected_provider_id = f"{pid}-prov"
    _delete(app_server, pid)
    resp = _upload(app_server, pid, _provider_plugin_zip(pid))
    assert resp.status_code == 200, app_server.logs_tail()

    _delete(app_server, pid)

    models_resp = app_server.api_request(
        "GET",
        "/api/models",
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert models_resp.status_code == 200, app_server.logs_tail()
    provider_ids = {p.get("id") for p in models_resp.json()}
    assert (
        expected_provider_id not in provider_ids
    ), f"provider not removed: {provider_ids}"


# ------------------------------------------------------------------ #
# A4: provider plugin really used by agent (end-to-end LLM call)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_provider_plugin_actually_serves_llm_call(app_server) -> None:
    """Test purpose:
    - Verify a Provider-type plugin's provider is *really* selectable
      and an agent run actually sends a request to it (not just listed).

    Test flow:
    1. Spin up a MockLLMHandler (OpenAI-compatible).
    2. Upload provider plugin.
    3. PUT /api/models/{prov-id}/config to redirect base_url to mock URL,
       set api_key.
    4. POST /api/models/{prov-id}/models to add a "mock-model" entry.
    5. PUT /api/models/active to set the plugin provider as active.
    6. Trigger an agent-type cron run.
    7. Assert mock server's request_count > 0 (LLM was actually called)
       and history status == success.

    API endpoints exercised end-to-end:
    - POST /api/plugins/upload
    - PUT  /api/models/{provider_id}/config
    - POST /api/models/{provider_id}/models
    - PUT  /api/models/active
    - POST /api/cron/jobs
    - POST /api/cron/jobs/{job_id}/run
    - DELETE /api/plugins/{plugin_id}
    """
    import threading
    from http.server import HTTPServer

    from helpers import MockLLMHandler

    pid = "integ-provider-real-call"
    prov_id = f"{pid}-prov"

    # Spin up mock LLM.
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    srv.request_count = 0
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    mock_url = f"http://127.0.0.1:{port}/v1"

    _delete(app_server, pid)

    job_id = None
    try:
        # Upload plugin.
        resp = _upload(app_server, pid, _provider_plugin_zip(pid))
        assert (
            resp.status_code == 200
        ), f"upload failed: {resp.text} | {app_server.logs_tail()}"

        # Redirect plugin provider's base_url to mock LLM.
        cfg_resp = app_server.api_request(
            "PUT",
            f"/api/models/{prov_id}/config",
            json={"api_key": "test-key", "base_url": mock_url},
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert cfg_resp.status_code == 200, app_server.logs_tail()

        # Add a model entry.
        add_model_resp = app_server.api_request(
            "POST",
            f"/api/models/{prov_id}/models",
            json={
                "id": "mock-model",
                "name": "Mock Model",
            },
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert add_model_resp.status_code in {200, 201}, app_server.logs_tail()

        # Set active.
        active_resp = app_server.api_request(
            "PUT",
            "/api/models/active",
            json={
                "provider_id": prov_id,
                "model": "mock-model",
                "scope": "global",
            },
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert active_resp.status_code == 200, app_server.logs_tail()

        # Trigger cron agent run.
        spec = {
            "name": pid,
            "enabled": True,
            "schedule": {
                "type": "cron",
                "cron": "0 0 1 1 *",
                "timezone": "UTC",
            },
            "task_type": "agent",
            "request": {
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [{"type": "text", "text": "ping"}],
                    },
                ],
            },
            "dispatch": {
                "type": "channel",
                "channel": "console",
                "target": {
                    "user_id": pid,
                    "session_id": f"console:{pid}",
                },
                "mode": "stream",
            },
            "save_result_to_inbox": False,
        }
        job_resp = app_server.api_request(
            "POST",
            "/api/cron/jobs",
            json=spec,
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert job_resp.status_code == 200, app_server.logs_tail()
        job_id = job_resp.json()["id"]

        run_resp = app_server.api_request(
            "POST",
            f"/api/cron/jobs/{job_id}/run",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert run_resp.status_code == 200, app_server.logs_tail()

        # Poll history.
        deadline = time.time() + 30.0
        records: list = []
        while time.time() < deadline:
            hist_resp = app_server.api_request(
                "GET",
                f"/api/cron/jobs/{job_id}/history",
                timeout=PLUGIN_HTTP_TIMEOUT,
            )
            if hist_resp.status_code == 200:
                records = hist_resp.json()
                if isinstance(records, list) and records:
                    break
            time.sleep(1.0)
        assert records, app_server.logs_tail()
        assert (
            records[0]["status"] == "success"
        ), f"cron failed: {records[0]} | {app_server.logs_tail()}"

        # Mock server must have received the request.
        assert (
            srv.request_count > 0
        ), f"plugin provider not actually used: {app_server.logs_tail()}"
    finally:
        if job_id:
            try:
                app_server.api_request(
                    "DELETE",
                    f"/api/cron/jobs/{job_id}",
                    timeout=PLUGIN_HTTP_TIMEOUT,
                )
            except Exception:
                pass
        _delete(app_server, pid)
        srv.shutdown()


# ------------------------------------------------------------------ #
# B. Hook plugin (3 cases)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_hook_plugin_install_loads(app_server) -> None:
    """Test purpose:
    - Verify a hook-type plugin uploads, loads, and the loaded plugin
      list contains it.

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/plugins
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-hook-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _hook_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()
        assert pid in _loaded_ids(app_server)
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p0
def test_hook_plugin_startup_hook_actually_fires(app_server) -> None:
    """Test purpose:
    - Verify the plugin's startup hook is *really* invoked on hot-install
      by asserting the marker file ``<plugin_id>.startup`` exists under
      WORKING_DIR.

    Test flow:
    1. Upload the hook plugin (POST /api/plugins/upload).
    2. Wait briefly for hot-install startup hook execution.
    3. Assert the startup marker file exists at
       ``app_server.working_dir / "<plugin_id>.startup"``.
    """
    pid = "integ-hook-startup-fire"
    _delete(app_server, pid)
    marker = app_server.working_dir / f"{pid}.startup"
    if marker.exists():
        marker.unlink()
    try:
        resp = _upload(app_server, pid, _hook_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        # Hot-install runs startup hooks synchronously inside the route;
        # the marker should already exist when the response returns.
        deadline = time.time() + 5.0
        while time.time() < deadline and not marker.exists():
            time.sleep(0.2)
        assert (
            marker.exists()
        ), f"startup marker missing: {marker} | {app_server.logs_tail()}"
    finally:
        _delete(app_server, pid)
        if marker.exists():
            marker.unlink()


@pytest.mark.integration
@pytest.mark.p1
def test_hook_plugin_uninstall_hook_actually_fires(app_server) -> None:
    """Test purpose:
    - Verify the plugin's uninstall hook is *really* invoked when the
      plugin is removed via DELETE /api/plugins/{plugin_id}.

    Test flow:
    1. Upload hook plugin.
    2. DELETE the plugin.
    3. Assert ``<plugin_id>.uninstall`` marker exists under WORKING_DIR.
    """
    pid = "integ-hook-uninstall-fire"
    _delete(app_server, pid)
    marker = app_server.working_dir / f"{pid}.uninstall"
    if marker.exists():
        marker.unlink()
    try:
        resp = _upload(app_server, pid, _hook_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        # Trigger uninstall — uninstall hook should write the marker.
        del_resp = app_server.api_request(
            "DELETE",
            f"/api/plugins/{pid}",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()

        deadline = time.time() + 5.0
        while time.time() < deadline and not marker.exists():
            time.sleep(0.2)
        assert (
            marker.exists()
        ), f"uninstall marker missing: {marker} | {app_server.logs_tail()}"
    finally:
        if marker.exists():
            marker.unlink()


# ------------------------------------------------------------------ #
# C. Command plugin (2 cases)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_command_plugin_install_loads(app_server) -> None:
    """Test purpose:
    - Verify a Command-type plugin uploads, loads, and the loaded
      plugin list contains it.

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/plugins
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-command-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _command_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()
        assert pid in _loaded_ids(app_server)
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p0
def test_command_plugin_command_actually_registered(app_server) -> None:
    """Test purpose:
    - Verify the plugin's slash command is *really* registered in the
      app's CommandRegistry by inspecting server logs for the
      'Registered plugin control command' message.

    Test flow:
    1. Upload command plugin.
    2. Read app_server.logs_tail() — must contain
       'Registered plugin control command: /<plugin_id>-cmd'.
    3. Cleanup.
    """
    pid = "integ-command-real-register"
    expected_cmd = f"/{pid}-cmd"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _command_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        logs = app_server.logs_tail(8000)
        # Look for either the registration log line or the
        # CommandRegistry confirmation. Both should be present.
        assert expected_cmd in logs, (
            f"command '{expected_cmd}' not in server logs:\n" f"{logs[-2000:]}"
        )
        # Stronger check: explicit registration confirmation.
        assert (
            "Registered plugin control command" in logs
            or "Registered command:" in logs
        ), f"no registration log found:\n{logs[-2000:]}"
    finally:
        _delete(app_server, pid)


# ------------------------------------------------------------------ #
# D. HTTP API plugin (3 cases)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_http_router_plugin_install_loads(app_server) -> None:
    """Test purpose:
    - Verify an HTTP-router plugin uploads, loads, and the loaded
      plugin list contains it.

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/plugins
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-http-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _http_router_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()
        assert pid in _loaded_ids(app_server)
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p0
def test_http_router_plugin_route_actually_serves(app_server) -> None:
    """Test purpose:
    - Verify the plugin's APIRouter is *really* mounted: GET on the
      registered prefix returns 200 with the expected body.

    Test flow:
    1. Upload http-router plugin (plugin registers /api/<pid>/ping).
    2. GET /api/<pid>/ping → 200, body contains pid as 'from'.
    3. Cleanup.

    API endpoints exercised end-to-end:
    - POST /api/plugins/upload
    - GET  /api/<plugin_id>/ping (plugin-mounted)
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-http-real-route"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _http_router_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        # The plugin mounted /api/{pid}/ping during register().
        ping_resp = app_server.api_request(
            "GET",
            f"/api/{pid}/ping",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert ping_resp.status_code == 200, (
            f"plugin route not mounted: {ping_resp.status_code} | "
            f"{ping_resp.text} | {app_server.logs_tail()}"
        )
        body = ping_resp.json()
        assert body.get("ok") is True, body
        assert body.get("from") == pid, body
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p1
def test_http_router_plugin_uninstall_removes_route(app_server) -> None:
    """Test purpose:
    - Verify uninstalling the plugin removes its mounted route. After
      DELETE the GET should return 404 (or 503/clean unmount).

    Test flow:
    1. Upload http-router plugin, verify GET /api/<pid>/ping = 200.
    2. DELETE the plugin.
    3. GET /api/<pid>/ping again — must be 404.
    """
    pid = "integ-http-uninstall-route"
    _delete(app_server, pid)
    resp = _upload(app_server, pid, _http_router_plugin_zip(pid))
    assert resp.status_code == 200, app_server.logs_tail()

    # Verify route exists.
    pre_resp = app_server.api_request(
        "GET",
        f"/api/{pid}/ping",
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert pre_resp.status_code == 200, app_server.logs_tail()

    # Uninstall.
    _delete(app_server, pid)

    # Route should now 404.
    post_resp = app_server.api_request(
        "GET",
        f"/api/{pid}/ping",
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert (
        post_resp.status_code == 404
    ), f"route not removed: {post_resp.status_code} | {post_resp.text}"


# ------------------------------------------------------------------ #
# E. Frontend plugin (2 cases)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_frontend_plugin_install_appears_in_public_list(app_server) -> None:
    """Test purpose:
    - Verify a frontend plugin uploads, loads, and the *public*
      GET /api/frontend_plugin endpoint lists it (so the login page
      can pick it up before authentication).

    API endpoints:
    - POST /api/plugins/upload
    - GET  /api/frontend_plugin (public)
    - DELETE /api/plugins/{plugin_id}
    """
    pid = "integ-frontend-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _frontend_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        list_resp = app_server.api_request(
            "GET",
            "/api/frontend_plugin",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        body = list_resp.json()
        items = body if isinstance(body, list) else body.get("plugins", [])
        ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
        assert pid in ids, f"frontend plugin not in public list: {ids}"
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p0
def test_frontend_plugin_static_file_actually_served(app_server) -> None:
    """Test purpose:
    - Verify the plugin's frontend bundle is *really* served via
      GET /api/frontend_plugin/{pid}/files/dist/index.js — the JS file
      content matches what the plugin shipped.

    Test flow:
    1. Upload frontend plugin (ships a 'dist/index.js' under the zip).
    2. GET /api/frontend_plugin/<pid>/files/dist/index.js → 200.
    3. Response body must contain '<pid> mock frontend bundle'.
    """
    pid = "integ-frontend-real-serve"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _frontend_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        file_resp = app_server.api_request(
            "GET",
            f"/api/frontend_plugin/{pid}/files/dist/index.js",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert file_resp.status_code == 200, (
            f"frontend file not served: {file_resp.status_code} | "
            f"{file_resp.text} | {app_server.logs_tail()}"
        )
        text = file_resp.text
        assert (
            f"{pid} mock frontend bundle" in text
        ), f"unexpected file content: {text[:200]}"
    finally:
        _delete(app_server, pid)


# ------------------------------------------------------------------ #
# F. Composite + error paths (2 cases)
# ------------------------------------------------------------------ #


def _composite_plugin_zip(plugin_id: str) -> bytes:
    """Plugin shipping BOTH a backend HTTP route AND a frontend bundle."""
    backend = (
        "# -*- coding: utf-8 -*-\n"
        "from fastapi import APIRouter\n"
        "\n"
        "router = APIRouter()\n"
        "\n"
        "\n"
        '@router.get("/info")\n'
        "async def _info():\n"
        f'    return {{"id": "{plugin_id}", "kind": "composite"}}\n'
        "\n"
        "\n"
        "class _CompositePlugin:\n"
        "    def register(self, api):\n"
        "        api.register_http_router(\n"
        "            router=router,\n"
        f'            prefix="/{plugin_id}",\n'
        f'            tags=["{plugin_id}"],\n'
        "        )\n"
        "\n"
        "\n"
        "plugin = _CompositePlugin()\n"
    )
    js_bundle = f"// {plugin_id} composite frontend\n"
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "general",
        "entry": {
            "backend": "plugin.py",
            "frontend": "dist/index.js",
        },
    }
    return _build_zip(
        plugin_id,
        manifest,
        {"plugin.py": backend, "dist/index.js": js_bundle},
    )


def _no_entry_plugin_zip(plugin_id: str) -> bytes:
    """Manifest without any entry point — should be rejected by loader."""
    manifest = {
        "id": plugin_id,
        "version": "0.1.0",
        "name": plugin_id,
        "plugin_type": "general",
        "entry": {},  # empty — no backend nor frontend
    }
    return _build_zip(plugin_id, manifest, {})


@pytest.mark.integration
@pytest.mark.p1
def test_composite_plugin_backend_and_frontend_both_live(app_server) -> None:
    """Test purpose:
    - Verify a plugin shipping BOTH backend (HTTP router) and frontend
      (static bundle) has both entries live after install:
      * GET /api/<pid>/info returns 200 with the expected body
      * GET /api/frontend_plugin/<pid>/files/dist/index.js returns 200

    Test flow:
    1. Upload composite plugin.
    2. Hit the backend route — assert 200 and payload.
    3. Hit the frontend static file — assert 200 and content.
    4. Cleanup.
    """
    pid = "integ-composite-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _composite_plugin_zip(pid))
        assert resp.status_code == 200, app_server.logs_tail()

        # Backend route check.
        info_resp = app_server.api_request(
            "GET",
            f"/api/{pid}/info",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert info_resp.status_code == 200, app_server.logs_tail()
        body = info_resp.json()
        assert body.get("id") == pid, body
        assert body.get("kind") == "composite", body

        # Frontend static file check.
        js_resp = app_server.api_request(
            "GET",
            f"/api/frontend_plugin/{pid}/files/dist/index.js",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert js_resp.status_code == 200, app_server.logs_tail()
        assert f"{pid} composite frontend" in js_resp.text, js_resp.text[:200]
    finally:
        _delete(app_server, pid)


@pytest.mark.integration
@pytest.mark.p2
def test_plugin_upload_rejects_manifest_without_entry(app_server) -> None:
    """Test purpose:
    - Verify the loader rejects a manifest with no entry points
      (entry.backend and entry.frontend both empty/missing) — should
      return 400 with a descriptive error so users get a clear hint.

    Test flow:
    1. Upload a malformed plugin (empty entry).
    2. Assert response status is 400 and detail mentions 'entry points'
       or similar.
    """
    pid = "integ-no-entry-plugin"
    _delete(app_server, pid)
    try:
        resp = _upload(app_server, pid, _no_entry_plugin_zip(pid))
        assert (
            resp.status_code == 400
        ), f"expected 400, got {resp.status_code}: {resp.text}"
        detail = (resp.json() or {}).get("detail", "").lower()
        assert (
            "entry" in detail or "no" in detail or "manifest" in detail
        ), f"error detail not informative: {detail}"
    finally:
        _delete(app_server, pid)
