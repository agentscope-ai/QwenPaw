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
    """Plugin that registers a startup hook writing a marker file."""
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
        "\n"
        "    async def _on_start(self):\n"
        "        marker = Path(os.environ.get('QWENPAW_WORKING_DIR', '.'))\n"
        f'        (marker / "{plugin_id}.startup").touch()\n'
        "\n"
        "    async def _on_stop(self):\n"
        "        marker = Path(os.environ.get('QWENPAW_WORKING_DIR', '.'))\n"
        f'        (marker / "{plugin_id}.shutdown").touch()\n'
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
        f'    name = "/{plugin_id}-cmd"\n'
        "    description = 'Test command'\n"
        "    permission_level = 0\n"
        "\n"
        "    async def execute(self, *args, **kwargs):\n"
        "        return {'ok': True}\n"
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
        f'// {plugin_id} mock frontend bundle\n'
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
                "POST", "/api/plugins/upload", **kwargs,
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
        "GET", "/api/plugins", timeout=PLUGIN_HTTP_TIMEOUT,
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
        assert resp.status_code == 200, (
            f"upload failed: {resp.text} | {app_server.logs_tail()}"
        )
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
            "GET", "/api/models", timeout=PLUGIN_HTTP_TIMEOUT,
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
        "GET", "/api/models", timeout=PLUGIN_HTTP_TIMEOUT,
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
        assert resp.status_code == 200, (
            f"upload failed: {resp.text} | {app_server.logs_tail()}"
        )

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
        assert add_model_resp.status_code in {200, 201}, (
            app_server.logs_tail()
        )

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
