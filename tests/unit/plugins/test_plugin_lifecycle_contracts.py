# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Plugin load, reload, provision, and custody contracts."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.routers.plugins import (
    UpdatePluginConfigRequest,
    update_plugin_config,
)
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.custody import close_connection
from qwenpaw.plugins.lifecycle import PluginInstance, PluginState
from qwenpaw.plugins.dependency_gate import DependencyGate
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    apply_tool_factory,
    load_inventory,
    provision_files,
    teardown_created_locations,
)
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.safe_fs import (
    ensure_deletable,
    parse_optional_absolute,
    same_location,
)
from qwenpaw.plugins.updates import (
    marker_path,
    recover_interrupted_updates,
    updates_dir,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry


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
        ),
    )


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
    await loader.load_plugin(manifest, installed, config)
    if activate:
        await loader.activate_plugin_unlocked(plugin_id)
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
    await loader.load_plugin(manifest_b, tmp_path / "plugins" / "owner-b")
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
        from qwenpaw.plugins.lifecycle import UnloadMode, UnloadReport

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
    assert inst.state is PluginState.ACTIVE
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
    import shutil

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
