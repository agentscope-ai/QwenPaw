# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Ledger teardowns, leftover scan, and reload safety."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI

from qwenpaw.plugins.api import PluginApi, _bridge_to_runtime
from qwenpaw.plugins.architecture import (
    PluginEntryPoints,
    PluginManifest,
    PluginRecord,
)
from qwenpaw.plugins.lifecycle import (
    LifecycleDelegate,
    PluginInstance,
    UnloadMode,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


@pytest.fixture()
def fresh_registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old


def _api(registry: PluginRegistry, plugin_id: str = "demo") -> PluginApi:
    api = PluginApi(plugin_id, config={}, manifest={"id": plugin_id})
    api.set_registry(registry)
    inst = PluginInstance(plugin_id)
    api.bind_instance(inst)
    return api


def _write_plugin(root: Path, plugin_id: str, body: str = "pass") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "name": plugin_id,
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        f"    def register(self, api):\n"
        f"        {body}\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.asyncio
async def test_http_and_provider_teardowns_drop_rows(fresh_registry):
    fresh_registry.set_plugin_http_app(FastAPI())
    api = _api(fresh_registry)
    router = APIRouter()
    api.register_http_router(router, prefix="/pets")
    api.register_provider("demo-llm", object, label="Demo")
    assert fresh_registry.get_http_router_registrations()
    assert "demo-llm" in fresh_registry.get_all_providers()
    leftovers = fresh_registry.leftover_registrations("demo")
    assert "http:/pets" in leftovers
    assert "provider:demo-llm" in leftovers

    await api._instance.dispose(UnloadMode.UNLOAD)
    assert fresh_registry.get_http_router_registrations() == []
    assert "demo-llm" not in fresh_registry.get_all_providers()
    assert fresh_registry.leftover_registrations("demo") == []


@pytest.mark.asyncio
async def test_plugin_api_uninstall_hook_runs_on_unload(fresh_registry):
    loader = PluginLoader(plugin_dirs=[])
    loader.registry = fresh_registry
    manifest = PluginManifest(
        id="hooked",
        name="Hooked",
        version="1.0.0",
        entry=PluginEntryPoints(backend="plugin.py"),
    )
    loader._loaded_plugins["hooked"] = PluginRecord(
        manifest=manifest,
        source_path=Path("/fake"),
        enabled=True,
        instance=None,
    )
    api = PluginApi("hooked", config={}, manifest={"id": "hooked"})
    api.set_registry(fresh_registry)
    api.bind_instance(loader.lifecycle.ensure_instance("hooked"))
    called: list[str] = []
    api.register_uninstall_hook(
        "cleanup",
        lambda plugin_id, delete_files: called.append(plugin_id),
    )

    await loader.unload_plugin("hooked")
    assert called == ["hooked"]
    assert fresh_registry.get_uninstall_hooks() == []


@pytest.mark.asyncio
async def test_skip_legacy_does_not_run_uninstall_hook(fresh_registry):
    loader = PluginLoader(plugin_dirs=[])
    loader.registry = fresh_registry
    manifest = PluginManifest(
        id="legacy",
        name="Legacy",
        version="1.0.0",
        entry=PluginEntryPoints(backend="plugin.py"),
    )
    loader._loaded_plugins["legacy"] = PluginRecord(
        manifest=manifest,
        source_path=Path("/fake"),
        enabled=True,
        instance=None,
    )
    api = PluginApi("legacy", config={}, manifest={"id": "legacy"})
    api.set_registry(fresh_registry)
    api.bind_instance(loader.lifecycle.ensure_instance("legacy"))
    called: list[str] = []
    api.register_uninstall_hook("cleanup", lambda **_k: called.append("ran"))

    await loader._unload_plugin_unlocked(
        "legacy",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
        skip_legacy=True,
    )
    assert not called
    assert not fresh_registry.get_uninstall_hooks()


@pytest.mark.asyncio
async def test_shutdown_skips_table_teardowns(fresh_registry):
    fresh_registry.set_plugin_http_app(FastAPI())
    api = _api(fresh_registry)
    api.register_http_router(APIRouter(), prefix="/pets")
    ran: list[str] = []
    api._instance.record_runtime(
        "conn",
        lambda: ran.append("conn"),
        shutdown_critical=True,
        kind="custody",
    )
    report = await api._instance.dispose(UnloadMode.SHUTDOWN)
    assert report.clean
    assert ran == ["conn"]
    assert fresh_registry.get_http_router_registrations()


def test_prompt_section_names_occupant(fresh_registry):
    api = _api(fresh_registry, "alpha")
    api.register_prompt_section("notes", "workspace", lambda _a: "a")
    other = _api(fresh_registry, "beta")
    with pytest.raises(ValueError, match="plugin 'alpha'"):
        other.register_prompt_section("notes", "workspace", lambda _a: "b")


def test_tool_bridge_names_occupant():
    occupied = ToolRegistry()
    occupied.register(
        ToolDescriptor(
            name="shared",
            func=lambda: None,
            owner_plugin_id="alpha",
        ),
    )
    workspace = SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(tool_registry=occupied),
    )
    registry = SimpleNamespace(
        get_workspace_manager=lambda: SimpleNamespace(
            agents={"talk": workspace},
            _bootstrap_kwargs=None,
        ),
    )
    with pytest.raises(ValueError, match="plugin 'alpha'"):
        _bridge_to_runtime(
            "shared",
            lambda: None,
            True,
            "desc",
            registry,
            "beta",
        )


def test_provision_files_skipped_when_not_owns_commit(tmp_path: Path):
    api = PluginApi("iso", config={}, manifest={"id": "iso"})
    inst = PluginInstance("iso")
    inst.delegate = _DenyCommit()
    api.bind_instance(inst)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("x\n", encoding="utf-8")
    assert api.provision_files(src, tmp_path / "dest", "1.0.0") == "skipped"
    assert not (tmp_path / "dest").exists()


@pytest.mark.asyncio
async def test_reload_aborts_when_not_quiescent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "stuck",
        "stuck",
        body=(
            "def _boom():\n"
            "            raise TimeoutError('stuck')\n"
            "        api.effect('hang', None, _boom)\n"
        ),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, installed)
    staging = _write_plugin(
        tmp_path / "staging-stuck",
        "stuck",
        body="api.register_slash_command('ok', lambda c, a: None)",
    )
    report = await loader.lifecycle.reload("stuck", new_source=staging)
    assert not report.ok
    assert any("stuck" in err for err in report.errors)
    assert "stuck" in loader.get_all_loaded_plugins()
    assert "register_slash_command" not in (installed / "main.py").read_text(
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_plugin_runtime_hook_is_isolated():
    from qwenpaw.runtime.hooks import HookBase, HookContext, HookRegistry
    from qwenpaw.runtime.phases import Phase

    inst = PluginInstance("hook-plug")

    class Boom(HookBase):
        phase = Phase.PRE_DISPATCH
        name = "boom"
        owner_plugin_id = "hook-plug"

        async def run(self, _ctx):
            raise RuntimeError("hook-boom")

    class HostBoom(HookBase):
        phase = Phase.PRE_EXECUTE
        name = "host-boom"

        async def run(self, _ctx):
            raise RuntimeError("host-boom")

    ctx = HookContext(
        request=SimpleNamespace(),
        session_id="s",
        agent_id="a",
        root_session_id="s",
        root_agent_id="a",
        workspace_dir=None,
        workspace=None,
        app_services=None,
    )
    registry = HookRegistry()
    registry.register(Boom())
    await registry.run(Phase.PRE_DISPATCH, ctx)
    assert any("hook-boom" in item for item in inst.diagnostics)

    host = HookRegistry()
    host.register(HostBoom())
    with pytest.raises(RuntimeError, match="host-boom"):
        await host.run(Phase.PRE_EXECUTE, ctx)


def test_cloudpaw_uses_provision_not_loader_patch():
    source = (
        Path(__file__).parents[3]
        / "plugins"
        / "bundle"
        / "cloudpaw"
        / "plugin.py"
    ).read_text(encoding="utf-8")
    assert "_patch_plugin_loader_unload" not in source
    assert "PluginLoader.unload_plugin" not in source
    assert "api.provision(" in source
    assert "cloudpaw_agents" in source


class _DenyCommit(LifecycleDelegate):
    def owns_commit(self, plugin_id: str) -> bool:
        del plugin_id
        return False
