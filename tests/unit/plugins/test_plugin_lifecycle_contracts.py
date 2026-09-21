# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Plugin load, reload, provision, and custody contracts."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.routers.plugins import (
    UpdatePluginConfigRequest,
    uninstall_plugin_source,
    update_plugin_config,
)
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.custody import close_connection, stop_task
from qwenpaw.plugins.lifecycle import (
    PluginInstance,
    PluginLifecycle,
    PluginState,
    UnloadMode,
    UnloadReport,
)
from qwenpaw.plugins.dependency_gate import DependencyGate
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    apply_tool_factory,
    inventory_path,
    load_inventory,
    provision_files,
    recover_migrating_inventory,
    save_inventory,
    teardown_created_locations,
)
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.safe_fs import (
    ensure_deletable,
    parse_optional_absolute,
    same_location,
)
from qwenpaw.plugins.updates import (
    STATUS_COMMITTED,
    STATUS_PREPARED,
    mark_update_committed,
    marker_path,
    recover_interrupted_updates,
    update_marker_status,
    updates_dir,
    write_updating_marker,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
from qwenpaw.runtime.tool_registry import ToolRegistry


@pytest.fixture()
def fresh_registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    body: str = "pass",
    requirements: str | None = None,
) -> Path:
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
    if requirements is not None:
        (root / "requirements.txt").write_text(
            requirements,
            encoding="utf-8",
        )
    return root


def _slash_workspace():
    return SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(
            slash_command_registry=SlashCommandRegistry(),
            tool_registry=ToolRegistry(),
        ),
        channel_manager=ChannelManager([]),
    )


def _isolate_working_dir(tmp_path: Path, monkeypatch) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", work)
    from qwenpaw.config import utils as config_utils

    config_utils._config_cache = None
    config_utils._config_mtime = None
    config_utils._agent_config_cache.clear()
    return work


def _seed_talk_agent(tmp_path: Path, monkeypatch) -> Path:
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import save_config

    work = _isolate_working_dir(tmp_path, monkeypatch)
    workspace = work / "workspaces" / "talk"
    workspace.mkdir(parents=True, exist_ok=True)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="talk",
                agent_order=["talk"],
                profiles={
                    "talk": AgentProfileRef(
                        id="talk",
                        workspace_dir=str(workspace),
                    ),
                },
            ),
        ),
        work / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    return workspace


def _agent_tool_names(agent_id: str = "talk") -> set[str]:
    from qwenpaw.config.config import load_agent_config

    return set(load_agent_config(agent_id).tools.builtin_tools)


def _seed_two_agents(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import save_config

    work = _isolate_working_dir(tmp_path, monkeypatch)
    talk = work / "workspaces" / "talk"
    other = work / "workspaces" / "other"
    talk.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="talk",
                agent_order=["talk", "other"],
                profiles={
                    "talk": AgentProfileRef(
                        id="talk",
                        workspace_dir=str(talk),
                    ),
                    "other": AgentProfileRef(
                        id="other",
                        workspace_dir=str(other),
                    ),
                },
            ),
        ),
        work / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    from qwenpaw.config.config import (
        AgentProfileConfig,
        ToolsConfig,
        save_agent_config,
    )

    for agent_id, workspace in (("talk", talk), ("other", other)):
        save_agent_config(
            agent_id,
            AgentProfileConfig(
                id=agent_id,
                name=agent_id,
                workspace_dir=str(workspace),
                tools=ToolsConfig(builtin_tools={}),
            ),
        )
    return talk, other


def _raw_agent_tools(workspace: Path) -> set[str]:
    path = workspace / "agent.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    tools = (data.get("tools") or {}).get("builtin_tools") or {}
    return set(tools)


def _volume_is_case_insensitive(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / "CaseProbe"
    probe.mkdir()
    alias = path / "caseprobe"
    try:
        return alias.exists() and same_location(probe, alias)
    finally:
        shutil.rmtree(probe)


def _patch_agent_tools(monkeypatch):
    boxes = {
        "talk": SimpleNamespace(tools=SimpleNamespace(builtin_tools={})),
    }

    def _load(agent_id):
        return boxes[agent_id]

    def _save(agent_id, cfg):
        boxes[agent_id] = cfg

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        _load,
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.save_agent_config",
        _save,
    )
    return boxes


def _control_body(name: str) -> str:
    return (
        "from qwenpaw.runtime.commands.control.base import "
        "BaseControlCommandHandler\n"
        "        class _H(BaseControlCommandHandler):\n"
        f"            command_name = '{name}'\n"
        "            async def handle(self, context):\n"
        "                return 'ok'\n"
        "        api.register_control_command(_H())"
    )


def _tool_body(name: str, description: str = "shared") -> str:
    return (
        f"def _{name}():\n"
        "            return 'ok'\n"
        "        api.register_tool(\n"
        f"            '{name}', _{name}, description={description!r},\n"
        "        )"
    )


def _tools_body(*pairs: tuple[str, str]) -> str:
    chunks = [_tool_body(name, desc) for name, desc in pairs]
    return ("\n        ").join(chunks)


def _tool_description(name: str, agent_id: str = "talk") -> str | None:
    from qwenpaw.config.config import load_agent_config

    tool = load_agent_config(agent_id).tools.builtin_tools.get(name)
    if tool is None:
        return None
    return getattr(tool, "description", None)


async def _load(
    tmp_path: Path,
    fresh_registry,
    plugin_id: str,
    body: str,
    *,
    config: dict | None = None,
    activate: bool = True,
):
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(
        manifest,
        installed,
        config,
        activate=activate,
    )
    return loader, workspace, installed


@pytest.mark.asyncio
async def test_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    _write_plugin(
        tmp_path / "plugins" / "owner-b",
        "owner-b",
        body="api.register_slash_command('ping', lambda c, a: None)",
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "owner-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "owner-b",
        activate=False,
    )
    with pytest.raises(Exception, match="Projection|already"):
        await loader.activate_plugin_unlocked("owner-b")
    await loader.unload_plugin("owner-b", delete_files=False)
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_failed_staging_keeps_old_dir(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "stage-keep",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    staging = _write_plugin(
        tmp_path / "incoming-stage",
        "stage-keep",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.copytree", _boom)
    report = await loader.lifecycle.reload(
        "stage-keep",
        new_source=staging,
    )
    assert not report.ok
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert "stage-keep" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_startup_failure_restores_old_projection(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    staging = _write_plugin(
        tmp_path / "incoming-svc",
        "svc",
        body=(
            "api.register_slash_command('pong', lambda c, a: None)\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    report = await loader.lifecycle.reload("svc", new_source=staging)
    assert not report.ok
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert "ping" in workspace.plugins.slash_command_registry.names()
    assert "pong" not in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_sync_close_does_not_block_event_loop():
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    class _SlowClose:
        def close(self) -> None:
            time.sleep(0.12)

    heart = asyncio.create_task(_heart())
    await close_connection(_SlowClose(), "slow")
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05


def test_empty_update_paths_are_noop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    sentinel = tmp_path / "work" / "keep-me"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("safe\n", encoding="utf-8")
    marker = updates_dir() / "empty.json"
    marker.write_text(
        json.dumps(
            {
                "plugin_id": "empty",
                "status": "updating",
                "backup_path": "",
                "target_path": "",
                "staging_path": "",
            },
        ),
        encoding="utf-8",
    )
    recover_interrupted_updates()
    assert sentinel.read_text(encoding="utf-8") == "safe\n"
    assert parse_optional_absolute("") is None
    assert parse_optional_absolute(None) is None
    with pytest.raises(ValueError, match="refusing to delete"):
        ensure_deletable(Path(""))


@pytest.mark.asyncio
async def test_dependency_gate_runs_before_probe(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "deps",
        "pass",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-deps",
        "deps",
        body="import definitely_not_a_real_pkg_xyz\n        pass",
        requirements="definitely-not-a-real-pkg-xyz==9.9.9\n",
    )
    order: list[str] = []

    def _eval(self, *args, **kwargs):
        del self, args, kwargs
        order.append("gate")
        from qwenpaw.plugins.dependency_gate import GateDecision

        return GateDecision(
            allow_install=False,
            already_satisfied=True,
            reason="ok",
        )

    monkeypatch.setattr(DependencyGate, "evaluate", _eval)

    async def _probe(*args, **kwargs):
        del args, kwargs
        order.append("probe")
        return None

    monkeypatch.setattr("qwenpaw.plugins.loader._probe_incoming", _probe)
    report = await loader.lifecycle.reload(
        "deps",
        new_source=incoming,
        allow_install=True,
    )
    assert not report.ok
    assert "gate" in order
    assert order.index("gate") < order.index("probe")


def test_platform_marker_is_skipped(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        'definitely-windows-only-xyz==1.0; sys_platform == "win32"\n'
        'definitely-darwin-only-xyz==1.0; sys_platform == "darwin"\n',
        encoding="utf-8",
    )
    decision = DependencyGate().evaluate(
        req,
        allow_install=False,
        plugin_id="p",
    )
    missing = " ".join(decision.missing)
    if sys.platform == "win32":
        assert "definitely-windows-only-xyz" in missing
        assert "definitely-darwin-only-xyz" not in missing
    elif sys.platform == "darwin":
        assert "definitely-darwin-only-xyz" in missing
        assert "definitely-windows-only-xyz" not in missing
    assert not decision.unsupported


def test_unsupported_requirement_is_loud(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("-r extra.txt\n", encoding="utf-8")
    decision = DependencyGate().evaluate(
        req,
        allow_install=True,
        plugin_id="p",
    )
    assert decision.unsupported
    assert not decision.allow_install
    assert "unsupported" in decision.reason


def test_migrate_keeps_owned_for_uninstall(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    assert provision_files("own", src, dest, "1.0.0") == "create"
    (src / "note.md").write_text("v2\n", encoding="utf-8")
    assert provision_files("own", src, dest, "2.0.0") == "migrate"
    loc = load_inventory("own")["locations"][str(dest)]
    assert loc["owned"] is True
    assert "branch" not in loc
    teardown_created_locations("own")
    assert not dest.exists()


@pytest.mark.asyncio
async def test_failed_register_undoes_this_txn_create(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "created-once"
    body = (
        "from pathlib import Path\n"
        f"        api.provision_files(Path({str(tmp_path / 'factory')!r}), "
        f"Path({str(dest)!r}), '1.0.0')\n"
        "        raise RuntimeError('register boom')"
    )
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    installed = _write_plugin(tmp_path / "plugins" / "boom", "boom", body=body)
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert not dest.exists()


@pytest.mark.asyncio
async def test_failed_channel_stop_keeps_handle():
    class _Bad:
        channel = "bad-ch"

        def set_enqueue(self, _enqueue) -> None:
            return None

        async def stop(self) -> None:
            raise RuntimeError("still connected")

    manager = ChannelManager([])
    bad = _Bad()
    manager.channels.append(bad)
    receipt = await manager.stop_one("bad-ch")
    assert receipt.stopped is False
    assert bad in manager.channels


@pytest.mark.asyncio
async def test_unquiescent_reload_does_not_reregister(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "busy",
        "pass",
    )

    async def _busy_unload(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="busy",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["thread still running"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy_unload)
    report = await loader.lifecycle.reload("busy")
    assert not report.ok
    assert report.needs_restart
    assert "busy" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_config_route_runs_startup_once(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    counter = tmp_path / "starts.txt"
    body = (
        "from pathlib import Path\n"
        f"        p = Path({str(counter)!r})\n"
        "        def _start(_p=p):\n"
        "            n = int(_p.read_text()) if _p.exists() else 0\n"
        "            _p.write_text(str(n + 1))\n"
        "        api.register_startup_hook('count', _start)\n"
        "        api.register_slash_command("
        "api.config.get('cmd', 'old'), lambda c, a: None)"
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cfg",
        body,
        config={"cmd": "old"},
    )
    before = int(counter.read_text()) if counter.exists() else 0
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    result = await update_plugin_config(
        "cfg",
        UpdatePluginConfigRequest(config={"cmd": "new"}),
        request,
    )
    assert result["ok"] is True
    after = int(counter.read_text())
    assert after - before == 1


@pytest.mark.asyncio
async def test_reload_generation_keeps_new_task(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    marker = tmp_path / "task.txt"
    body = (
        "import pathlib\n"
        "        async def _run():\n"
        f"            pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "        api.spawn_task(_run(), 'tick')"
    )
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "gen",
        body,
    )
    await asyncio.sleep(0.05)
    assert marker.read_text() == "ran"
    inst = loader.lifecycle.get_instance("gen")
    assert inst is not None
    first_gen = inst.generation
    marker.write_text("")
    _write_plugin(
        installed,
        "gen",
        body=(
            "import pathlib\n"
            "        async def _run():\n"
            f"            pathlib.Path({str(marker)!r}).write_text('ran2')\n"
            "        api.spawn_task(_run(), 'tick')"
        ),
    )
    report = await loader.lifecycle.reload("gen")
    assert report.ok
    assert report.generation == first_gen + 1
    await asyncio.sleep(0.05)
    assert marker.read_text() == "ran2"


@pytest.mark.asyncio
async def test_in_place_rollback_reuses_old_plugin_def(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "inplace",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    (installed / "main.py").write_text(
        "class _P:\n"
        "    def register(self, api):\n"
        "        raise RuntimeError('bad disk')\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    report = await loader.lifecycle.reload("inplace")
    assert not report.ok
    assert loader.get_loaded_plugin("inplace").status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_repair_keeps_config_and_activates(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "fixme",
        "api.register_slash_command(api.config.get('cmd', 'x'), "
        "lambda c, a: None)",
        config={"cmd": "kept"},
    )
    record = loader.get_loaded_plugin("fixme")
    record.status = "failed"
    record.enabled = False
    inst = loader.lifecycle.get_instance("fixme")
    inst.mark_failed("missing dep")
    inst.activated = False
    repaired = await loader.repair_dependencies("fixme")
    assert repaired.status == "active"
    assert loader.lifecycle.get_instance("fixme").config.get("cmd") == "kept"
    assert "kept" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_force_install_respects_owns_commit(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "owned",
        "pass",
    )
    loader.lifecycle.delegate.owns_commit = lambda _plugin_id: False
    staging = _write_plugin(
        tmp_path / "staging-owned",
        "owned",
        body="api.register_slash_command('nope', lambda c, a: None)",
    )
    with pytest.raises(RuntimeError, match="not owned"):
        await loader.load_plugin_from_path(staging, force=True)
    assert "class _P" in (installed / "main.py").read_text(encoding="utf-8")
    assert "register_slash_command" not in (installed / "main.py").read_text(
        encoding="utf-8",
    )


def test_same_location_uses_identity(tmp_path: Path):
    target = tmp_path / "CasePlugin"
    target.mkdir()
    alias = tmp_path / "CasePlugin"
    assert same_location(target, alias)
    missing = tmp_path / "missing-a"
    other = tmp_path / "missing-b"
    assert same_location(missing, missing)
    assert not same_location(missing, other)


def test_factory_baseline_frozen_until_commit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    apply_tool_factory(
        "tid",
        "demo",
        {"description": "old"},
        None,
    )
    first = apply_tool_factory(
        "tid",
        "demo",
        {"description": "new"},
        {"description": "old"},
    )
    second = apply_tool_factory(
        "tid",
        "demo",
        {"description": "new"},
        {"description": "old"},
    )
    assert first["description"] == "new"
    assert second["description"] == "new"
    row = load_inventory("tid")["tools"]["demo"]
    assert row["factory"]["description"] == "old"
    assert row["pending_factory"]["description"] == "new"


@pytest.mark.asyncio
async def test_unload_keeps_instance_when_not_quiescent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "held",
        "pass",
    )
    inst = loader.lifecycle.get_instance("held")
    assert inst is not None

    async def _hang():
        raise TimeoutError("thread still running")

    inst.record_runtime("thread:x", _hang, kind="custody")
    report = await loader.unload_plugin("held", delete_files=False)
    assert report.quiescent is False
    assert report.needs_restart is True
    assert loader.lifecycle.get_instance("held") is inst
    assert "held" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_teardown_timeout_is_not_quiescent():
    inst = PluginInstance("stuck")

    async def _hang():
        raise TimeoutError("thread still running")

    inst.record_runtime("thread:x", _hang, kind="custody")
    report = await inst.teardown_runtime()
    assert report.clean is False
    assert report.quiescent is False
    assert report.needs_restart is True
    assert inst.state is PluginState.FAILED
    assert inst._runtime


@pytest.mark.asyncio
async def test_repair_does_not_load_disabled_plugin(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    class _Cfg:
        plugins = {"off": {"enabled": False}}

    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda *args, **kwargs: _Cfg(),
    )
    installed = _write_plugin(tmp_path / "plugins" / "off", "off")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    repaired = await loader.repair_dependencies("off")
    assert repaired.status == "inactive"
    assert repaired.enabled is False
    assert "off" not in loader.get_all_loaded_plugins()
    assert loader.lifecycle.get_instance("off") is None
    del installed


@pytest.mark.asyncio
async def test_occupied_swap_keeps_marker_and_needs_restart(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "busyfs",
        "pass",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-busyfs",
        "busyfs",
        body="api.register_slash_command('next', lambda c, a: None)",
    )
    moves = {"n": 0}
    real_move = shutil.move

    def _move(src, dst, *args, **kwargs):
        moves["n"] += 1
        if moves["n"] >= 2:
            raise PermissionError("file in use")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.move", _move)
    report = await loader.reload_plugin_unlocked(
        "busyfs",
        new_source=incoming,
        allow_install=False,
        owns_dependency_env=True,
    )
    assert not report.ok
    assert report.needs_restart
    assert marker_path("busyfs").is_file()
    del installed


def _clear_tool_owners():
    from qwenpaw.plugins.api import (
        _TOOL_PLUGIN_OWNERS,
        _TOOL_PLUGIN_OWNERS_LOCK,
    )

    with _TOOL_PLUGIN_OWNERS_LOCK:
        _TOOL_PLUGIN_OWNERS.clear()


@pytest.mark.asyncio
async def test_tool_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    boxes = _patch_agent_tools(monkeypatch)
    _clear_tool_owners()
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        _tool_body("shared_tool"),
    )
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    from qwenpaw.plugins.api import _TOOL_PLUGIN_OWNERS

    assert _TOOL_PLUGIN_OWNERS.get("shared_tool") == "owner-a"
    _write_plugin(
        tmp_path / "plugins" / "owner-b",
        "owner-b",
        body=_tool_body("shared_tool"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "owner-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "owner-b",
        activate=False,
    )
    with pytest.raises(Exception, match="Projection|already|owned"):
        await loader.activate_plugin_unlocked("owner-b")
    record_b = loader.get_loaded_plugin("owner-b")
    assert record_b is None or record_b.status != "active"
    await loader.unload_plugin(
        "owner-b",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    assert _TOOL_PLUGIN_OWNERS.get("shared_tool") == "owner-a"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_control_command_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.runtime.commands.control import (
        command_owner,
        unregister_command,
    )

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cmd-a",
        _control_body("sharedcmd"),
    )
    assert command_owner("sharedcmd") == "cmd-a"
    _write_plugin(
        tmp_path / "plugins" / "cmd-b",
        "cmd-b",
        body=_control_body("sharedcmd"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "cmd-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    record_b = await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "cmd-b",
        activate=False,
    )
    assert record_b.status != "active"
    if loader.get_loaded_plugin("cmd-b") is not None:
        await loader.unload_plugin("cmd-b", delete_files=False)
    assert command_owner("sharedcmd") == "cmd-a"
    await loader.unload_plugin("cmd-a", delete_files=False)
    unregister_command("sharedcmd", owner="cmd-a")


@pytest.mark.asyncio
async def test_stop_one_propagates_cancelled_error():
    class _Ch:
        channel = "x"

        def set_enqueue(self, _enqueue):
            return None

        async def stop(self):
            raise asyncio.CancelledError()

    manager = ChannelManager([])
    manager.channels = [_Ch()]
    with pytest.raises(asyncio.CancelledError):
        await manager.stop_one("x")
    assert manager.channels


@pytest.mark.asyncio
async def test_reload_cancel_after_unload_restores_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-cancel",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-svc-cancel",
        "svc-cancel",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    async def _cancel_swap(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(loader, "_swap_plugin_dir", _cancel_swap)
    with pytest.raises(asyncio.CancelledError):
        await loader.reload_plugin_unlocked(
            "svc-cancel",
            new_source=incoming,
            allow_install=False,
            owns_dependency_env=True,
        )
    assert "ping" in workspace.plugins.slash_command_registry.names()
    record = loader.get_loaded_plugin("svc-cancel")
    assert record is not None
    assert record.status == "active"
    assert (installed / "main.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_reload_cancel_after_swap_restores_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-swap-cancel",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-svc-swap-cancel",
        "svc-swap-cancel",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    calls = {"n": 0}
    real_load = loader._load_plugin_unlocked

    async def _load_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError()
        return await real_load(*args, **kwargs)

    monkeypatch.setattr(loader, "_load_plugin_unlocked", _load_once)
    with pytest.raises(asyncio.CancelledError):
        await loader.reload_plugin_unlocked(
            "svc-swap-cancel",
            new_source=incoming,
            allow_install=False,
            owns_dependency_env=True,
        )
    assert "ping" in workspace.plugins.slash_command_registry.names()
    record = loader.get_loaded_plugin("svc-swap-cancel")
    assert record is not None
    assert record.status == "active"
    assert "pong" not in (installed / "main.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_install_cancel_waits_for_copy_before_next_load(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    source = _write_plugin(tmp_path / "src-copier", "copier", body="pass")
    install_dir = tmp_path / "plugins"
    install_dir.mkdir(parents=True, exist_ok=True)
    loader = PluginLoader(plugin_dirs=[install_dir])
    loader.registry = fresh_registry
    finished = {"done": False}
    real_copy = shutil.copytree

    def _slow_copy(src, dst, *args, **kwargs):
        time.sleep(0.12)
        result = real_copy(src, dst, *args, **kwargs)
        finished["done"] = True
        return result

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.copytree", _slow_copy)
    task = asyncio.create_task(
        loader.load_plugin_from_path(source, install_dir=install_dir),
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished["done"]
    record = await loader.load_plugin_from_path(
        source,
        install_dir=install_dir,
        force=True,
    )
    assert record.manifest.id == "copier"


@pytest.mark.asyncio
async def test_provision_replay_without_instance(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    flag = tmp_path / "cleared.txt"
    plugin_dir = tmp_path / "plugins" / "cloud-lite"
    _write_plugin(
        plugin_dir,
        "cloud-lite",
        body=(
            "api.provision(\n"
            "            'cloudpaw_agents',\n"
            "            setup=None,\n"
            "            teardown=None,\n"
            "            kind='cloudpaw_agents',\n"
            "            teardown_ref='agents_setup:uninstall_agents',\n"
            "        )"
        ),
    )
    (plugin_dir / "agents_setup.py").write_text(
        "from pathlib import Path\n"
        f"FLAG = Path({str(flag)!r})\n"
        "def uninstall_agents():\n"
        "    FLAG.write_text('cleared', encoding='utf-8')\n",
        encoding="utf-8",
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cloud-lite",
        (
            "api.provision(\n"
            "            'cloudpaw_agents',\n"
            "            setup=None,\n"
            "            teardown=None,\n"
            "            kind='cloudpaw_agents',\n"
            "            teardown_ref='agents_setup:uninstall_agents',\n"
            "        )"
        ),
    )
    await loader.unload_plugin(
        "cloud-lite",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("cloud-lite") is None
    assert plugin_dir.is_dir()
    report = await loader.unload_plugin(
        "cloud-lite",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert report.quiescent
    assert flag.read_text(encoding="utf-8") == "cleared"


@pytest.mark.asyncio
async def test_pawapp_disable_then_delete_uses_lifecycle(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.app.routers.pawapps import uninstall_pawapp

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: tmp_path / "plugins",
    )
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "paw-app",
        "pass",
    )
    await loader.unload_plugin(
        "paw-app",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("paw-app") is None
    assert installed.is_dir()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    result = await uninstall_pawapp("paw-app", request)
    assert result["id"] == "paw-app"
    assert not installed.exists()


@pytest.mark.asyncio
async def test_http_uninstall_does_not_delete_tools_from_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    boxes = _patch_agent_tools(monkeypatch)
    _clear_tool_owners()
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        _tool_body("shared_tool"),
    )
    _write_plugin(tmp_path / "plugins" / "meta-b", "meta-b", body="pass")
    plugin_json = tmp_path / "plugins" / "meta-b" / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    data["meta"] = {"tools": [{"name": "shared_tool"}]}
    plugin_json.write_text(json.dumps(data), encoding="utf-8")
    manifest_b = PluginManifest.from_dict(data)
    await loader.load_plugin(manifest_b, tmp_path / "plugins" / "meta-b")
    await loader.activate_plugin_unlocked("meta-b")
    removed = []
    monkeypatch.setattr(
        "qwenpaw.app.routers.plugins._remove_plugin_tools_from_agents",
        lambda plugin_id, meta: removed.append((plugin_id, meta)),
    )
    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=loader))
    await uninstall_plugin_source("meta-b", app=app)
    assert not removed
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_activate_skill_copy_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins.api import PluginApi

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    def _slow(self, *_args, **_kwargs):
        del self
        time.sleep(0.12)

    monkeypatch.setattr(PluginApi, "_do_install_skills", _slow)
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    heart = asyncio.create_task(_heart())
    await _load(
        tmp_path,
        fresh_registry,
        "skiller",
        "from pathlib import Path\n"
        "        api.register_skill_provider(Path('.'))",
    )
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05


@pytest.mark.asyncio
async def test_activate_tool_config_write_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    _patch_agent_tools(monkeypatch)
    _clear_tool_owners()

    def _slow(*_args, **_kwargs):
        time.sleep(0.12)

    monkeypatch.setattr("qwenpaw.plugins.api._write_tool_config", _slow)
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    heart = asyncio.create_task(_heart())
    await _load(
        tmp_path,
        fresh_registry,
        "tool-io",
        _tool_body("io_tool"),
    )
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05
    _clear_tool_owners()


def test_plugins_get_missing_id_is_404_not_405():
    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = None
    client = TestClient(app)
    response = client.get("/api/plugins/nonexistent-plugin-12345")
    assert response.status_code == 404
    assert response.status_code != 405


@pytest.mark.asyncio
async def test_disable_then_uninstall_removes_owned_agent_tool(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "keep-a",
        _tool_body("keep_tool"),
    )
    _write_plugin(
        tmp_path / "plugins" / "solo-b",
        "solo-b",
        body=_tool_body("solo_tool"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "solo-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(manifest_b, tmp_path / "plugins" / "solo-b")
    await loader.activate_plugin_unlocked("solo-b")
    assert {"keep_tool", "solo_tool"} <= _agent_tool_names()
    await loader.unload_plugin(
        "solo-b",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("solo-b") is None
    assert {"keep_tool", "solo_tool"} <= _agent_tool_names()
    await loader.unload_plugin(
        "solo-b",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    names = _agent_tool_names()
    assert "solo_tool" not in names
    assert "keep_tool" in names
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_inventory_only_uninstall_removes_owned_agent_tool(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.config.config import BuiltinToolConfig, load_agent_config
    from qwenpaw.config.config import save_agent_config

    _seed_talk_agent(tmp_path, monkeypatch)
    agent_cfg = load_agent_config("talk")
    agent_cfg.tools.builtin_tools["solo_tool"] = BuiltinToolConfig(
        name="solo_tool",
        description="solo",
    )
    agent_cfg.tools.builtin_tools["keep_tool"] = BuiltinToolConfig(
        name="keep_tool",
        description="keep",
    )
    save_agent_config("talk", agent_cfg)
    save_inventory(
        "solo-only",
        {
            "plugin_id": "solo-only",
            "locations": {},
            "tools": {"solo_tool": {"factory": {"description": "solo"}}},
            "provisions": [],
        },
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    assert loader.get_loaded_plugin("solo-only") is None
    await loader.unload_plugin(
        "solo-only",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    names = _agent_tool_names()
    assert "solo_tool" not in names
    assert "keep_tool" in names


@pytest.mark.asyncio
async def test_default_load_activates_register_is_not_active(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "reg-only",
        "api.register_slash_command('ping', lambda c, a: None)",
        activate=False,
    )
    record = loader.get_loaded_plugin("reg-only")
    assert record is not None
    assert record.status == "registered"
    assert "ping" not in workspace.plugins.slash_command_registry.names()
    await loader.activate_plugin_unlocked("reg-only")
    assert record.status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()
    await loader.unload_plugin("reg-only", delete_files=False)
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    again = await loader.load_plugin(manifest, installed)
    assert again.status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_unquiescent_repair_does_not_drop_instance(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "fix-busy",
        "api.register_slash_command('kept', lambda c, a: None)",
    )
    record = loader.get_loaded_plugin("fix-busy")
    record.status = "failed"
    record.enabled = False
    inst = loader.lifecycle.get_instance("fix-busy")
    inst.mark_failed("missing dep")
    original = inst

    async def _busy() -> UnloadReport:
        return UnloadReport(
            plugin_id="fix-busy",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["thread still running"],
        )

    monkeypatch.setattr(inst, "teardown_runtime", _busy)
    repaired = await loader.repair_dependencies("fix-busy")
    assert repaired.status == "failed"
    assert loader.lifecycle.get_instance("fix-busy") is original
    assert any("quiescent" in str(item) for item in repaired.diagnostics)


@pytest.mark.asyncio
async def test_activate_failure_rolls_back_new_agent_tools(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    body = (
        _tool_body("ghost_tool") + "\n"
        "        def _boom():\n"
        "            raise RuntimeError('startup boom')\n"
        "        api.register_startup_hook('boom', _boom, priority=90)"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "ghost",
        "ghost",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record is loader.get_loaded_plugin("ghost")
    assert record is not None
    assert record.status == "failed"
    assert "ghost_tool" not in _agent_tool_names()
    tools = load_inventory("ghost").get("tools") or {}
    assert "ghost_tool" not in tools
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_skill_install_failure_fails_activate(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills = tmp_path / "plugin-skills"
    skill_aaa = skills / "aaa"
    skill_zzz = skills / "zzz"
    skill_aaa.mkdir(parents=True)
    skill_zzz.mkdir(parents=True)
    (skill_aaa / "SKILL.md").write_text("# aaa\n", encoding="utf-8")
    (skill_zzz / "SKILL.md").write_text("# zzz\n", encoding="utf-8")
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.list_workspaces",
        lambda: [{"workspace_dir": str(workspace), "agent_id": "talk"}],
    )
    from qwenpaw.plugins import provision as provision_mod

    real_provision = provision_mod.provision_files

    def _fail_zzz(plugin_id, src, dest, version):
        if Path(src).name == "zzz" or Path(dest).name == "zzz":
            raise RuntimeError("zzz failed")
        return real_provision(plugin_id, src, dest, version)

    monkeypatch.setattr(provision_mod, "provision_files", _fail_zzz)
    body = (
        "from pathlib import Path\n"
        f"        api.register_skill_provider(Path({str(skills)!r}))"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "skiller-fail",
        "skiller-fail",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record is loader.get_loaded_plugin("skiller-fail")
    assert record is not None
    assert record.status == "failed"
    inst = loader.lifecycle.get_instance("skiller-fail")
    assert inst is None or inst.activated is False
    from qwenpaw.agents.skill_system.store import get_workspace_skills_dir

    copied = get_workspace_skills_dir(workspace)
    assert not (copied / "aaa").exists()
    assert not (copied / "zzz").exists()
    loc = load_inventory("skiller-fail").get("locations") or {}
    assert not any(Path(key).name in {"aaa", "zzz"} for key in loc)
    migrating = [
        row
        for row in loc.values()
        if (row or {}).get("migrating")
        and (row.get("migrating") or {}).get("status") != "committed"
    ]
    assert not migrating


@pytest.mark.asyncio
async def test_unloaded_force_skips_copy_on_case_alias(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugins = tmp_path / "plugins"
    if not _volume_is_case_insensitive(plugins):
        pytest.skip("volume is case-sensitive")
    installed = _write_plugin(plugins / "CasePlugin", "CasePlugin")
    alias = plugins / "caseplugin"
    assert same_location(installed, alias)
    marker = installed / "unique.txt"
    marker.write_text("keep-me", encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[plugins])
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(alias, force=True)
    assert installed.exists()
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert record.status == "active"
    assert (installed / "plugin.json").exists()


@pytest.mark.asyncio
async def test_meta_only_tool_is_not_written_to_agents(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    talk, other = _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    installed = _write_plugin(tmp_path / "plugins" / "meta-only", "meta-only")
    plugin_json = installed / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    data["meta"] = {"tools": [{"name": "meta_ghost"}]}
    plugin_json.write_text(json.dumps(data), encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(data)
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "active"
    assert "meta_ghost" not in _raw_agent_tools(talk)
    assert "meta_ghost" not in _raw_agent_tools(other)
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_register_tool_writes_all_agents_and_uninstall_clears(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    installed = _write_plugin(
        tmp_path / "plugins" / "all-agents",
        "all-agents",
        body=_tool_body("shared_everywhere"),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "active"
    assert "shared_everywhere" in _agent_tool_names("talk")
    assert "shared_everywhere" in _agent_tool_names("other")
    await loader.unload_plugin(
        "all-agents",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "shared_everywhere" not in _agent_tool_names("talk")
    assert "shared_everywhere" not in _agent_tool_names("other")
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_reload_failed_activate_restores_tool_description(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "desc-reload",
        _tool_body("reload_demo_tool", "v1-desc"),
    )
    assert _tool_description("reload_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-reload")["tools"]["reload_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    _write_plugin(
        installed,
        "desc-reload",
        body=(
            _tool_body("reload_demo_tool", "v2-desc") + "\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom, priority=90)"
        ),
    )
    report = await loader.lifecycle.reload("desc-reload")
    assert not report.ok
    assert _tool_description("reload_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-reload")["tools"]["reload_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    _write_plugin(
        installed,
        "desc-reload",
        body=_tool_body("reload_demo_tool", "v1-desc"),
    )
    report = await loader.lifecycle.reload("desc-reload")
    assert report.ok
    assert _tool_description("reload_demo_tool") == "v1-desc"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_update_config_failed_activate_restores_tool_description(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    body = (
        "def _demo():\n"
        "            return 'ok'\n"
        "        api.register_tool(\n"
        "            'cfg_demo_tool', _demo,\n"
        "            description=api.config.get('desc', 'v1-desc'),\n"
        "        )\n"
        "        if api.config.get('boom'):\n"
        "            def _boom():\n"
        "                raise RuntimeError('startup boom')\n"
        "            api.register_startup_hook('boom', _boom, priority=90)"
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "desc-cfg",
        body,
        config={"desc": "v1-desc"},
    )
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    failed = await loader.lifecycle.update_config(
        "desc-cfg",
        {"desc": "v2-desc", "boom": True},
    )
    assert not failed.ok
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-cfg")["tools"]["cfg_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    ok = await loader.lifecycle.update_config(
        "desc-cfg",
        {"desc": "v1-desc"},
    )
    assert ok.ok
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_reload_drops_unregistered_tools_without_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    body_v1 = _tools_body(("drop_old_tool", "old"), ("drop_keep_tool", "keep"))
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "drop-tools",
        body_v1,
    )
    assert {"drop_old_tool", "drop_keep_tool"} <= _agent_tool_names("talk")
    assert {"drop_old_tool", "drop_keep_tool"} <= _agent_tool_names("other")
    incoming = _write_plugin(
        tmp_path / "incoming-drop-tools",
        "drop-tools",
        body=_tool_body("drop_keep_tool", "keep"),
    )
    report = await loader.lifecycle.reload(
        "drop-tools",
        new_source=incoming,
    )
    assert report.ok
    assert "drop_old_tool" not in _agent_tool_names("talk")
    assert "drop_old_tool" not in _agent_tool_names("other")
    assert "drop_keep_tool" in _agent_tool_names("talk")
    assert "drop_keep_tool" in _agent_tool_names("other")
    assert "drop_old_tool" not in (
        load_inventory("drop-tools").get("tools") or {}
    )
    other = _write_plugin(
        tmp_path / "plugins" / "other-owner",
        "other-owner",
        body=_tool_body("drop_old_tool", "other"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads((other / "plugin.json").read_text(encoding="utf-8")),
    )
    record_b = await loader.load_plugin(manifest_b, other)
    assert record_b.status == "active"
    await loader.unload_plugin(
        "drop-tools",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "drop_old_tool" in _agent_tool_names("talk")
    assert "drop_keep_tool" not in _agent_tool_names("talk")
    _clear_tool_owners()
    del installed


@pytest.mark.asyncio
async def test_force_install_drops_unregistered_tools_without_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "force-drop",
        _tools_body(("force_old_tool", "old"), ("force_keep_tool", "keep")),
    )
    incoming = _write_plugin(
        tmp_path / "incoming-force-drop",
        "force-drop",
        body=_tool_body("force_keep_tool", "keep"),
    )
    record = await loader.load_plugin_from_path(incoming, force=True)
    assert record.status == "active"
    assert "force_old_tool" not in _agent_tool_names("talk")
    assert "force_old_tool" not in _agent_tool_names("other")
    assert "force_keep_tool" in _agent_tool_names("talk")
    assert "force_old_tool" not in (
        load_inventory("force-drop").get("tools") or {}
    )
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_reload_cleanup_failure_after_commit_keeps_new_version(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "keep-new",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    incoming = _write_plugin(
        tmp_path / "incoming-keep-new",
        "keep-new",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    (incoming / "v2.txt").write_text("v2", encoding="utf-8")

    def _fail_remove(path):
        raise PermissionError("sharing violation")

    monkeypatch.setattr("qwenpaw.plugins.loader._remove_dir", _fail_remove)
    report = await loader.lifecycle.reload("keep-new", new_source=incoming)
    assert report.ok
    assert report.needs_restart
    assert (installed / "main.py").read_text(encoding="utf-8") != old_text
    assert "pong" in (installed / "main.py").read_text(encoding="utf-8")
    assert "pong" in workspace.plugins.slash_command_registry.names()
    assert "ping" not in workspace.plugins.slash_command_registry.names()
    record = loader.get_loaded_plugin("keep-new")
    assert record is not None
    assert record.status == "active"


@pytest.mark.asyncio
async def test_reload_cancel_after_activate_commit_keeps_new_version(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "cancel-committed",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-cancel-committed",
        "cancel-committed",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    rollbacks: list[bool] = []
    real_commit = loader._commit_plugin_transaction
    real_rollback = loader._rollback_reload

    async def _commit_then_cancel(*args, **kwargs):
        await real_commit(*args, **kwargs)
        raise asyncio.CancelledError

    async def _spy_rollback(*args, **kwargs):
        rollbacks.append(True)
        return await real_rollback(*args, **kwargs)

    monkeypatch.setattr(
        loader,
        "_commit_plugin_transaction",
        _commit_then_cancel,
    )
    monkeypatch.setattr(loader, "_rollback_reload", _spy_rollback)
    with pytest.raises(asyncio.CancelledError):
        await loader.lifecycle.reload(
            "cancel-committed",
            new_source=incoming,
        )
    assert not rollbacks
    assert "pong" in workspace.plugins.slash_command_registry.names()
    assert "ping" not in workspace.plugins.slash_command_registry.names()
    assert "pong" in (installed / "main.py").read_text(encoding="utf-8")
    record = loader.get_loaded_plugin("cancel-committed")
    assert record is not None
    assert record.status == "active"
    inst = loader.lifecycle.get_instance("cancel-committed")
    assert inst is not None
    assert inst.activated
    assert update_marker_status("cancel-committed") != STATUS_PREPARED


@pytest.mark.asyncio
async def test_unquiescent_new_version_does_not_restore_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "sticky-new",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    initial_gen = loader.lifecycle.get_instance("sticky-new").generation
    incoming = _write_plugin(
        tmp_path / "incoming-sticky-new",
        "sticky-new",
        body=(
            "api.register_slash_command('pong', lambda c, a: None)\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom, priority=90)"
        ),
    )
    real_dispose = PluginInstance.dispose

    async def _sticky(self, mode):
        if self.generation > initial_gen:
            report = UnloadReport(
                plugin_id=self.plugin_id,
                mode=mode,
                clean=False,
                quiescent=False,
                needs_restart=True,
                errors=["channel stop failed"],
            )
            self.state = PluginState.FAILED
            self.activated = False
            return report
        return await real_dispose(self, mode)

    monkeypatch.setattr(PluginInstance, "dispose", _sticky)
    report = await loader.lifecycle.reload("sticky-new", new_source=incoming)
    assert not report.ok
    assert report.needs_restart
    assert marker_path("sticky-new").is_file()
    inst = loader.lifecycle.get_instance("sticky-new")
    assert inst is not None
    assert inst.activated is False
    assert inst.state is not PluginState.DISPOSED
    assert loader.get_loaded_plugin("sticky-new") is not None
    names = workspace.plugins.slash_command_registry.names()
    assert "ping" not in names


@pytest.mark.asyncio
async def test_restore_failed_load_is_reported(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "restore-fail",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-restore-fail",
        "restore-fail",
        body=(
            "api.register_slash_command('pong', lambda c, a: None)\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom, priority=90)"
        ),
    )
    restoring = {"on": False}
    real_rollback = loader._rollback_reload
    real_load = loader._load_plugin_unlocked

    async def _rollback(*args, **kwargs):
        restoring["on"] = True
        try:
            return await real_rollback(*args, **kwargs)
        finally:
            restoring["on"] = False

    async def _load_wrap(*args, **kwargs):
        record = await real_load(*args, **kwargs)
        if restoring["on"]:
            record.status = "failed"
            record.diagnostics = list(record.diagnostics or [])
            record.diagnostics.append("forced restore failure")
            inst = loader.lifecycle.get_instance(record.manifest.id)
            if inst is not None:
                inst.activated = False
        return record

    monkeypatch.setattr(loader, "_rollback_reload", _rollback)
    monkeypatch.setattr(loader, "_load_plugin_unlocked", _load_wrap)
    report = await loader.lifecycle.reload(
        "restore-fail",
        new_source=incoming,
    )
    assert not report.ok
    assert report.needs_restart
    assert any("restore" in item for item in report.errors)
    inst = loader.lifecycle.get_instance("restore-fail")
    assert inst is None or inst.activated is False


@pytest.mark.asyncio
async def test_teardown_runtime_cancel_keeps_ledger():
    inst = PluginInstance("cancel-teardown")
    started = asyncio.Event()
    blocker = asyncio.get_running_loop().create_future()

    def _slow():
        started.set()
        return blocker

    inst.record_runtime("slow", teardown=_slow)
    task = asyncio.create_task(inst.teardown_runtime())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inst.state is PluginState.FAILED
    assert inst._runtime
    for entry in inst._runtime:
        entry.teardown = None
    report = await inst.teardown_runtime()
    assert report.quiescent
    assert not inst._runtime


@pytest.mark.asyncio
async def test_dispose_cancel_does_not_mark_disposed():
    inst = PluginInstance("cancel-dispose")
    started = asyncio.Event()
    blocker = asyncio.get_running_loop().create_future()

    def _slow():
        started.set()
        return blocker

    inst.record_runtime("slow", teardown=_slow, kind="custody")
    task = asyncio.create_task(inst.dispose(UnloadMode.UNLOAD))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inst.state is not PluginState.DISPOSED
    assert inst.state is PluginState.FAILED
    assert inst._runtime
    for entry in inst._runtime:
        entry.teardown = None
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert inst.state is PluginState.DISPOSED


@pytest.mark.asyncio
async def test_stop_task_reraises_parent_cancel():
    started = asyncio.Event()

    async def _work():
        started.set()
        await asyncio.Event().wait()

    hosted = asyncio.create_task(_work())
    await asyncio.wait_for(started.wait(), timeout=1)

    async def _stop():
        await stop_task(hosted, "work")

    stopper = asyncio.create_task(_stop())
    await asyncio.sleep(0)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    if not hosted.done():
        hosted.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hosted


@pytest.mark.asyncio
async def test_update_config_cancel_restores_old_when_quiescent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cfg-cancel",
        "api.register_slash_command('old', lambda c, a: None)",
    )
    started = asyncio.Event()
    real_reg = loader.reregister_unlocked
    calls = {"n": 0}

    async def _hang_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            started.set()
            await asyncio.Event().wait()
        return await real_reg(*args, **kwargs)

    monkeypatch.setattr(loader, "reregister_unlocked", _hang_once)
    task = asyncio.create_task(
        loader.lifecycle.update_config("cfg-cancel", {"cmd": "new"}),
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    inst = loader.lifecycle.get_instance("cfg-cancel")
    assert inst is not None
    assert inst.state is not PluginState.DISPOSED
    assert "old" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_update_config_unquiescent_failure_does_not_setup_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    body = (
        "api.register_slash_command(\n"
        "            api.config.get('cmd', 'old'), lambda c, a: None,\n"
        "        )\n"
        "        if api.config.get('boom'):\n"
        "            def _boom():\n"
        "                raise RuntimeError('startup boom')\n"
        "            api.register_startup_hook('boom', _boom, priority=90)"
    )
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cfg-sticky",
        body,
        config={"cmd": "old"},
    )
    teardowns = {"n": 0}
    real_teardown = PluginInstance.teardown_runtime

    async def _counted(self):
        report = await real_teardown(self)
        teardowns["n"] += 1
        if teardowns["n"] >= 2:
            report.quiescent = False
            report.needs_restart = True
            report.clean = False
            self.state = PluginState.FAILED
        return report

    configs: list[dict] = []
    real_reg = loader.reregister_unlocked

    async def _spy(plugin_id, config=None):
        configs.append(dict(config or {}))
        return await real_reg(plugin_id, config)

    monkeypatch.setattr(PluginInstance, "teardown_runtime", _counted)
    monkeypatch.setattr(loader, "reregister_unlocked", _spy)
    report = await loader.lifecycle.update_config(
        "cfg-sticky",
        {"cmd": "new", "boom": True},
    )
    assert not report.ok
    assert report.needs_restart
    assert len(configs) == 1
    names = workspace.plugins.slash_command_registry.names()
    assert not ("old" in names and "new" in names)
    inst = loader.lifecycle.get_instance("cfg-sticky")
    assert inst is not None
    assert inst.state is PluginState.FAILED


@pytest.mark.asyncio
async def test_disable_unquiescent_does_not_persist_or_lie(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    persisted: list[tuple[str, dict]] = []

    def _persist(plugin_id, **kwargs):
        persisted.append((plugin_id, kwargs))

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        _persist,
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "stay-on",
        "api.register_slash_command('ping', lambda c, a: None)",
    )

    async def _busy(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="stay-on",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["channel stop failed"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy)
    report = await loader.lifecycle.set_enabled("stay-on", False)
    assert not report.quiescent
    assert report.needs_restart
    assert loader.get_loaded_plugin("stay-on") is not None
    assert not any(
        plugin_id == "stay-on" and item.get("enabled") is False
        for plugin_id, item in persisted
    )

    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = loader
    client = TestClient(app)
    response = client.post(
        "/api/plugins/stay-on/enabled",
        json={"enabled": False},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["loaded"] is True
    assert detail["needs_restart"] is True
    assert detail["enabled"] is True
    assert detail["quiescent"] is False
    assert loader.get_loaded_plugin("stay-on") is not None
    assert not any(
        plugin_id == "stay-on" and item.get("enabled") is False
        for plugin_id, item in persisted
    )


def _enabled_channel_config(*keys: str):
    channels = SimpleNamespace()
    extra = {}
    for key in keys:
        extra[key] = SimpleNamespace(enabled=True, no_text_debounce=True)
    channels.__pydantic_extra__ = extra
    return SimpleNamespace(channels=channels, show_tool_details=True)


@pytest.mark.asyncio
async def test_failed_register_unquiescent_keeps_module(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr("qwenpaw.plugins.custody.THREAD_STOP_SECONDS", 0.15)
    body = (
        "import time\n"
        "        def _spin():\n"
        "            while True:\n"
        "                time.sleep(0.05)\n"
        "        api.spawn_thread(_spin, 'sticky')\n"
        "        raise RuntimeError('register boom')"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "sticky-reg",
        "sticky-reg",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    setups = {"n": 0}
    real_register = loader._invoke_plugin_register

    async def _count(*args, **kwargs):
        setups["n"] += 1
        return await real_register(*args, **kwargs)

    monkeypatch.setattr(loader, "_invoke_plugin_register", _count)
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert "plugin_sticky_reg" in sys.modules
    inst = loader.lifecycle.get_instance("sticky-reg")
    assert inst is not None
    assert inst.state is PluginState.FAILED
    after = setups["n"]
    report = await loader.lifecycle.reload("sticky-reg")
    assert not report.ok
    assert report.needs_restart
    assert setups["n"] == after
    repaired = await loader.repair_dependencies("sticky-reg")
    assert repaired.status == "failed"
    assert setups["n"] == after
    assert "plugin_sticky_reg" in sys.modules


@pytest.mark.asyncio
async def test_startup_stop_failure_keeps_channel(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    async def _noop_process(_req):
        return None

    workspace = SimpleNamespace(
        agent_id="talk",
        plugins=WorkspacePlugins(),
        _config=_enabled_channel_config("sticky-ch"),
        channel_manager=ChannelManager([]),
    )
    workspace.channel_manager._process = _noop_process
    workspace.channel_manager._workspace = workspace
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    body = (
        "from qwenpaw.app.channels.base import BaseChannel\n"
        "        class _Stuck(BaseChannel):\n"
        "            channel = 'sticky-ch'\n"
        "            uses_manager_queue = False\n"
        "            def __init__(self, *args, **kwargs):\n"
        "                self.alive = True\n"
        "                self._enqueue = None\n"
        "            @classmethod\n"
        "            def from_config(cls, **kwargs):\n"
        "                return cls()\n"
        "            async def start(self):\n"
        "                self.alive = True\n"
        "            async def stop(self):\n"
        "                raise RuntimeError('still connected')\n"
        "            def set_enqueue(self, cb):\n"
        "                self._enqueue = cb\n"
        "            def set_workspace(self, ws, reg):\n"
        "                return None\n"
        "        api.register_channel(_Stuck)\n"
        "        def _boom():\n"
        "            raise RuntimeError('startup boom')\n"
        "        api.register_startup_hook('boom', _boom, priority=90)"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "sticky-ch-plug",
        "sticky-ch-plug",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )

    def _ch_registry():
        reg = fresh_registry.get_channel_registration("sticky-ch")
        if reg is None:
            return {}
        return {"sticky-ch": reg.channel_class}

    with (
        patch(
            "qwenpaw.plugins.workspace_projector.get_available_channels",
            return_value=("sticky-ch",),
        ),
        patch(
            "qwenpaw.app.channels.manager.get_channel_registry",
            _ch_registry,
        ),
        patch(
            "qwenpaw.app.channels.manager.get_available_channels",
            return_value=("sticky-ch",),
        ),
    ):
        record = await loader.load_plugin(manifest, installed)
        assert record.status == "failed"
        assert "plugin_sticky_ch_plug" in sys.modules
        inst = loader.lifecycle.get_instance("sticky-ch-plug")
        assert inst is not None
        assert inst.state is PluginState.FAILED
        assert workspace.channel_manager.channels
        keys = [ch.channel for ch in workspace.channel_manager.channels]
        assert "sticky-ch" in keys
        setups = {"n": 0}
        real_register = loader._invoke_plugin_register

        async def _count(*args, **kwargs):
            setups["n"] += 1
            return await real_register(*args, **kwargs)

        monkeypatch.setattr(loader, "_invoke_plugin_register", _count)
        report = await loader.lifecycle.reload("sticky-ch-plug")
        assert not report.ok
        assert report.needs_restart
        assert setups["n"] == 0
        assert workspace.channel_manager.channels


@pytest.mark.asyncio
async def test_failed_register_undoes_this_txn_provision_setup(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "escape-once"
    body = (
        "from pathlib import Path\n"
        "        import shutil\n"
        f"        dest = Path({str(dest)!r})\n"
        "        def _setup(_dest=dest):\n"
        "            _dest.mkdir()\n"
        "            (_dest / 'note.md').write_text('v1\\n')\n"
        "        def _teardown(_dest=dest):\n"
        "            if _dest.exists():\n"
        "                shutil.rmtree(_dest)\n"
        "        api.provision('escape-dir', _setup, _teardown)\n"
        "        raise RuntimeError('register boom')"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "esc-boom",
        "esc-boom",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert not dest.exists()
    rows = load_inventory("esc-boom").get("provisions") or []
    assert not any(row.get("desc") == "escape-dir" for row in rows)


@pytest.mark.asyncio
async def test_commit_persist_then_error_does_not_rollback(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    factory = tmp_path / "factory-commit"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "migrated-commit"
    body = (
        "from pathlib import Path\n"
        f"        src = Path({str(factory)!r})\n"
        f"        dest = Path({str(dest)!r})\n"
        "        api.provision_files(src, dest, '1.0.0')\n"
        "        (src / 'note.md').write_text('v2\\n')\n"
        "        api.provision_files(src, dest, '2.0.0')\n"
        "        api.register_slash_command('ping', lambda c, a: None)"
    )
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "commit-half",
        body,
        activate=False,
    )
    loc = load_inventory("commit-half")["locations"][str(dest)]
    assert loc.get("migrating")
    from qwenpaw.plugins import provision as provision_mod

    calls = {"n": 0}
    real_save = provision_mod.save_inventory

    def _save(plugin_id, data):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("second save boom")
        return real_save(plugin_id, data)

    monkeypatch.setattr(provision_mod, "save_inventory", _save)
    await loader.activate_plugin_unlocked("commit-half")
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    record = loader.get_loaded_plugin("commit-half")
    assert record is not None
    assert record.status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()
    saved = json.loads(
        provision_mod.inventory_path("commit-half").read_text(
            encoding="utf-8",
        ),
    )
    marker = (
        (saved.get("locations") or {})
        .get(str(dest), {})
        .get(
            "migrating",
        )
    )
    assert marker is None or marker.get("status") == "committed"


@pytest.mark.asyncio
async def test_http_unload_unquiescent_is_409(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "stay-loaded",
        "api.register_slash_command('ping', lambda c, a: None)",
    )

    async def _busy(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="stay-loaded",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["channel stop failed"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy)
    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = loader
    client = TestClient(app)
    response = client.post("/api/plugins/stay-loaded/unload")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["loaded"] is True
    assert detail["quiescent"] is False
    assert detail["needs_restart"] is True
    assert loader.get_loaded_plugin("stay-loaded") is not None


@pytest.mark.asyncio
async def test_http_update_config_unquiescent_is_409(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cfg-http",
        "api.register_slash_command('old', lambda c, a: None)",
        config={"cmd": "old"},
    )

    async def _busy(self):
        self.state = PluginState.FAILED
        return UnloadReport(
            plugin_id=self.plugin_id,
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["teardown stuck"],
        )

    monkeypatch.setattr(PluginInstance, "teardown_runtime", _busy)
    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = loader
    client = TestClient(app)
    response = client.put(
        "/api/plugins/cfg-http/config",
        json={"config": {"cmd": "new"}},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["needs_restart"] is True
    assert detail["quiescent"] is False
    assert detail["errors"]


@pytest.mark.asyncio
async def test_ensure_instance_replaces_disposed_generation():
    life = PluginLifecycle(SimpleNamespace())
    inst = life.ensure_instance("gen-p", generation=1)
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert inst.state is PluginState.DISPOSED
    inst.mark_failed("should not revive")
    assert inst.state is PluginState.DISPOSED
    fresh = life.ensure_instance("gen-p", generation=7)
    assert fresh is not inst
    assert fresh.generation == 7
    assert fresh.state is not PluginState.DISPOSED


def test_ensure_instance_refuses_other_generation():
    life = PluginLifecycle(SimpleNamespace())
    inst = life.ensure_instance("gen-q", generation=3)
    inst.mark_failed("boom")
    with pytest.raises(RuntimeError, match="cannot be reused"):
        life.ensure_instance("gen-q", generation=4)
    assert life.get_instance("gen-q") is inst
    assert inst.generation == 3


@pytest.mark.asyncio
async def test_install_after_load_error_does_not_unload_active(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    incoming = _write_plugin(
        tmp_path / "incoming-keep-after",
        "keep-after",
        body="api.register_slash_command('ping', lambda c, a: None)",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [_slash_workspace()],
    )

    def _after(_record):
        raise RuntimeError("after boom")

    with pytest.raises(RuntimeError, match="after boom"):
        await loader.load_plugin_from_path(incoming, after_load=_after)
    record = loader.get_loaded_plugin("keep-after")
    assert record is not None
    assert record.status == "active"
    inst = loader.lifecycle.get_instance("keep-after")
    assert inst is not None
    assert inst.activated
    assert (tmp_path / "plugins" / "keep-after").is_dir()

    def _cancel(_record):
        raise asyncio.CancelledError

    incoming2 = _write_plugin(
        tmp_path / "incoming-keep-cancel",
        "keep-cancel",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    with pytest.raises(asyncio.CancelledError):
        await loader.load_plugin_from_path(incoming2, after_load=_cancel)
    record2 = loader.get_loaded_plugin("keep-cancel")
    assert record2 is not None
    assert record2.status == "active"
    assert (tmp_path / "plugins" / "keep-cancel").is_dir()


@pytest.mark.asyncio
async def test_register_cancel_records_failed_and_refuses_setup(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr("qwenpaw.plugins.custody.THREAD_STOP_SECONDS", 0.15)
    marker = tmp_path / "ready-cancel.txt"
    body = (
        "import asyncio, pathlib, time\n"
        "        def _spin():\n"
        "            while True:\n"
        "                time.sleep(0.05)\n"
        "        api.spawn_thread(_spin, 'sticky')\n"
        f"        pathlib.Path({str(marker)!r}).write_text('ready')\n"
        "        return asyncio.get_running_loop().create_future()"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "sticky-cancel",
        "sticky-cancel",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    setups = {"n": 0}
    real_register = loader._invoke_plugin_register

    async def _count(*args, **kwargs):
        setups["n"] += 1
        return await real_register(*args, **kwargs)

    monkeypatch.setattr(loader, "_invoke_plugin_register", _count)
    task = asyncio.create_task(loader.load_plugin(manifest, installed))
    for _ in range(50):
        if marker.is_file():
            break
        await asyncio.sleep(0.02)
    assert marker.is_file()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = loader.get_loaded_plugin("sticky-cancel")
    assert record is not None
    assert record.status == "failed"
    assert any("needs_restart" in item for item in record.diagnostics)
    assert "plugin_sticky_cancel" in sys.modules
    inst = loader.lifecycle.get_instance("sticky-cancel")
    assert inst is not None
    assert inst.state is PluginState.FAILED
    assert inst.has_runtime_ledger()
    after = setups["n"]
    again = await loader.load_plugin(manifest, installed)
    assert again.status == "failed"
    assert setups["n"] == after
    with pytest.raises(RuntimeError, match="not quiescent"):
        inst.refuse_unquiescent_reregister()


@pytest.mark.asyncio
async def test_rollback_reload_skips_dir_swap_without_record(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    old = _write_plugin(
        tmp_path / "plugins" / "swap-me",
        "swap-me",
        body="pass",
    )
    backup = _write_plugin(
        tmp_path / "backup-swap-me",
        "swap-me",
        body="api.register_slash_command('old', lambda c, a: None)",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    inst = loader.lifecycle.ensure_instance("swap-me", generation=2)
    inst.record_runtime("thread", teardown=lambda: None)
    inst.mark_failed("cancelled")
    assert loader.get_loaded_plugin("swap-me") is None
    old_text = (old / "main.py").read_text(encoding="utf-8")
    manifest = PluginManifest.from_dict(
        json.loads((old / "plugin.json").read_text(encoding="utf-8")),
    )
    report = await loader._rollback_reload(
        "swap-me",
        old,
        None,
        None,
        backup,
        incoming_manifest=manifest,
        in_place=False,
        generation=1,
    )
    assert not report.ok
    assert report.needs_restart
    assert any("unquiescent" in item for item in report.errors)
    assert (old / "main.py").read_text(encoding="utf-8") == old_text
    assert backup.is_dir()
    assert inst.state is PluginState.FAILED


@pytest.mark.asyncio
async def test_provision_setup_none_does_not_teardown_on_fail(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "cloudpaw-ws"
    dest.mkdir()
    (dest / "keep.txt").write_text("user-data\n", encoding="utf-8")
    body = (
        "from pathlib import Path\n"
        "        import shutil\n"
        f"        dest = Path({str(dest)!r})\n"
        "        def _teardown(_dest=dest):\n"
        "            if _dest.exists():\n"
        "                shutil.rmtree(_dest)\n"
        "        api.provision(\n"
        "            'cloudpaw_agents', None, _teardown,\n"
        "            kind='cloudpaw_agents',\n"
        "        )\n"
        "        raise RuntimeError('register boom')"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "cloud-first",
        "cloud-first",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert dest.is_dir()
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "user-data\n"
    rows = load_inventory("cloud-first").get("provisions") or []
    assert not any(row.get("desc") == "cloudpaw_agents" for row in rows)

    dest2 = tmp_path / "cloudpaw-ws-activate"
    dest2.mkdir()
    (dest2 / "keep.txt").write_text("user-data\n", encoding="utf-8")
    body2 = (
        "from pathlib import Path\n"
        "        import shutil\n"
        f"        dest = Path({str(dest2)!r})\n"
        "        def _teardown(_dest=dest):\n"
        "            if _dest.exists():\n"
        "                shutil.rmtree(_dest)\n"
        "        api.provision(\n"
        "            'cloudpaw_agents', None, _teardown,\n"
        "            kind='cloudpaw_agents',\n"
        "        )\n"
        "        def _boom():\n"
        "            raise RuntimeError('startup boom')\n"
        "        api.register_startup_hook('boom', _boom, priority=90)"
    )
    loader2, _workspace, _installed = await _load(
        tmp_path / "activate-cloud",
        fresh_registry,
        "cloud-act",
        body2,
    )
    record2 = loader2.get_loaded_plugin("cloud-act")
    assert record2 is not None
    assert record2.status == "failed"
    assert dest2.is_dir()
    assert (dest2 / "keep.txt").read_text(encoding="utf-8") == "user-data\n"


@pytest.mark.asyncio
async def test_boot_recover_after_activate_keeps_new_version(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    """Boot recover after swap+activate must keep the new tree.

    Cleanup is skipped so backup remains, as after a crash. Activate
    persists the update marker before it returns. The test then leaves
    ``status=prepared`` (the leftover field the crash window used to
    expose); ``recover_interrupted_updates`` must still keep the new
    directory and must not restore the provision inventory.
    """
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "prov-boot"
    body = (
        "from pathlib import Path\n"
        "        api.provision_files(\n"
        "            Path(__file__).resolve().parent / 'factory',\n"
        f"            Path({str(dest)!r}),\n"
        "            '1.0.0',\n"
        "        )\n"
        "        api.register_slash_command('ping', lambda c, a: None)"
    )
    root = tmp_path / "plugins" / "boot-rec"
    _write_plugin(root, "boot-rec", body=body)
    (root / "factory").mkdir()
    (root / "factory" / "note.md").write_text("v1\n", encoding="utf-8")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "boot-rec",
        body,
    )
    incoming = _write_plugin(
        tmp_path / "incoming-boot-rec",
        "boot-rec",
        body=(
            "from pathlib import Path\n"
            "        api.provision_files(\n"
            "            Path(__file__).resolve().parent / 'factory',\n"
            f"            Path({str(dest)!r}),\n"
            "            '2.0.0',\n"
            "        )\n"
            "        api.register_slash_command('pong', lambda c, a: None)"
        ),
    )
    (incoming / "factory").mkdir()
    (incoming / "factory" / "note.md").write_text("v2\n", encoding="utf-8")
    meta = json.loads((incoming / "plugin.json").read_text(encoding="utf-8"))
    meta["version"] = "2.0.0"
    (incoming / "plugin.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    (incoming / "v2.txt").write_text("v2", encoding="utf-8")

    async def _skip_finish(_plugin_id, _swapped):
        return []

    monkeypatch.setattr(loader, "_finish_committed_reload", _skip_finish)
    report = await loader.lifecycle.reload("boot-rec", new_source=incoming)
    assert report.ok
    assert update_marker_status("boot-rec") == STATUS_COMMITTED
    payload = json.loads(marker_path("boot-rec").read_text(encoding="utf-8"))
    backup = Path(payload["backup_path"])
    assert backup.exists()
    payload["status"] = STATUS_PREPARED
    marker_path("boot-rec").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    recover_interrupted_updates()
    assert not backup.exists()
    assert (installed / "v2.txt").read_text(encoding="utf-8") == "v2"
    assert "pong" in (installed / "main.py").read_text(encoding="utf-8")
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    saved = load_inventory("boot-rec")
    loc = (saved.get("locations") or {}).get(str(dest))
    assert loc is not None
    assert loc.get("version") == "2.0.0"
    assert loc.get("owned") is True
    assert "pong" in workspace.plugins.slash_command_registry.names()


def test_boot_recover_committed_update_keeps_prepared_provision(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    target = tmp_path / "plugins" / "half-commit"
    target.mkdir(parents=True)
    (target / "main.py").write_text("NEW\n", encoding="utf-8")
    backup = tmp_path / "plugins" / "half-commit.bak"
    backup.mkdir()
    (backup / "main.py").write_text("OLD\n", encoding="utf-8")
    write_updating_marker(
        "half-commit",
        backup_path=backup,
        target_path=target,
    )
    mark_update_committed("half-commit")
    dest = tmp_path / "skills-half"
    dest.mkdir()
    (dest / "note.md").write_text("v2\n", encoding="utf-8")
    dest_backup = tmp_path / "skills-half.bak"
    dest_backup.mkdir()
    (dest_backup / "note.md").write_text("v1\n", encoding="utf-8")
    save_inventory(
        "half-commit",
        {
            "plugin_id": "half-commit",
            "locations": {
                str(dest): {
                    "src": str(tmp_path / "factory"),
                    "version": "2.0.0",
                    "owned": True,
                    "files": {"note.md": {"factory_hash": "new"}},
                    "migrating": {
                        "status": "prepared",
                        "backup_path": str(dest_backup),
                        "target_version": "2.0.0",
                        "prev_version": "1.0.0",
                        "prev_factory_hashes": {"note.md": "old"},
                    },
                },
            },
            "tools": {},
            "provisions": [],
        },
    )
    recover_interrupted_updates()
    recover_migrating_inventory()
    assert (target / "main.py").read_text(encoding="utf-8") == "NEW\n"
    assert not backup.exists()
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    assert not dest_backup.exists()
    loc = load_inventory("half-commit")["locations"][str(dest)]
    assert loc.get("version") == "2.0.0"
    assert loc.get("migrating") is None
    assert loc.get("owned") is True


@pytest.mark.asyncio
async def test_provision_create_mid_copy_retries_owned(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "created-skills"
    plugin_id = "half-create"
    body = (
        "from pathlib import Path\n"
        "        api.provision_files(\n"
        "            Path(__file__).resolve().parent / 'factory',\n"
        f"            Path({str(dest)!r}),\n"
        "            '1.0.0',\n"
        "        )\n"
        "        api.register_slash_command('ready', lambda c, a: None)"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=body,
    )
    factory = installed / "factory"
    factory.mkdir()
    (factory / "a.txt").write_text("A\n", encoding="utf-8")
    (factory / "b.txt").write_text("B\n", encoding="utf-8")

    from qwenpaw.plugins import provision as provision_mod

    real_copy = provision_mod.shutil.copy2

    def _copy(src, dst, *args, **kwargs):
        if Path(src).name == "b.txt":
            raise OSError("disk full")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(provision_mod.shutil, "copy2", _copy)
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert not dest.exists()
    loc = (load_inventory(plugin_id).get("locations") or {}).get(str(dest))
    assert loc is None
    monkeypatch.setattr(provision_mod.shutil, "copy2", real_copy)
    await loader.unload_plugin(plugin_id, delete_files=False)
    record2 = await loader.load_plugin(manifest, installed)
    assert record2.status == "active"
    assert (dest / "a.txt").read_text(encoding="utf-8") == "A\n"
    assert (dest / "b.txt").read_text(encoding="utf-8") == "B\n"
    loc = load_inventory(plugin_id)["locations"][str(dest)]
    assert loc.get("owned") is True
    await loader.unload_plugin(
        plugin_id,
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert not dest.exists()
    assert not inventory_path(plugin_id).is_file()


@pytest.mark.asyncio
async def test_http_delete_uninstall_unquiescent_is_409(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "stay-del",
        "api.register_slash_command('ping', lambda c, a: None)",
    )

    async def _busy(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="stay-del",
            mode=UnloadMode.UNINSTALL,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["channel stop failed"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy)
    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = loader
    client = TestClient(app)
    response = client.delete("/api/plugins/stay-del")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["loaded"] is True
    assert detail["quiescent"] is False
    assert detail["needs_restart"] is True
    assert loader.get_loaded_plugin("stay-del") is not None


@pytest.mark.asyncio
async def test_http_delete_pawapp_unquiescent_is_409(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.app.routers.pawapps._get_apps_dir",
        lambda: tmp_path / "plugins",
    )
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "stay-app",
        "api.register_slash_command('ping', lambda c, a: None)",
    )

    async def _busy(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="stay-app",
            mode=UnloadMode.UNINSTALL,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["channel stop failed"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy)
    from qwenpaw.app.routers.pawapps import router as pawapps_router

    app = FastAPI()
    app.include_router(pawapps_router, prefix="/api")
    app.state.plugin_loader = loader
    client = TestClient(app)
    response = client.delete("/api/pawapps/stay-app")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["loaded"] is True
    assert detail["quiescent"] is False
    assert detail["needs_restart"] is True

    async def _memory(*_args, **_kwargs):
        raise RuntimeError("memory backend is in use")

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _memory)
    memory_resp = client.delete("/api/pawapps/stay-app")
    assert memory_resp.status_code == 409
    memory_detail = memory_resp.json()["detail"]
    assert memory_detail["needs_restart"] is True
    assert memory_detail["quiescent"] is False


@pytest.mark.asyncio
async def test_unloaded_force_respects_owns_commit(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "idle-owned",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    await loader.unload_plugin("idle-owned", delete_files=False)
    assert loader.get_loaded_plugin("idle-owned") is None
    loader.lifecycle.delegate.owns_commit = lambda _plugin_id: False
    staging = _write_plugin(
        tmp_path / "staging-idle-owned",
        "idle-owned",
        body="api.register_slash_command('nope', lambda c, a: None)",
    )
    with pytest.raises(RuntimeError, match="not owned"):
        await loader.load_plugin_from_path(staging, force=True)
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert loader.get_loaded_plugin("idle-owned") is None


def test_register_hooks_guard_before_registry(fresh_registry):
    from qwenpaw.plugins.api import PluginApi

    inst = PluginInstance("guard-hooks")
    inst.state = PluginState.UNLOADING
    api = PluginApi("guard-hooks", config={})
    api.set_registry(fresh_registry)
    api.bind_instance(inst)
    with pytest.raises(RuntimeError, match="unloading"):
        api.register_startup_hook("late-start", lambda: None)
    assert all(
        hook.hook_name != "late-start"
        for hook in fresh_registry.get_startup_hooks()
    )
    with pytest.raises(RuntimeError, match="unloading"):
        api.register_workspace_created_hook("late-ws", lambda _info: None)
    assert all(
        hook.hook_name != "late-ws"
        for hook in fresh_registry.get_workspace_created_hooks()
    )
    inst.state = PluginState.DISPOSED
    with pytest.raises(RuntimeError, match="disposed"):
        api.register_prompt_section(
            "late-prompt",
            "workspace",
            lambda _agent: "",
        )
    assert all(
        section.name != "late-prompt"
        for section in fresh_registry.get_prompt_sections()
    )


def test_schedule_workspace_intent_guards_before_intend(fresh_registry):
    from qwenpaw.plugins.api import PluginApi

    projector = WorkspaceProjector(live_workspaces=lambda: [])
    fresh_registry.projector = projector
    inst = PluginInstance("guard-intent")
    inst.state = PluginState.UNLOADING
    api = PluginApi("guard-intent", config={})
    api.set_registry(fresh_registry)
    api.bind_instance(inst)
    with pytest.raises(RuntimeError, match="unloading"):
        api._schedule_workspace_intent(
            "slash_command",
            "late",
            apply=lambda _workspace: None,
            revoke=lambda _workspace, _token=None: None,
        )
    assert projector._intents == []


@pytest.mark.asyncio
async def test_unloaded_force_keeps_old_dir_on_copy_failure(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "idle-copy",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    await loader.unload_plugin("idle-copy", delete_files=False)
    assert loader.get_loaded_plugin("idle-copy") is None
    staging = _write_plugin(
        tmp_path / "staging-idle-copy",
        "idle-copy",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    (staging / "a.txt").write_text("new-a\n", encoding="utf-8")
    (staging / "b.txt").write_text("new-b\n", encoding="utf-8")
    real_copytree = shutil.copytree

    def _copytree(src, dst, *args, **kwargs):
        def _copy(src_file, dst_file, *a, **k):
            if Path(src_file).name == "b.txt":
                raise OSError("injected copy fail on b.txt")
            return shutil.copy2(src_file, dst_file, *a, **k)

        patched = dict(kwargs)
        patched["copy_function"] = _copy
        return real_copytree(src, dst, *args, **patched)

    monkeypatch.setattr(shutil, "copytree", _copytree)
    with pytest.raises(OSError, match="injected copy fail"):
        await loader.load_plugin_from_path(staging, force=True)
    assert (installed / "plugin.json").exists()
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert installed.is_dir()
    assert any(installed.iterdir())
    recover_interrupted_updates()
    assert (installed / "plugin.json").exists()
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert not (marker_path("idle-copy").is_file()) or (
        update_marker_status("idle-copy") == STATUS_PREPARED
        and (installed / "plugin.json").exists()
    )
    assert loader.get_loaded_plugin("idle-copy") is None


@pytest.mark.asyncio
async def test_unloaded_force_permission_error_keeps_marker(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "idle-lock",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    await loader.unload_plugin("idle-lock", delete_files=False)
    staging = _write_plugin(
        tmp_path / "staging-idle-lock",
        "idle-lock",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    def _boom(*_args, **_kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(shutil, "copytree", _boom)
    with pytest.raises(RuntimeError, match="restart required"):
        await loader.load_plugin_from_path(staging, force=True)
    assert marker_path("idle-lock").is_file()
    assert (installed / "plugin.json").exists()
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text


@pytest.mark.asyncio
async def test_failed_register_unquiescent_keeps_this_txn_create(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr("qwenpaw.plugins.custody.THREAD_STOP_SECONDS", 0.15)
    dest = tmp_path / "created-sticky"
    flag = tmp_path / "stop-sticky"
    factory = tmp_path / "factory-sticky"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    body = (
        "from pathlib import Path\n"
        "        import time\n"
        f"        dest = Path({str(dest)!r})\n"
        f"        api.provision_files(Path({str(factory)!r}), dest, '1.0.0')\n"
        "        def _spin():\n"
        f"            while not Path({str(flag)!r}).exists():\n"
        "                time.sleep(0.02)\n"
        "        api.spawn_thread(_spin, 'sticky')\n"
        "        raise RuntimeError('register boom')"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "sticky-create",
        "sticky-create",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert dest.exists()
    inst = loader.lifecycle.get_instance("sticky-create")
    assert inst is not None
    assert inst.state is PluginState.FAILED
    assert any(entry.desc.startswith("thread:") for entry in inst._runtime)
    assert "needs_restart" in inst.diagnostics
    assert loader.lifecycle.get_instance("sticky-create") is inst
    flag.write_text("stop\n", encoding="utf-8")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not any(
            thread.is_alive() and thread.name.endswith(":sticky")
            for thread in threading.enumerate()
        ):
            break
        time.sleep(0.02)
    report = await loader.unload_plugin("sticky-create", delete_files=False)
    assert report.quiescent
    assert not dest.exists()


@pytest.mark.asyncio
async def test_activate_failure_unquiescent_keeps_migrate_dest(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr("qwenpaw.plugins.custody.THREAD_STOP_SECONDS", 0.15)
    dest = tmp_path / "migrated-keep"
    factory_v1 = tmp_path / "factory-v1"
    factory_v1.mkdir()
    (factory_v1 / "note.md").write_text("v1\n", encoding="utf-8")
    factory_v2 = tmp_path / "factory-v2"
    factory_v2.mkdir()
    (factory_v2 / "note.md").write_text("v2\n", encoding="utf-8")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "mig-keep",
        (
            "from pathlib import Path\n"
            f"        api.provision_files(Path({str(factory_v1)!r}), "
            f"Path({str(dest)!r}), '1.0.0')"
        ),
    )
    assert (dest / "note.md").read_text(encoding="utf-8") == "v1\n"
    await loader.unload_plugin("mig-keep", delete_files=False)
    _write_plugin(
        installed,
        "mig-keep",
        body=(
            "from pathlib import Path\n"
            "        import time\n"
            f"        api.provision_files(Path({str(factory_v2)!r}), "
            f"Path({str(dest)!r}), '2.0.0')\n"
            "        def _spin():\n"
            "            while True:\n"
            "                time.sleep(0.05)\n"
            "        api.spawn_thread(_spin, 'sticky')\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    inst = loader.lifecycle.get_instance("mig-keep")
    assert inst is not None
    assert inst.state is PluginState.FAILED
    assert "needs_restart" in inst.diagnostics
    loc = (load_inventory("mig-keep").get("locations") or {}).get(str(dest))
    migrating = (loc or {}).get("migrating") or {}
    assert migrating
    assert migrating.get("status") != "committed"


@pytest.mark.asyncio
async def test_control_command_projects_to_live_channel_manager(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.runtime.commands.control import unregister_command

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cmd-live",
        _control_body("plugincmd"),
    )
    manager = workspace.channel_manager
    assert manager.is_control_command("/plugincmd")
    await loader.unload_plugin("cmd-live", delete_files=False)
    assert not manager.is_control_command("/plugincmd")
    unregister_command("plugincmd", owner="cmd-live")


@pytest.mark.asyncio
async def test_effect_teardown_runtime_error_is_not_quiescent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "effect-hang",
        (
            "def _boom():\n"
            "            raise RuntimeError('effect still running')\n"
            "        api.effect('hang', None, _boom)"
        ),
    )
    inst = loader.lifecycle.get_instance("effect-hang")
    assert inst is not None
    setups = {"n": 0}
    real_register = loader._invoke_plugin_register

    async def _count(*args, **kwargs):
        setups["n"] += 1
        return await real_register(*args, **kwargs)

    monkeypatch.setattr(loader, "_invoke_plugin_register", _count)
    report = await loader.unload_plugin("effect-hang", delete_files=False)
    assert report.quiescent is False
    assert report.needs_restart is True
    assert loader.lifecycle.get_instance("effect-hang") is inst
    assert inst.has_runtime_ledger()
    assert "effect-hang" in loader.get_all_loaded_plugins()
    reload_report = await loader.lifecycle.reload("effect-hang")
    assert not reload_report.ok
    assert reload_report.needs_restart
    assert setups["n"] == 0
    cfg = await loader.lifecycle.update_config(
        "effect-hang",
        {"touched": True},
    )
    assert not cfg.ok
    assert cfg.needs_restart
    assert setups["n"] == 0


@pytest.mark.asyncio
async def test_unloaded_force_unquiescent_activate_keeps_new_dir(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    async def _noop_process(_req):
        return None

    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "force-ch",
        "pass",
    )
    (installed / "v1.txt").write_text("v1\n", encoding="utf-8")
    await loader.unload_plugin("force-ch", delete_files=False)
    workspace._config = _enabled_channel_config("force-ch")
    workspace.channel_manager = ChannelManager([])
    workspace.channel_manager._process = _noop_process
    workspace.channel_manager._workspace = workspace
    staging = _write_plugin(
        tmp_path / "staging-force-ch",
        "force-ch",
        body=(
            "from qwenpaw.app.channels.base import BaseChannel\n"
            "        class _Stuck(BaseChannel):\n"
            "            channel = 'force-ch'\n"
            "            uses_manager_queue = False\n"
            "            def __init__(self, *args, **kwargs):\n"
            "                self.alive = True\n"
            "                self._enqueue = None\n"
            "            @classmethod\n"
            "            def from_config(cls, **kwargs):\n"
            "                return cls()\n"
            "            async def start(self):\n"
            "                self.alive = True\n"
            "            async def stop(self):\n"
            "                raise RuntimeError('still connected')\n"
            "            def set_enqueue(self, cb):\n"
            "                self._enqueue = cb\n"
            "            def set_workspace(self, ws, reg):\n"
            "                return None\n"
            "        api.register_channel(_Stuck)\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom, priority=90)"
        ),
    )
    (staging / "v2.txt").write_text("v2\n", encoding="utf-8")

    def _ch_registry():
        reg = fresh_registry.get_channel_registration("force-ch")
        if reg is None:
            return {}
        return {"force-ch": reg.channel_class}

    with (
        patch(
            "qwenpaw.plugins.workspace_projector.get_available_channels",
            return_value=("force-ch",),
        ),
        patch(
            "qwenpaw.app.channels.manager.get_channel_registry",
            _ch_registry,
        ),
        patch(
            "qwenpaw.app.channels.manager.get_available_channels",
            return_value=("force-ch",),
        ),
    ):
        with pytest.raises(RuntimeError, match="startup boom"):
            await loader.load_plugin_from_path(staging, force=True)
    assert (installed / "v2.txt").exists()
    assert not (installed / "v1.txt").exists()
    marker = json.loads(marker_path("force-ch").read_text(encoding="utf-8"))
    backup = Path(marker["backup_path"])
    assert backup.is_dir()
    assert (backup / "v1.txt").read_text(encoding="utf-8") == "v1\n"
    assert marker_path("force-ch").is_file()
    inst = loader.lifecycle.get_instance("force-ch")
    assert inst is not None
    assert inst.state is PluginState.FAILED
    assert inst.has_runtime_ledger()
    assert workspace.channel_manager.channels
    assert "force-ch" in [
        ch.channel for ch in workspace.channel_manager.channels
    ]


@pytest.mark.asyncio
async def test_commit_migrations_failure_keeps_new_service(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-commit",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-svc-commit",
        "svc-commit",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    def _boom(_plugin_id):
        raise RuntimeError("commit boom")

    monkeypatch.setattr(
        "qwenpaw.plugins.provision.commit_migrations",
        _boom,
    )
    report = await loader.lifecycle.reload(
        "svc-commit",
        new_source=incoming,
    )
    assert report.ok
    assert report.needs_restart
    assert "pong" in workspace.plugins.slash_command_registry.names()
    assert "ping" not in workspace.plugins.slash_command_registry.names()
    assert "pong" in (installed / "main.py").read_text(encoding="utf-8")
    assert "ping" not in (installed / "main.py").read_text(encoding="utf-8")
    inst = loader.lifecycle.get_instance("svc-commit")
    assert inst is not None
    assert inst.activated
    record = loader.get_loaded_plugin("svc-commit")
    assert record is not None
    assert record.status == "active"


@pytest.mark.asyncio
async def test_commit_migrations_failure_survives_boot_recover(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "prov-commit-boot"
    factory_v1 = tmp_path / "factory-commit-v1"
    factory_v1.mkdir()
    (factory_v1 / "note.md").write_text("v1\n", encoding="utf-8")
    factory_v2 = tmp_path / "factory-commit-v2"
    factory_v2.mkdir()
    (factory_v2 / "note.md").write_text("v2\n", encoding="utf-8")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-boot",
        (
            "from pathlib import Path\n"
            f"        api.provision_files(Path({str(factory_v1)!r}), "
            f"Path({str(dest)!r}), '1.0.0')\n"
            "        api.register_slash_command('ping', lambda c, a: None)"
        ),
    )
    assert (dest / "note.md").read_text(encoding="utf-8") == "v1\n"
    incoming = _write_plugin(
        tmp_path / "incoming-svc-boot",
        "svc-boot",
        body=(
            "from pathlib import Path\n"
            f"        api.provision_files(Path({str(factory_v2)!r}), "
            f"Path({str(dest)!r}), '2.0.0')\n"
            "        api.register_slash_command('pong', lambda c, a: None)"
        ),
    )

    def _boom(_plugin_id):
        raise RuntimeError("commit boom")

    monkeypatch.setattr(
        "qwenpaw.plugins.provision.commit_migrations",
        _boom,
    )
    report = await loader.lifecycle.reload(
        "svc-boot",
        new_source=incoming,
    )
    assert report.ok
    assert report.needs_restart
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    assert "pong" in workspace.plugins.slash_command_registry.names()
    loc = (load_inventory("svc-boot").get("locations") or {}).get(str(dest))
    migrating = (loc or {}).get("migrating") or {}
    assert not migrating or migrating.get("status") == "committed"
    recover_interrupted_updates()
    recover_migrating_inventory()
    assert (dest / "note.md").read_text(encoding="utf-8") == "v2\n"
    assert "pong" in (installed / "main.py").read_text(encoding="utf-8")
    loc = (load_inventory("svc-boot").get("locations") or {}).get(str(dest))
    assert loc is not None
    assert loc.get("version") == "2.0.0"
    leftover = loc.get("migrating") or {}
    assert leftover.get("status") != "prepared"
    assert not leftover or leftover.get("status") == "committed"


@pytest.mark.asyncio
async def test_finish_committed_keeps_marker_if_prepared_commit_fails(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    target = tmp_path / "plugins" / "keep-mark"
    target.mkdir(parents=True)
    (target / "main.py").write_text("NEW\n", encoding="utf-8")
    backup = tmp_path / "plugins" / "keep-mark.bak"
    backup.mkdir()
    (backup / "main.py").write_text("OLD\n", encoding="utf-8")
    write_updating_marker(
        "keep-mark",
        backup_path=backup,
        target_path=target,
    )
    mark_update_committed("keep-mark")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])

    def _boom(_plugin_id):
        raise RuntimeError("inventory full")

    monkeypatch.setattr(
        "qwenpaw.plugins.provision.commit_prepared_migrations",
        _boom,
    )
    errors = await loader._finish_committed_reload("keep-mark", backup)
    assert errors
    assert marker_path("keep-mark").is_file()
    assert update_marker_status("keep-mark") == STATUS_COMMITTED
    assert backup.exists()
    assert (target / "main.py").read_text(encoding="utf-8") == "NEW\n"


@pytest.mark.asyncio
async def test_unload_keeps_post_activate_workspace_create(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.provision import commit_migrations

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    first = tmp_path / "first-skill"
    factory = tmp_path / "factory-skill"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "ws-keep",
        (
            "from pathlib import Path\n"
            f"        api.provision_files(Path({str(factory)!r}), "
            f"Path({str(first)!r}), '1.0.0')\n"
            "        api.register_slash_command('ping', lambda c, a: None)"
        ),
    )
    inst = loader.lifecycle.get_instance("ws-keep")
    assert inst is not None
    assert inst.activated
    dest = tmp_path / "new-ws-skill"
    later = tmp_path / "later-factory"
    later.mkdir()
    (later / "note.md").write_text("ws\n", encoding="utf-8")
    api = PluginApi("ws-keep", config={}, manifest={"id": "ws-keep"})
    api.bind_instance(inst)
    assert api.provision_files(later, dest, "1.0.0") == "create"
    commit_migrations("ws-keep")
    assert dest.exists()
    assert inst.created_dests() == []
    report = await loader.unload_plugin("ws-keep", delete_files=False)
    assert report.quiescent
    assert dest.exists()
    assert first.exists()
    loc = (load_inventory("ws-keep").get("locations") or {}).get(str(dest))
    assert loc is not None
    assert loc.get("owned") is True


@pytest.mark.asyncio
async def test_uninstall_removes_owned_after_post_activate_create(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.provision import commit_migrations

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    factory = tmp_path / "owned-factory"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "owned-later"
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "ws-drop",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    inst = loader.lifecycle.get_instance("ws-drop")
    assert inst is not None
    api = PluginApi("ws-drop", config={}, manifest={"id": "ws-drop"})
    api.bind_instance(inst)
    assert api.provision_files(factory, dest, "1.0.0") == "create"
    commit_migrations("ws-drop")
    assert dest.exists()
    report = await loader.unload_plugin(
        "ws-drop",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert report.quiescent
    assert not dest.exists()
    assert str(dest) not in (load_inventory("ws-drop").get("locations") or {})


@pytest.mark.asyncio
async def test_activate_rollback_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins import api as plugin_api

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    real = plugin_api.rollback_activate_install

    def _slow(*args, **kwargs):
        time.sleep(0.12)
        return real(*args, **kwargs)

    monkeypatch.setattr(plugin_api, "rollback_activate_install", _slow)
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    installed = _write_plugin(
        tmp_path / "plugins" / "roll-io",
        "roll-io",
        body=(
            "def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    heart = asyncio.create_task(_heart())
    record = await loader.load_plugin(manifest, installed)
    await heart
    assert record.status == "failed"
    gaps = [later - earlier for later, earlier in zip(beats[1:], beats)]
    assert gaps
    assert min(gaps) < 0.05


@pytest.mark.asyncio
async def test_uninstall_teardown_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins import provision as provision_mod

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    real = provision_mod.teardown_created_locations

    def _slow(plugin_id):
        time.sleep(0.12)
        return real(plugin_id)

    monkeypatch.setattr(provision_mod, "teardown_created_locations", _slow)
    factory = tmp_path / "slow-factory"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "slow-dest"
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "slow-un",
        (
            "from pathlib import Path\n"
            f"        api.provision_files(Path({str(factory)!r}), "
            f"Path({str(dest)!r}), '1.0.0')"
        ),
    )
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    heart = asyncio.create_task(_heart())
    await loader.unload_plugin(
        "slow-un",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    await heart
    gaps = [later - earlier for later, earlier in zip(beats[1:], beats)]
    assert gaps
    assert min(gaps) < 0.05
    assert not dest.exists()


def _assert_old_plugin_copy_survives(
    plugin_id: str,
    target: Path,
    old_text: str,
    incoming_text: str,
) -> None:
    backup = None
    path = marker_path(plugin_id)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = str(data.get("backup_path") or "").strip()
        if raw:
            backup = Path(raw)
    copies = []
    if target.exists() and (target / "main.py").is_file():
        copies.append((target / "main.py").read_text(encoding="utf-8"))
    if (
        backup is not None
        and backup.exists()
        and (backup / "main.py").is_file()
    ):
        copies.append((backup / "main.py").read_text(encoding="utf-8"))
    assert old_text in copies
    backup_gone = backup is None or not backup.exists()
    if backup_gone:
        assert target.exists()
        assert (target / "main.py").read_text(encoding="utf-8") == old_text
        assert (target / "main.py").read_text(
            encoding="utf-8",
        ) != incoming_text


@pytest.mark.asyncio
async def test_occupied_swap_retry_keeps_old_backup(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "busy-retry",
        "pass",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    incoming = _write_plugin(
        tmp_path / "incoming-busy-retry",
        "busy-retry",
        body="api.register_slash_command('next', lambda c, a: None)",
    )
    incoming_text = (incoming / "main.py").read_text(encoding="utf-8")
    moves = {"n": 0}
    real_move = shutil.move

    def _move(src, dst, *args, **kwargs):
        moves["n"] += 1
        if moves["n"] >= 2:
            raise PermissionError("file in use")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.move", _move)
    report = await loader.reload_plugin_unlocked(
        "busy-retry",
        new_source=incoming,
        allow_install=False,
        owns_dependency_env=True,
    )
    assert not report.ok
    assert report.needs_restart
    assert marker_path("busy-retry").is_file()
    _assert_old_plugin_copy_survives(
        "busy-retry",
        installed,
        old_text,
        incoming_text,
    )

    with pytest.raises(RuntimeError, match="restart required"):
        await loader.load_plugin_from_path(incoming, force=True)
    _assert_old_plugin_copy_survives(
        "busy-retry",
        installed,
        old_text,
        incoming_text,
    )


@pytest.mark.asyncio
async def test_provision_migrate_retry_keeps_backup(
    tmp_path: Path,
    monkeypatch,
):
    from qwenpaw.plugins import provision as provision_mod

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "skill-keep"
    factory_v1 = tmp_path / "factory-v1"
    factory_v1.mkdir()
    (factory_v1 / "note.md").write_text("OLD\n", encoding="utf-8")
    assert provision_files("mig-keep", factory_v1, dest, "1.0.0") == "create"
    assert dest.exists()
    factory_v2 = tmp_path / "factory-v2"
    factory_v2.mkdir()
    (factory_v2 / "note.md").write_text("NEW\n", encoding="utf-8")
    real_apply = provision_mod._apply_factory_copy

    def _boom(*_args, **_kwargs):
        raise RuntimeError("copy boom")

    monkeypatch.setattr(provision_mod, "_apply_factory_copy", _boom)
    with pytest.raises(RuntimeError, match="copy boom"):
        provision_files("mig-keep", factory_v2, dest, "2.0.0")
    loc = (load_inventory("mig-keep").get("locations") or {}).get(str(dest))
    assert loc is not None
    first_backup = Path(loc["migrating"]["backup_path"])
    assert first_backup.exists()
    assert (first_backup / "note.md").read_text(encoding="utf-8") == "OLD\n"
    with pytest.raises(RuntimeError, match="copy boom"):
        provision_files("mig-keep", factory_v2, dest, "2.0.0")
    loc2 = (load_inventory("mig-keep").get("locations") or {}).get(str(dest))
    assert loc2 is not None
    second_backup = Path(loc2["migrating"]["backup_path"])
    assert second_backup.exists()
    assert second_backup == first_backup
    assert (second_backup / "note.md").read_text(encoding="utf-8") == "OLD\n"
    monkeypatch.setattr(provision_mod, "_apply_factory_copy", real_apply)


@pytest.mark.asyncio
async def test_boot_recover_is_fail_soft_on_occupied_update(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins import updates as updates_mod
    from qwenpaw.plugins.safe_fs import safe_remove as real_safe_remove

    work = tmp_path / "work"
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    plugins = tmp_path / "plugins"
    backups = tmp_path / "backups"
    backups.mkdir()
    _write_plugin(plugins / "occ", "occ")
    _write_plugin(plugins / "ok", "ok")
    _write_plugin(plugins / "fresh", "fresh")
    occ_target = plugins / "occ"
    ok_target = plugins / "ok"
    (occ_target / "main.py").write_text("OCC-NEW\n", encoding="utf-8")
    (ok_target / "main.py").write_text("OK-NEW\n", encoding="utf-8")
    occ_backup = backups / "occ.bak"
    ok_backup = backups / "ok.bak"
    shutil.copytree(occ_target, occ_backup)
    shutil.copytree(ok_target, ok_backup)
    (occ_backup / "main.py").write_text("OCC-OLD\n", encoding="utf-8")
    (ok_backup / "main.py").write_text("OK-OLD\n", encoding="utf-8")
    write_updating_marker(
        "occ",
        backup_path=occ_backup,
        target_path=occ_target,
    )
    write_updating_marker(
        "ok",
        backup_path=ok_backup,
        target_path=ok_target,
    )

    def _blocked(path, purpose="delete"):
        if Path(path).resolve() == occ_target.resolve():
            raise PermissionError("target locked")
        return real_safe_remove(path, purpose=purpose)

    monkeypatch.setattr(updates_mod, "safe_remove", _blocked)
    loader = PluginLoader(plugin_dirs=[plugins])
    loader.registry = fresh_registry
    loaded = await loader.load_all_plugins(activate=True)
    assert marker_path("occ").is_file()
    assert occ_backup.exists()
    assert (occ_backup / "main.py").read_text(encoding="utf-8") == "OCC-OLD\n"
    assert (ok_target / "main.py").read_text(encoding="utf-8") == "OK-OLD\n"
    assert not ok_backup.exists()
    assert "fresh" in loaded
    assert "ok" in loaded


def test_recover_migrating_is_fail_soft_on_occupied_dest(
    tmp_path: Path,
    monkeypatch,
):
    from qwenpaw.plugins import provision as provision_mod

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest_a = tmp_path / "dest-a"
    dest_b = tmp_path / "dest-b"
    bak_a = tmp_path / "dest-a.bak"
    bak_b = tmp_path / "dest-b.bak"
    dest_a.mkdir()
    dest_b.mkdir()
    bak_a.mkdir()
    bak_b.mkdir()
    (dest_a / "note.md").write_text("NEW-A\n", encoding="utf-8")
    (dest_b / "note.md").write_text("NEW-B\n", encoding="utf-8")
    (bak_a / "note.md").write_text("OLD-A\n", encoding="utf-8")
    (bak_b / "note.md").write_text("OLD-B\n", encoding="utf-8")
    for plugin_id, dest, backup in (
        ("p-occ", dest_a, bak_a),
        ("p-ok", dest_b, bak_b),
    ):
        save_inventory(
            plugin_id,
            {
                "plugin_id": plugin_id,
                "locations": {
                    str(dest): {
                        "src": str(dest),
                        "version": "2.0.0",
                        "owned": True,
                        "files": {},
                        "migrating": {
                            "status": "prepared",
                            "backup_path": str(backup),
                            "prev_version": "1.0.0",
                            "prev_factory_hashes": {},
                        },
                    },
                },
                "tools": {},
                "provisions": [],
            },
        )
    real_remove = provision_mod._remove_path

    def _blocked(path):
        if path is not None and Path(path).resolve() == dest_a.resolve():
            raise PermissionError("dest locked")
        return real_remove(path)

    monkeypatch.setattr(provision_mod, "_remove_path", _blocked)
    recovered = recover_migrating_inventory()
    assert "p-ok" in recovered
    assert "p-occ" not in recovered
    assert (bak_a / "note.md").read_text(encoding="utf-8") == "OLD-A\n"
    assert (dest_b / "note.md").read_text(encoding="utf-8") == "OLD-B\n"
    loc = (load_inventory("p-occ").get("locations") or {}).get(str(dest_a))
    assert loc is not None
    assert Path(loc["migrating"]["backup_path"]) == bak_a
