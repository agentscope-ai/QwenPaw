# -*- coding: utf-8 -*-
"""Test real plugin routes with a deterministic native peer."""

# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from record_replay.session_store import RecordingStore
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord

PLUGIN_DIR = (
    Path(__file__).resolve().parents[3] / "plugins/bundle/record-and-replay"
)


@pytest.fixture
def setup_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    fixtures = importlib.import_module("test_event_stream_recorder")
    spec = importlib.util.spec_from_file_location(
        "record_replay_test_plugin",
        PLUGIN_DIR / "plugin.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        AsyncMock(
            return_value=SimpleNamespace(
                workspace_dir=str(workspace),
                agent_id="agent",
            ),
        ),
    )
    clients = []

    def factory():
        client = fixtures._FakeClient(tmp_path / "staging")
        clients.append(client)
        return module.DesktopRecordingService(
            event_stream_recorder=module.EventStreamDesktopRecorder(
                client,
                ingestor=fixtures._FakeIngestor(),
            ),
        )

    plugin = module.RecordAndReplayPlugin(tmp_path / "feature.json", factory)
    app = FastAPI()
    registry = PluginRegistry()
    registry.set_plugin_http_app(app)
    api = PluginApi("record-and-replay", {})
    api.set_registry(registry)
    plugin.register(api)
    return SimpleNamespace(
        plugin=plugin,
        module=module,
        app=app,
        registry=registry,
        clients=clients,
        workspace=workspace,
        path=tmp_path / "feature.json",
    )


def http_client(setup):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_disable_closes_capture_and_renews_lifetime(
    setup_plugin,
):
    setup = setup_plugin
    async with http_client(setup) as client:
        assert (await client.get("/api/desktop/recording")).status_code == 200
        started = await client.post("/api/desktop/recording/start")
        assert started.status_code == 200
        recording_id = started.json()["recording"]["recording_id"]
        await client.post("/api/desktop/recording/pause")
        old = setup.clients[-1]
        off = await client.put(
            "/api/desktop/recording/feature",
            json={"enabled": False},
        )
        assert off.json()["enabled"] is False
        assert old.closed and "event_stream.cancel" in old.calls
        assert (
            RecordingStore(setup.workspace).get(recording_id).state.value
            == "interrupted"
        )
        assert (
            await client.post("/api/desktop/recording/start")
        ).status_code == 403
        assert (
            await client.post(
                "/api/desktop/recording/learn/generate",
                json={
                    "consent_token": "00000000-0000-0000-0000-000000000000",
                    "consent": True,
                },
            )
        ).status_code == 403
        await client.put(
            "/api/desktop/recording/feature",
            json={"enabled": True},
        )
        assert setup.clients[-1] is not old
        assert (
            await client.post("/api/desktop/recording/start")
        ).status_code == 200
        assert (
            await client.post("/api/desktop/recording/stop")
        ).status_code == 200
    await setup.plugin.close()


@pytest.mark.asyncio
async def test_loader_unload_removes_owned_routes(
    setup_plugin,
):
    setup = setup_plugin
    other = APIRouter()
    other.add_api_route("/status", lambda: {"act": True})
    setup.registry.register_http_router("other", other, prefix="/other")
    marker = setup.workspace / "skills" / "existing" / "SKILL.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("existing user skill", encoding="utf-8")
    loader = PluginLoader([])
    loader.registry = setup.registry
    manifest = PluginManifest.model_validate_json(
        (PLUGIN_DIR / "plugin.json").read_text(),
    )
    assert manifest.dependencies == []
    loader._loaded_plugins[manifest.id] = PluginRecord(
        manifest,
        PLUGIN_DIR,
        True,
        setup.plugin,
    )
    async with http_client(setup) as client:
        await client.post("/api/desktop/recording/start")
        await loader.unload_plugin(manifest.id, delete_files=False)
        assert (await client.get("/api/desktop/recording")).status_code == 404
        assert (await client.get("/api/other/status")).status_code == 200
    assert setup.clients[-1].closed
    assert marker.read_text() == "existing user skill"
    assert PLUGIN_DIR.is_dir()


@pytest.mark.asyncio
async def test_disable_cancels_inflight_learn_request(
    setup_plugin,
):
    setup = setup_plugin
    entered = asyncio.Event()

    async def blocked(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    setup.plugin._learning.generate = blocked
    async with http_client(setup) as client:
        pending = asyncio.create_task(
            client.post(
                "/api/desktop/recording/learn/generate",
                json={
                    "consent_token": "00000000-0000-0000-0000-000000000000",
                    "consent": True,
                },
            ),
        )
        await asyncio.wait_for(entered.wait(), 2)
        await client.put(
            "/api/desktop/recording/feature",
            json={"enabled": False},
        )
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert setup.plugin._requests == set()
        assert setup.clients[-1].closed
        assert (await client.get("/api/desktop/recording")).status_code == 403


@pytest.mark.asyncio
async def test_preference_persists_but_shutdown_does_not_change_it(
    setup_plugin,
):
    setup = setup_plugin
    await setup.plugin.set_enabled(False)
    assert json.loads(setup.path.read_text()) == {"enabled": False}
    await setup.plugin.close()
    assert json.loads(setup.path.read_text()) == {"enabled": False}
    api = PluginApi("reloaded-record", {})
    registry = PluginRegistry()
    registry.unregister_plugin("record-and-replay")
    registry.set_plugin_http_app(FastAPI())
    api.set_registry(registry)
    reloaded = setup.module.RecordAndReplayPlugin(setup.path)
    reloaded.register(api)
    assert reloaded.feature_status()["enabled"] is False
    assert reloaded._service is None


@pytest.mark.asyncio
async def test_unavailable_runtime_does_not_create_legacy_fallback(
    setup_plugin,
):
    setup = setup_plugin
    setup.clients[-1].available = AsyncMock(return_value=False)
    async with http_client(setup) as client:
        status = await client.get("/api/desktop/recording")
        assert (
            status.status_code == 200 and status.json()["available"] is False
        )
        assert (
            await client.post("/api/desktop/recording/start")
        ).status_code == 503
    assert setup.clients[-1].calls == []
    assert not setup.workspace.exists()


@pytest.mark.asyncio
async def test_platform_and_strict_feature_input_fail_closed(setup_plugin):
    setup = setup_plugin
    setup.module.sys.platform = "linux"
    async with http_client(setup) as client:
        assert (await client.get("/api/desktop/recording/feature")).json()[
            "supported_platform"
        ] is False
        assert (
            await client.post("/api/desktop/recording/start")
        ).status_code == 503
        assert (
            await client.put(
                "/api/desktop/recording/feature",
                json={"enabled": "true"},
            )
        ).status_code == 422
    assert setup.clients[-1].calls == []


@pytest.mark.asyncio
async def test_disable_blocks_a_start_waiting_for_workspace_resolution(
    setup_plugin,
    monkeypatch,
):
    setup = setup_plugin
    entered = asyncio.Event()

    async def waiting_workspace(_request):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_agent_for_request",
        waiting_workspace,
    )
    async with http_client(setup) as client:
        start = asyncio.create_task(
            client.post("/api/desktop/recording/start"),
        )
        await asyncio.wait_for(entered.wait(), 2)
        await client.put(
            "/api/desktop/recording/feature",
            json={"enabled": False},
        )
        with pytest.raises(asyncio.CancelledError):
            await start
    assert setup.clients[-1].calls == []
    assert not setup.workspace.exists()


@pytest.mark.asyncio
async def test_shutdown_preserves_enabled_preference(setup_plugin):
    setup = setup_plugin
    await setup.plugin.set_enabled(True)
    await setup.plugin.close()
    assert json.loads(setup.path.read_text()) == {"enabled": True}
    with pytest.raises(Exception) as error:
        await setup.plugin.set_enabled(True)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_corrupt_preference_starts_disabled(setup_plugin):
    setup = setup_plugin
    await setup.plugin.close()
    setup.registry.unregister_plugin("record-and-replay")
    setup.path.write_text("[invalid", encoding="utf-8")
    plugin = setup.module.RecordAndReplayPlugin(setup.path)
    api = PluginApi("record-and-replay", {})
    api.set_registry(setup.registry)
    plugin.register(api)
    assert plugin.feature_status()["enabled"] is False
    assert plugin._service is None


@pytest.mark.asyncio
async def test_disable_save_failure_still_closes_native_and_denies_calls(
    setup_plugin,
    monkeypatch,
):
    setup = setup_plugin
    monkeypatch.setattr(
        setup.module,
        "write_text_atomic_async",
        AsyncMock(side_effect=OSError("test disk failure")),
    )
    async with http_client(setup) as client:
        await client.post("/api/desktop/recording/start")
        response = await client.put(
            "/api/desktop/recording/feature",
            json={"enabled": False},
        )
        assert response.status_code == 503
        assert (await client.get("/api/desktop/recording")).status_code == 403
    assert setup.clients[-1].closed
