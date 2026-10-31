# -*- coding: utf-8 -*-
"""Sidecar availability must not remove a PawApp's diagnostic routes."""

import asyncio
from dataclasses import replace
import signal
import sys
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.routers.pawapps import router as pawapps_router
from qwenpaw.pawapp import PawApp
from qwenpaw.pawapp import ManagedService, ManagedServiceSpec
from qwenpaw.pawapp import service as service_module
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins import custody
from qwenpaw.plugins.lifecycle import UnloadMode
from qwenpaw.plugins.loader import PluginLoader

from .timing import WAIT_TIMEOUT


def _fixture_plugin(tmp_path, registry, declaration):
    root = tmp_path / "service-fixture"
    root.mkdir()
    manifest = PluginManifest.from_dict(
        {
            "id": "service-fixture",
            "name": "Fixture",
            "version": "1.0.0",
            "entry": {"backend": "main.py"},
            "meta": {"pawapp": {"entry_page": "/apps/service-fixture"}},
        },
    )
    (root / "plugin.json").write_text(manifest.model_dump_json())
    (root / "main.py").write_text(
        "from qwenpaw.pawapp import PawApp\n"
        'plugin = PawApp("Fixture", app_id="service-fixture")\n'
        "plugin.enable_standard_capabilities()\n" + declaration,
    )
    loader = PluginLoader([tmp_path])
    loader.registry = registry
    app = FastAPI()
    app.state.plugin_registry = registry
    app.include_router(pawapps_router, prefix="/api")
    registry.set_plugin_http_app(app)

    @app.get("/{path:path}", name="qwenpaw_console_spa_catchall")
    def fallback(path: str):
        return {"path": path}

    return loader, app, manifest, root


# Older Datapaw's gateway only catches HTTP transport failures, and its
# startup reconciliation only catches HTTPException. Preserve that contract.
_LEGACY_DATAPAW_STARTUP = """
import httpx
from fastapi import HTTPException

class LegacyGateway:
    async def send(self):
        try:
            async with httpx.AsyncClient() as client:
                return await client.get(
                    f'{service.base_url}/api/v1/cm/datasources',
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise HTTPException(503, 'Context service is unavailable') from exc

gateway = LegacyGateway()

@plugin.hook('startup', priority=100)
async def reconcile_sources():
    try:
        await gateway.send()
    except HTTPException:
        return

@plugin.route('/context', methods=['GET'])
async def context():
    await gateway.send()
"""


@pytest.mark.asyncio
async def test_legacy_datapaw_followup_keeps_app_and_returns_unavailable(
    tmp_path,
    fresh_registry,
):
    declaration = (
        "service = plugin.managed_service('context', "
        f"command=({str(tmp_path / 'missing-python')!r},))\n"
        + _LEGACY_DATAPAW_STARTUP
    )
    loader, app, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    try:
        record = await loader.load_plugin(manifest, root)
        assert record.status == "active"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://fixture",
        ) as client:
            diagnostic = await client.get(
                "/api/service-fixture/dependencies/context?force=true",
            )
            unavailable = await client.get("/api/service-fixture/context")
            applications = await client.get("/api/pawapps")
        assert diagnostic.status_code == 200
        assert diagnostic.json()["error_code"] == "RUNTIME_MISSING"
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "RUNTIME_MISSING"
        assert str(tmp_path) not in unavailable.text
        assert applications.status_code == 200
        assert any(
            entry["id"] == manifest.id for entry in applications.json()["apps"]
        )
    finally:
        report = await loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD)
        assert report.clean and report.quiescent


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
@pytest.mark.parametrize("failure", ["runtime", "health"])
async def test_unavailable_sidecar_keeps_app_routes(
    tmp_path,
    fresh_registry,
    monkeypatch,
    required,
    failure,
):
    monkeypatch.setattr(service_module, "_health_request", lambda *_: False)
    if failure == "health":
        monkeypatch.setenv("SERVICE_FIXTURE_MODE", "external")
        monkeypatch.setenv("SERVICE_FIXTURE_URL", "http://127.0.0.1:9123")
    declaration = (
        "service = plugin.managed_service('context', "
        f"command=({str(tmp_path / 'missing-python')!r},), "
        "mode_env='SERVICE_FIXTURE_MODE', "
        "external_url_env='SERVICE_FIXTURE_URL', "
        f"required={required!r}, startup_timeout=0.01, "
        "runtime_remediation='Prepare the isolated context runtime')\n"
    )
    loader, app, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    try:
        record = await loader.load_plugin(manifest, root)
        assert record.status == "active"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://fixture",
        ) as client:
            chat = await client.post("/api/service-fixture/chat", json={})
            response = await client.get(
                "/api/service-fixture/dependencies/context?force=true",
            )
        assert chat.status_code == 400
        assert chat.json()["detail"] == "message is required"
        assert response.status_code == 200
        status = response.json()
        assert status["required"] is required
        assert status["health"] == "unavailable"
        assert str(tmp_path) not in status["message"]
        assert status["remediation"] == "Prepare the isolated context runtime"
        if failure == "runtime":
            assert status["error_code"] == "RUNTIME_MISSING"
        else:
            assert "healthy" in status["message"]
    finally:
        report = await loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD)
        assert report.clean and report.quiescent


@pytest.mark.asyncio
async def test_before_start_bug_still_fails_plugin(tmp_path, fresh_registry):
    declaration = (
        "async def broken_setup():\n"
        "    raise RuntimeError('setup programming bug')\n"
        "service = plugin.managed_service('context', command=('missing',), "
        "on_before_start=broken_setup)\n"
    )
    loader, _, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    record = await loader.load_plugin(manifest, root)
    assert record.status == "failed"
    assert any("setup programming bug" in item for item in record.diagnostics)
    assert fresh_registry.get_http_router_registrations() == []


@pytest.mark.asyncio
async def test_cancelled_startup_stops_sidecar(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    started = asyncio.Event()

    async def wait_for_health(_service):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        service_module.ManagedService,
        "_wait_until_healthy",
        wait_for_health,
    )
    declaration = (
        "service = plugin.managed_service('context', "
        f"command=({sys.executable!r}, '-c', 'import time; time.sleep(60)'))\n"
    )
    loader, _, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    record = await loader.lifecycle.load(manifest, root, activate=False)
    assert record.status == "registered"
    assert not loader.lifecycle.get_instance(manifest.id).activated
    service = sys.modules["plugin_service_fixture"].service
    assert not service.is_ready
    activating = asyncio.create_task(loader.lifecycle.activate(manifest.id))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        process = service._process  # pylint: disable=protected-access
        activating.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(activating, timeout=10)
        assert process.returncode is not None
        assert not service.is_ready
        report = await loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD)
        assert report.clean and report.quiescent
    finally:
        activating.cancel()
        await asyncio.gather(activating, return_exceptions=True)
        if sys.exc_info()[0] is None:
            await service.stop()
        else:
            await asyncio.gather(service.stop(), return_exceptions=True)


@pytest.mark.asyncio
async def test_repaired_service_clears_startup_diagnostic(monkeypatch):
    monkeypatch.setenv("SERVICE_FIXTURE_MODE", "external")
    monkeypatch.setenv("SERVICE_FIXTURE_URL", "http://127.0.0.1:9123")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: False)
    app = PawApp("Fixture", app_id="fixture")
    service = app.managed_service(
        "context",
        command=("missing",),
        mode_env="SERVICE_FIXTURE_MODE",
        external_url_env="SERVICE_FIXTURE_URL",
        startup_timeout=5,
    )
    with pytest.raises(RuntimeError, match="not ready"):
        _ = service.base_url
    # Inject a fast startup failure without shrinking the later health probe.
    with monkeypatch.context() as failed_start:
        failed_start.setattr(
            service,
            "spec",
            replace(service.spec, startup_timeout=0.01),
        )
        with pytest.raises(TimeoutError):
            await service.start()
    assert service.startup_error is not None
    monkeypatch.setattr(service_module, "_health_request", lambda *_: True)
    try:
        await service.start()
        status = await app.dependencies.get("context", force=True)
        assert service.startup_error is None
        assert status["health"] == "healthy"
        assert status["error_code"] is None
    finally:
        await service.stop()
    with pytest.raises(RuntimeError, match="not ready"):
        _ = service.base_url


@pytest.mark.asyncio
async def test_config_update_reuses_service_safely(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setenv("SERVICE_FIXTURE_MODE", "external")
    monkeypatch.setenv("SERVICE_FIXTURE_URL", "http://127.0.0.1:9123")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: True)
    declaration = (
        "service = plugin.managed_service('context', command=('missing',), "
        "mode_env='SERVICE_FIXTURE_MODE', "
        "external_url_env='SERVICE_FIXTURE_URL')\n"
    )
    loader, _, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    record = await loader.load_plugin(manifest, root)
    service = sys.modules["plugin_service_fixture"].service
    try:
        assert record.status == "active" and service.is_ready
        report = await loader.lifecycle.update_config(
            manifest.id,
            {"value": "new"},
        )
        assert report.ok
        assert sys.modules["plugin_service_fixture"].service is service
        assert service.is_ready
        assert loader.get_loaded_plugin(manifest.id).status == "active"
    finally:
        report = await loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD)
        assert report.clean and report.quiescent


@pytest.mark.asyncio
async def test_stuck_service_close_retains_retry_and_blocks_reregister(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    released = asyncio.Event()
    calls = []

    async def blocked_close(service):
        calls.append(service)
        while not released.is_set():
            try:
                await released.wait()
            except asyncio.CancelledError:
                pass
        await service.stop()

    monkeypatch.setenv("SERVICE_FIXTURE_URL", "http://127.0.0.1:9123")
    monkeypatch.setattr(service_module, "_health_request", lambda *_: True)
    monkeypatch.setattr(service_module.ManagedService, "aclose", blocked_close)
    monkeypatch.setattr(custody, "CONNECTION_STOP_SECONDS", 0.01)
    declaration = (
        "service = plugin.managed_service('context', command=('missing',), "
        "external_url_env='SERVICE_FIXTURE_URL')\n"
    )
    loader, _, manifest, root = _fixture_plugin(
        tmp_path,
        fresh_registry,
        declaration,
    )
    await loader.load_plugin(manifest, root)
    plugin = sys.modules["plugin_service_fixture"].plugin
    service = sys.modules["plugin_service_fixture"].service
    try:
        report = await asyncio.wait_for(
            loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD),
            timeout=WAIT_TIMEOUT,
        )
        assert not report.clean and not report.quiescent
        assert len(calls) == 1
        with pytest.raises(RuntimeError, match="still closing"):
            plugin.register(MagicMock())
    finally:
        released.set()
        await asyncio.sleep(0)
        report = await loader.lifecycle.unload(manifest.id, UnloadMode.UNLOAD)
        assert report.clean and report.quiescent
        assert calls == [service]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal handling")
@pytest.mark.parametrize("interruption", ["timeout", "cancel"])
@pytest.mark.asyncio
async def test_service_close_interruption_does_not_reset_kill_deadline(
    tmp_path,
    monkeypatch,
    interruption,
):
    ready = tmp_path / "ready"

    async def await_ready(_service):
        async with asyncio.timeout(WAIT_TIMEOUT):
            while not ready.exists():
                await asyncio.sleep(0.001)

    monkeypatch.setattr(ManagedService, "_wait_until_healthy", await_ready)
    monkeypatch.setattr(custody, "CONNECTION_STOP_SECONDS", 0.01)
    service = ManagedService(
        ManagedServiceSpec(
            name="context",
            command=(
                sys.executable,
                "-c",
                "import signal,time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"Path({str(ready)!r}).write_text('ready'); time.sleep(60)",
            ),
            shutdown_timeout=0.05,
        ),
    )
    await service.start()
    process = service._process  # pylint: disable=protected-access
    terminating = asyncio.Event()
    terminate = process.terminate

    def mark_terminate():
        terminate()
        terminating.set()

    monkeypatch.setattr(process, "terminate", mark_terminate)
    closer = custody.ConnectionCloser(service, "context")
    try:
        closing = asyncio.create_task(closer())
        if interruption == "cancel":
            await asyncio.wait_for(terminating.wait(), timeout=WAIT_TIMEOUT)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
        else:
            with pytest.raises(TimeoutError):
                await closing
        assert service._process is process  # pylint: disable=protected-access
        assert (
            await asyncio.wait_for(process.wait(), timeout=WAIT_TIMEOUT)
            == -signal.SIGKILL
        )
        with pytest.raises(RuntimeError, match="close was cancelled"):
            await closer()
        await closer()
        assert service._process is None  # pylint: disable=protected-access
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await service.stop()
