# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Plugin failure recovery and workspace replacement regressions."""

import asyncio
import builtins
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.lifecycle import PluginState, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    EscapeRollbackError,
    load_inventory,
    record_escape_provision,
    save_inventory,
    undo_this_txn_escapes,
)
from qwenpaw.plugins.updates import (
    STATUS_COMMITTED,
    marker_path,
    write_updating_marker,
)
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.workspace_projector import WorkspaceProjector


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    return PluginRegistry()


def workspace():
    return SimpleNamespace(agent_id="same-agent", plugins=WorkspacePlugins())


@pytest.mark.asyncio
async def test_boot_activation_finishes_before_unload(
    tmp_path,
    registry,
    monkeypatch,
):
    state = {
        "entered": asyncio.Event(),
        "release": asyncio.Event(),
        "alive": False,
        "calls": [],
    }
    monkeypatch.setattr(
        builtins,
        "_qwenpaw_boot_activation_state",
        state,
        raising=False,
    )
    root = tmp_path / "plugins" / "boot-activation"
    root.mkdir(parents=True)
    manifest = PluginManifest.from_dict(
        {
            "id": "boot-activation",
            "name": "Boot activation",
            "version": "1.0.0",
            "entry": {"backend": "main.py"},
        },
    )
    (root / "main.py").write_text(
        "import builtins\n"
        "state = builtins._qwenpaw_boot_activation_state\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        async def start():\n"
        "            state['calls'].append('starting')\n"
        "            state['entered'].set()\n"
        "            await state['release'].wait()\n"
        "            state['alive'] = True\n"
        "            state['calls'].append('started')\n"
        "        def stop():\n"
        "            state['alive'] = False\n"
        "            state['calls'].append('stopped')\n"
        "        api.effect('connection', None, stop)\n"
        "        api.register_startup_hook('connection', start)\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    loader = PluginLoader([root.parent])
    loader.registry = registry
    record = await loader.load_plugin(manifest, root, activate=False)
    assert record.status == "registered"
    activation = asyncio.create_task(loader.activate_all_loaded())
    unload = None
    try:
        await asyncio.wait_for(state["entered"].wait(), timeout=2)
        unload = asyncio.create_task(loader.unload_plugin(manifest.id))
        done, _ = await asyncio.wait({unload}, timeout=0.05)
        assert not done
        assert state["calls"] == ["starting"]
    finally:
        state["release"].set()
        await activation
        if unload is not None:
            report = await unload
        else:
            report = await loader.unload_plugin(manifest.id)
    assert report.clean and report.quiescent
    assert state["calls"] == ["starting", "started", "stopped"]
    assert not state["alive"]
    assert loader.get_loaded_plugin(manifest.id) is None
    assert loader.lifecycle.get_instance(manifest.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_partial_effect_setup_is_cleaned_or_retained_for_retry(
    tmp_path,
    registry,
    monkeypatch,
    cleanup_fails,
):
    state = {
        "value": "old",
        "cleanup_fails": cleanup_fails,
        "cleanup_calls": 0,
    }
    monkeypatch.setattr(
        builtins,
        "_qwenpaw_effect_test_state",
        state,
        raising=False,
    )
    root = tmp_path / "plugins" / "partial-effect"
    root.mkdir(parents=True)
    manifest = PluginManifest.from_dict(
        {
            "id": "partial-effect",
            "name": "Partial effect",
            "version": "1.0.0",
            "entry": {"backend": "main.py"},
        },
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "partial-effect",
                "name": "Partial effect",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "import builtins\n"
        "state = builtins._qwenpaw_effect_test_state\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        def setup():\n"
        "            state['value'] = 'new'\n"
        "            raise RuntimeError('partial setup failed')\n"
        "        def teardown():\n"
        "            state['cleanup_calls'] += 1\n"
        "            if state['cleanup_fails']:\n"
        "                raise RuntimeError('effect still live')\n"
        "            state['value'] = 'old'\n"
        "        api.effect('partial effect', setup, teardown)\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    loader.registry = registry
    record = await loader.load_plugin(manifest, root)
    assert record.status == "failed"
    assert any("partial setup failed" in d for d in record.diagnostics)
    assert state["cleanup_calls"] == 1
    inst = loader.lifecycle.get_instance("partial-effect")
    if cleanup_fails:
        assert state["value"] == "new"
        assert inst.state is PluginState.FAILED
        assert inst.has_runtime_ledger()
        with pytest.raises(RuntimeError, match="not quiescent"):
            inst.refuse_unquiescent_reregister()
        report = await loader.unload_plugin("partial-effect")
        assert not report.clean
        assert not report.quiescent
        assert report.needs_restart
        assert state["cleanup_calls"] == 2
        assert inst.has_runtime_ledger()
        assert loader.get_loaded_plugin("partial-effect") is not None
        state["cleanup_fails"] = False
    else:
        assert state["value"] == "old"
    report = await loader.unload_plugin("partial-effect")
    assert report.clean
    assert report.quiescent
    assert state["value"] == "old"
    assert state["cleanup_calls"] == (3 if cleanup_fails else 1)
    assert loader.get_loaded_plugin("partial-effect") is None


def test_unbound_effect_refuses_setup():
    api = PluginApi("unbound-effect", {}, {"id": "unbound-effect"})
    calls = []
    with pytest.raises(RuntimeError, match="Plugin instance is not bound"):
        api.effect("unbound", lambda: calls.append("setup"), lambda: None)
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,restart",
    [("register", False), ("startup", True)],
)
async def test_escape_rollback_failure_keeps_cleanup_for_retry(
    tmp_path,
    registry,
    phase,
    restart,
):
    root = tmp_path / "plugins" / "escape-retry"
    root.mkdir(parents=True)
    residue = tmp_path / "external-file"
    blocked = tmp_path / "blocked"
    blocked.touch()
    cleanup_module = f"cleanup_{phase}_{int(restart)}"
    data = {
        "id": "escape-retry",
        "name": "Escape retry",
        "version": "1.0.0",
        "entry": {"backend": "main.py"},
    }
    (root / "plugin.json").write_text(json.dumps(data))
    (root / f"{cleanup_module}.py").write_text(
        "from pathlib import Path\n"
        "def cleanup():\n"
        f"    if Path({str(blocked)!r}).exists():\n"
        "        raise PermissionError('file occupied')\n"
        f"    Path({str(residue)!r}).unlink(missing_ok=True)\n",
    )
    invoke = (
        "fail()"
        if phase == "register"
        else ("api.register_startup_hook('fail', fail)")
    )
    (root / "main.py").write_text(
        "from pathlib import Path\n"
        f"from {cleanup_module} import cleanup\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        def fail():\n"
        f"            def setup(): Path({str(residue)!r}).write_text('live')\n"
        "            api.provision('external file', setup, cleanup, "
        f"teardown_ref='{cleanup_module}:cleanup')\n"
        "            raise RuntimeError('transaction failed')\n"
        f"        {invoke}\n"
        "plugin = Plugin()\n",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    loader.registry = registry
    record = await loader.load_plugin(PluginManifest.from_dict(data), root)
    assert record.status == "failed"
    assert residue.exists()
    assert any("file occupied" in d for d in record.diagnostics)
    rows = load_inventory("escape-retry")["provisions"]
    assert len(rows) == 1
    assert rows[0]["teardown_ref"] == f"{cleanup_module}:cleanup"
    inst = loader.lifecycle.get_instance("escape-retry")
    assert [desc for desc, _ in inst.txn_escapes()] == ["external file"]
    if restart:
        # Fresh loader has no callable handles; persistent refs must suffice.
        loader = PluginLoader([tmp_path / "plugins"])
        loader.registry = registry
        mode = UnloadMode.UNINSTALL
    else:
        mode = UnloadMode.UNLOAD
    report = await loader.unload_plugin("escape-retry", mode=mode)
    assert not report.clean
    assert any("file occupied" in error for error in report.errors)
    assert residue.exists()
    assert root.exists()
    assert load_inventory("escape-retry")["provisions"]
    if not restart:
        assert report.quiescent  # File deletion failure is not a live task.
        assert loader.lifecycle.get_instance("escape-retry") is inst
        assert inst.txn_escapes()
    blocked.unlink()
    report = await loader.unload_plugin("escape-retry", mode=mode)
    assert report.clean
    assert report.quiescent
    assert not residue.exists()
    assert not load_inventory("escape-retry")["provisions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,outcome",
    [
        ("register", "success"),
        ("startup", "success"),
        ("startup", "error"),
        ("startup", "cancel"),
    ],
)
async def test_async_escape_rollback_awaits_on_owner_loop_and_keeps_retry(
    tmp_path,
    registry,
    monkeypatch,
    phase,
    outcome,
):
    state = {
        "loop": asyncio.get_running_loop(),
        "outcome": outcome,
        "calls": 0,
    }
    monkeypatch.setattr(
        builtins,
        "_qwenpaw_async_escape_state",
        state,
        raising=False,
    )
    plugin_id = f"async-escape-{phase}-{outcome}"
    root = tmp_path / "plugins" / plugin_id
    root.mkdir(parents=True)
    residue = tmp_path / "external-file"
    cleanup_module = f"cleanup_async_{phase}_{outcome}"
    data = {
        "id": plugin_id,
        "name": "Async escape",
        "version": "1.0.0",
        "entry": {"backend": "main.py"},
    }
    (root / "plugin.json").write_text(json.dumps(data))
    (root / f"{cleanup_module}.py").write_text(
        "import asyncio, builtins\n"
        "from pathlib import Path\n"
        "async def cleanup():\n"
        "    state = builtins._qwenpaw_async_escape_state\n"
        "    assert asyncio.get_running_loop() is state['loop']\n"
        "    state['calls'] += 1\n"
        "    ready = state['loop'].create_future()\n"
        "    state['loop'].call_soon(ready.set_result, None)\n"
        "    await ready\n"
        "    if state['outcome'] == 'error':\n"
        "        raise PermissionError('async file occupied')\n"
        "    if state['outcome'] == 'cancel':\n"
        "        raise asyncio.CancelledError('async cleanup cancelled')\n"
        f"    Path({str(residue)!r}).unlink(missing_ok=True)\n",
    )
    invoke = (
        "fail()"
        if phase == "register"
        else "api.register_startup_hook('fail', fail)"
    )
    teardown = (
        "lambda: asyncio.create_task(cleanup())"
        if phase == "register"
        else "cleanup"
    )
    (root / "main.py").write_text(
        "import asyncio\n"
        "from pathlib import Path\n"
        f"from {cleanup_module} import cleanup\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        def fail():\n"
        f"            def setup(): Path({str(residue)!r}).write_text('live')\n"
        f"            api.provision('external file', setup, {teardown}, "
        f"teardown_ref='{cleanup_module}:cleanup')\n"
        "            raise RuntimeError('transaction failed')\n"
        f"        {invoke}\n"
        "plugin = Plugin()\n",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    loader.registry = registry
    record = await loader.load_plugin(PluginManifest.from_dict(data), root)
    assert record.status == "failed"
    assert state["calls"] == 1
    rows = load_inventory(plugin_id)["provisions"]
    if outcome == "success":
        assert not residue.exists()
        assert not rows
        return

    assert residue.exists()
    assert rows[0]["teardown_ref"] == f"{cleanup_module}:cleanup"
    error = "async file occupied" if outcome == "error" else "cancel"
    assert any(
        error in diagnostic.lower() for diagnostic in record.diagnostics
    )
    inst = loader.lifecycle.get_instance(plugin_id)
    assert [desc for desc, _ in inst.txn_escapes()] == ["external file"]
    state["outcome"] = "success"
    report = await loader.unload_plugin(plugin_id)
    assert report.clean and report.quiescent
    assert state["calls"] == 2
    assert not residue.exists()
    assert not load_inventory(plugin_id)["provisions"]
    assert not inst.txn_escapes()


@pytest.mark.asyncio
async def test_escape_rollback_drops_only_successful_rows(registry):
    calls = []
    record_escape_provision("partial-undo", "good", teardown_ref="m:good")
    record_escape_provision("partial-undo", "bad", teardown_ref="m:bad")

    def bad():
        calls.append("bad")
        raise PermissionError("file occupied")

    with pytest.raises(EscapeRollbackError) as caught:
        undo_this_txn_escapes(
            "partial-undo",
            [("good", lambda: calls.append("good")), ("bad", bad)],
        )
    assert calls == ["bad", "good"]
    assert caught.value.failed_descs == ["bad"]
    assert [
        row["desc"] for row in load_inventory("partial-undo")["provisions"]
    ] == (["bad"])


@pytest.mark.asyncio
async def test_replacement_workspace_gets_its_own_binding(registry):
    old, new = workspace(), workspace()
    live = [old]
    registry.projector = WorkspaceProjector(lambda: live)
    loader = PluginLoader([])
    api = PluginApi("replacement", {}, {"id": "replacement"})
    api.set_registry(registry)
    inst = loader.lifecycle.ensure_instance("replacement")
    api.bind_instance(inst)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project("slash_command", "hello", "replacement")
    # Reload candidates are set up before replacing the current workspace.
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "replacement",
    )
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    assert old.plugins.slash_command_registry.resolve("/hello") is not None
    live[:] = [new]
    await inst.dispose(UnloadMode.UNLOAD)
    assert new.plugins.slash_command_registry.resolve("/hello") is None
    assert old.plugins.slash_command_registry.resolve("/hello") is None


@pytest.mark.asyncio
async def test_failed_mode_cleanup_retains_binding_for_retry(registry):
    ws = workspace()
    registry.projector = WorkspaceProjector(lambda: [ws])
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("mode-test")
    api = PluginApi("mode-test", {}, {"id": "mode-test"})
    api.set_registry(registry)
    api.bind_instance(inst)
    calls = []

    class Mode:
        name = "retryable"

        def setup(self, _):
            pass

        def teardown(self, _):
            calls.append("stop")
            if len(calls) == 1:
                raise RuntimeError("connection still open")

    api.register_mode(Mode)
    await registry.projector.project("mode", "retryable", "mode-test")
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert inst.state is PluginState.FAILED
    assert len(ws.plugins.modes) == 1
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert not ws.plugins.modes


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_partial_channel_start_keeps_handle_until_stopped(
    monkeypatch,
    cancelled,
):
    connected = []
    started = asyncio.Event()

    async def start():
        connected.append(True)
        started.set()
        if cancelled:
            await asyncio.Event().wait()
        raise RuntimeError("start failed")

    ch = SimpleNamespace(
        channel="partial",
        uses_manager_queue=False,
        start=start,
        stop=AsyncMock(side_effect=RuntimeError("stop failed")),
        set_enqueue=lambda _: None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        lambda *a, **k: ch,
    )
    manager = ChannelManager([])
    manager._process = lambda *_: None
    task = asyncio.create_task(manager.start_one("partial", object()))
    await started.wait()
    if cancelled:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
        await task
    assert connected
    assert await manager.get_channel("partial") is ch
    ch.stop.side_effect = None
    assert (await manager.stop_one("partial")).stopped
    assert await manager.get_channel("partial") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    [None, "cleanup:cleanup"],
)
async def test_uninstall_unresolved_provisions_keeps_retry_information(
    tmp_path,
    registry,
    ref,
):
    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    (root / "cleanup.py").write_text(
        "def cleanup():\n    raise RuntimeError('resource busy')\n",
    )
    resource = tmp_path / "external-resource"
    resource.write_text("still owned")
    record_escape_provision("disk-plugin", "external", teardown_ref=ref)
    loader = PluginLoader([tmp_path / "plugins"])
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert not report.clean
    assert not report.quiescent
    assert report.errors
    assert root.exists()
    assert resource.exists()
    assert load_inventory("disk-plugin")["provisions"]


@pytest.mark.asyncio
async def test_memory_config_rejected_before_any_teardown(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.agents.memory.base_memory_manager import MemoryBackendRegistry
    from qwenpaw import memory

    isolated = MemoryBackendRegistry()
    monkeypatch.setattr(memory, "memory_registry", isolated)
    # The guard reads the registry exposed by qwenpaw.memory.
    isolated.register_backend(
        backend_id="selected",
        factory=type("Factory", (), {}),
        plugin_id="memory-plugin",
        label="Selected",
    )
    ws = workspace()
    ws._config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="selected"),
    )
    registry.set_workspace_manager(SimpleNamespace(agents={ws.agent_id: ws}))
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("memory-plugin")
    closed = []
    inst.record_runtime("connection", lambda: closed.append(True))
    manifest = PluginManifest.from_dict(
        {"id": "memory-plugin", "version": "1.0.0", "name": "Memory"},
    )
    loader._loaded_plugins["memory-plugin"] = PluginRecord(
        manifest=manifest,
        source_path=tmp_path,
        instance=object(),
        status="active",
        enabled=True,
    )
    report = await loader.lifecycle.update_config("memory-plugin", {})
    assert not report.ok
    assert report.unchanged
    assert report.conflict
    assert not closed
    assert inst.has_runtime_ledger()
    assert loader.get_loaded_plugin("memory-plugin").status == "active"
    from fastapi import HTTPException
    from qwenpaw.app.routers.plugins import (
        UpdatePluginConfigRequest,
        update_plugin_config,
    )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    with pytest.raises(HTTPException) as error:
        await update_plugin_config(
            "memory-plugin",
            UpdatePluginConfigRequest(config={}),
            request,
        )
    assert error.value.status_code == 409
    assert error.value.detail["unchanged"]
    assert not closed


@pytest.mark.asyncio
async def test_channel_failed_projection_can_retry_cleanup(
    registry,
    monkeypatch,
):
    ws = workspace()
    manager = ChannelManager([])
    manager._process = lambda *_: None
    ws.channel_manager = manager
    registry.projector = WorkspaceProjector(lambda: [ws])
    ch = SimpleNamespace(
        channel="partial",
        uses_manager_queue=False,
        start=AsyncMock(side_effect=RuntimeError("start failed")),
        stop=AsyncMock(side_effect=RuntimeError("stop failed")),
        set_enqueue=lambda _: None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        lambda *a, **k: ch,
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.workspace_projector.channel_passes_gates",
        lambda *_: True,
    )
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("channel-plugin")
    api = PluginApi("channel-plugin", {}, {"id": "channel-plugin"})
    api.set_registry(registry)
    api.bind_instance(inst)
    api._project_channel("partial")
    with pytest.raises(RuntimeError):
        await registry.projector.project(
            "channel",
            "partial",
            "channel-plugin",
        )
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert await manager.get_channel("partial") is ch
    ch.stop.side_effect = None
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert await manager.get_channel("partial") is None


@pytest.mark.asyncio
async def test_restart_cleanup_preserves_only_unfinished_rows(
    tmp_path,
    registry,
    monkeypatch,
):
    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    flag = tmp_path / "busy"
    flag.touch()
    completed = tmp_path / "completed"
    (root / "cleanup.py").write_text(
        "from pathlib import Path\n"
        f"def first():\n    Path({str(completed)!r}).write_text('done')\n"
        "def second():\n"
        f"    if Path({str(flag)!r}).exists():\n"
        "        raise RuntimeError('busy')\n",
    )
    record_escape_provision(
        "disk-plugin",
        "first",
        teardown_ref="cleanup:first",
    )
    record_escape_provision(
        "disk-plugin",
        "second",
        teardown_ref="cleanup:second",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert not report.clean
    assert completed.read_text() == "done"
    assert [
        row["desc"] for row in load_inventory("disk-plugin")["provisions"]
    ] == [
        "second",
    ]
    completed.write_text("do not run first again")
    flag.unlink()
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert report.clean
    assert not root.exists()
    assert completed.read_text() == "do not run first again"


@pytest.mark.asyncio
async def test_failed_mode_setup_cleanup_is_reported_as_unquiescent(registry):
    ws = workspace()
    registry.projector = WorkspaceProjector(lambda: [ws])
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("bad-mode")
    api = PluginApi("bad-mode", {}, {"id": "bad-mode"})
    api.set_registry(registry)
    api.bind_instance(inst)

    class Mode:
        name = "partial"

        def setup(self, _):
            raise RuntimeError("setup failed")

        def teardown(self, _):
            raise RuntimeError("resource remains")

    api.register_mode(Mode)
    with pytest.raises(RuntimeError):
        await registry.projector.project("mode", "partial", "bad-mode")
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert not ws.plugins.modes
    assert len(ws.plugins._pending_modes) == 1


@pytest.mark.asyncio
async def test_retiring_workspace_cleanup_preserves_new_workspace(registry):
    old, new = workspace(), workspace()
    live = [old]
    registry.projector = WorkspaceProjector(lambda: live)
    api = PluginApi("retiring", {}, {"id": "retiring"})
    api.set_registry(registry)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project("slash_command", "hello", "retiring")
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "retiring",
    )
    live[:] = [new]
    await registry.projector.revoke_workspace(old)
    assert old.plugins.slash_command_registry.resolve("/hello") is None
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    await registry.projector.revoke("slash_command", "hello", "retiring")
    assert new.plugins.slash_command_registry.resolve("/hello") is None


def test_existing_provision_can_gain_restartable_cleanup_without_setup(
    registry,
):
    calls = []
    api = PluginApi("upgrade-cleanup", {}, {"id": "upgrade-cleanup"})
    api.set_registry(registry)
    api.provision("owned", lambda: calls.append("setup"), lambda: None)
    api.provision(
        "owned",
        lambda: calls.append("duplicate"),
        lambda: None,
        teardown_ref="cleanup:remove",
    )
    assert calls == ["setup"]
    assert (
        load_inventory("upgrade-cleanup")["provisions"][0]["teardown_ref"]
        == "cleanup:remove"
    )


@pytest.mark.asyncio
async def test_workspace_stop_releases_its_plugin_bindings(registry):
    from qwenpaw.app.workspace.workspace import Workspace

    old = Workspace.__new__(Workspace)
    old.agent_id = "same-agent"
    old.plugins = WorkspacePlugins()
    old._started = True
    old._start_attempted = True
    old._harness_runtime = None
    old._service_manager = SimpleNamespace(stop_all=AsyncMock(), services={})
    new = workspace()
    registry.projector = WorkspaceProjector(lambda: [old])
    api = PluginApi("stop-workspace", {}, {"id": "stop-workspace"})
    api.set_registry(registry)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project(
        "slash_command",
        "hello",
        "stop-workspace",
    )
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "stop-workspace",
    )
    await old.stop(final=False)
    assert old.plugins.slash_command_registry.resolve("/hello") is None
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    old._service_manager.stop_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_unresolved_restart_cleanup_returns_http_conflict(
    tmp_path,
    registry,
):
    from fastapi import HTTPException
    from qwenpaw.app.routers.plugins import uninstall_plugin

    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    record_escape_provision("disk-plugin", "unresolved")
    loader = PluginLoader([tmp_path / "plugins"])
    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=loader))
    with pytest.raises(HTTPException) as error:
        await uninstall_plugin("disk-plugin", SimpleNamespace(app=app))
    assert error.value.status_code == 409
    assert error.value.detail["needs_restart"]
    assert not error.value.detail["quiescent"]
    assert root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_awaitable", [False, True])
async def test_restart_cleanup_awaits_result(
    tmp_path,
    registry,
    monkeypatch,
    custom_awaitable,
):
    root = tmp_path / "plugins" / "async-cleanup"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {"id": "async-cleanup", "version": "1.0.0", "name": "Async"},
        ),
    )
    flag = tmp_path / "finished"
    body = (
        "from pathlib import Path\n"
        "async def finish():\n"
        f"    Path({str(flag)!r}).write_text('done')\n"
    )
    if custom_awaitable:
        body += (
            "class Pending:\n"
            "    def __await__(self):\n"
            "        return finish().__await__()\n"
            "def cleanup():\n"
            "    return Pending()\n"
        )
    else:
        body += "def cleanup():\n    return finish()\n"
    (root / "cleanup.py").write_text(body)
    record_escape_provision(
        "async-cleanup",
        "resource",
        teardown_ref="cleanup:cleanup",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    report = await loader.unload_plugin(
        "async-cleanup",
        mode=UnloadMode.UNINSTALL,
    )
    assert report.clean
    assert flag.read_text() == "done"
    assert not root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(UnloadMode))
async def test_stubborn_hosted_task_returns_failure_and_keeps_retry_handle(
    tmp_path,
    registry,
    monkeypatch,
    mode,
):
    from qwenpaw.plugins import custody

    monkeypatch.setattr(custody, "TASK_STOP_SECONDS", 0.01)
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("stubborn-task")
    api = PluginApi("stubborn-task", {}, {"id": "stubborn-task"})
    api.set_registry(registry)
    api.bind_instance(inst)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def work():
        started.set()
        while not finish.is_set():
            try:
                await finish.wait()
            except asyncio.CancelledError:
                pass

    hosted = api.spawn_task(work(), "stubborn")
    await started.wait()
    manifest = PluginManifest.from_dict(
        {"id": "stubborn-task", "name": "Stubborn", "version": "1.0.0"},
    )
    loader._loaded_plugins["stubborn-task"] = PluginRecord(
        manifest=manifest,
        source_path=tmp_path / "plugin",
        enabled=True,
        status="active",
        instance=object(),
    )
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    retry = None
    operation = asyncio.create_task(
        loader.lifecycle.unload("stubborn-task", mode),
    )
    try:
        done, _ = await asyncio.wait({operation}, timeout=0.3)
        assert operation in done, "unload waited beyond its task stop budget"
        report = operation.result()
        assert not report.clean
        assert not report.quiescent
        assert report.needs_restart
        assert not hosted.done()
        assert inst.state is PluginState.FAILED
        assert inst.has_runtime_ledger()
        assert loader.get_loaded_plugin("stubborn-task") is not None
        with pytest.raises(RuntimeError, match="not quiescent"):
            inst.refuse_unquiescent_reregister()
        # The first unload must also release the facade's same-plugin lock.
        retry = asyncio.create_task(
            loader.lifecycle.unload("stubborn-task", mode),
        )
        done, _ = await asyncio.wait({retry}, timeout=0.3)
        assert retry in done, "the same-plugin lifecycle lock was not released"
        assert not retry.result().quiescent
    finally:
        finish.set()
        await hosted
        await operation
        if retry is not None:
            await retry
    report = await loader.lifecycle.unload("stubborn-task", mode)
    assert report.quiescent


@pytest.mark.asyncio
async def test_stop_task_accepts_normal_cancellation():
    from qwenpaw.plugins.custody import stop_task

    started = asyncio.Event()

    async def work():
        started.set()
        await asyncio.Event().wait()

    hosted = asyncio.create_task(work())
    await started.wait()
    await stop_task(hosted, "normal")
    assert hosted.cancelled()


@pytest.mark.asyncio
async def test_stop_request_cancellation_does_not_wait_for_stubborn_task():
    from qwenpaw.plugins.custody import stop_task

    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    finish = asyncio.Event()

    async def work():
        started.set()
        while not finish.is_set():
            try:
                await finish.wait()
            except asyncio.CancelledError:
                cancellation_seen.set()

    hosted = asyncio.create_task(work())
    await started.wait()
    stopper = asyncio.create_task(stop_task(hosted, "stubborn"))
    try:
        await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
        stopper.cancel()
        done, _ = await asyncio.wait({stopper}, timeout=0.3)
        assert stopper in done
        with pytest.raises(asyncio.CancelledError):
            stopper.result()
        assert not hosted.done()
    finally:
        finish.set()
        await hosted
        await asyncio.gather(stopper, return_exceptions=True)


def write_plugin(root, plugin_id, trace, version):
    root.mkdir(parents=True)
    manifest = {
        "id": plugin_id,
        "version": version,
        "entry": {"backend": f"{plugin_id}.py"},
    }
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / f"{plugin_id}.py").write_text(
        "from pathlib import Path\n"
        f"trace = Path({str(trace)!r})\n"
        "def note(stage):\n"
        "    with trace.open('a') as stream:\n"
        f"        stream.write('{version}:' + stage + '\\n')\n"
        "note('import')\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        note('register')\n"
        "        api.register_startup_hook('probe', lambda: note('startup'))\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    return PluginManifest.from_dict(manifest)


def assert_blocked(loader, plugin_id, trace):
    record = loader.get_loaded_plugin(plugin_id)
    assert record is not None
    assert record.status == "failed"
    assert not trace.exists(), "blocked plugin must not even import"
    assert any("needs_restart" in item for item in record.diagnostics)
    assert any("locked" in item for item in record.diagnostics)


async def assert_direct_entries_blocked(loader, manifest, target, trace):
    try:
        record = await loader.lifecycle.load(manifest, target)
    except RuntimeError:
        pass
    else:
        assert record.status == "failed"
    try:
        await loader.lifecycle.activate(manifest.id)
    except RuntimeError:
        pass
    assert not trace.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["delete", "restore"])
async def test_prepared_update_failure_blocks_activation_and_allows_retry(
    tmp_path,
    registry,
    monkeypatch,
    failure_stage,
):
    from qwenpaw.plugins import updates

    plugin_id = f"boot_{failure_stage}"
    plugins = tmp_path / "plugins"
    target = plugins / plugin_id
    backup = tmp_path / "backup"
    trace = tmp_path / "blocked-trace"
    manifest = write_plugin(target, plugin_id, trace, "2.0.0")
    write_plugin(backup, plugin_id, trace, "1.0.0")
    healthy_trace = tmp_path / "healthy-trace"
    healthy_id = f"healthy_{failure_stage}"
    write_plugin(plugins / healthy_id, healthy_id, healthy_trace, "1.0.0")
    write_updating_marker(plugin_id, backup_path=backup, target_path=target)
    original_marker = marker_path(plugin_id).read_bytes()
    blocked = True
    original_remove = updates.safe_remove
    original_move = updates.shutil.move

    def remove(path, **kwargs):
        if blocked and failure_stage == "delete" and Path(path) == target:
            raise PermissionError("target locked")
        return original_remove(path, **kwargs)

    def move(source, destination, *args, **kwargs):
        if blocked and failure_stage == "restore" and Path(source) == backup:
            raise PermissionError("backup locked")
        return original_move(source, destination, *args, **kwargs)

    monkeypatch.setattr(updates, "safe_remove", remove)
    monkeypatch.setattr(updates.shutil, "move", move)
    loader = PluginLoader([plugins])
    loader.registry = registry
    await loader.load_all_plugins(activate=False)
    await loader.activate_all_loaded()
    assert_blocked(loader, plugin_id, trace)
    assert loader.get_loaded_plugin(healthy_id).status == "active"
    assert "startup" in healthy_trace.read_text(encoding="utf-8")
    await assert_direct_entries_blocked(loader, manifest, target, trace)
    assert marker_path(plugin_id).read_bytes() == original_marker
    assert backup.is_dir()

    blocked = False
    await loader.load_all_plugins(activate=True)
    assert loader.get_loaded_plugin(plugin_id).status == "active"
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "1.0.0:import",
        "1.0.0:register",
        "1.0.0:startup",
    ]
    assert not backup.exists()
    assert not marker_path(plugin_id).exists()


@pytest.mark.asyncio
async def test_committed_cleanup_failure_keeps_new_version_and_diagnostics(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins import updates

    plugin_id = "boot_committed_cleanup"
    plugins = tmp_path / "plugins"
    target = plugins / plugin_id
    trace = tmp_path / "new-trace"
    backup = tmp_path / "backup"
    write_plugin(target, plugin_id, trace, "2.0.0")
    write_plugin(backup, plugin_id, trace, "1.0.0")
    write_updating_marker(
        plugin_id,
        backup_path=backup,
        target_path=target,
        status=STATUS_COMMITTED,
    )
    original_marker = marker_path(plugin_id).read_bytes()
    original_remove = updates.safe_remove

    def remove(path, **kwargs):
        if Path(path) == backup:
            raise PermissionError("committed backup locked")
        return original_remove(path, **kwargs)

    monkeypatch.setattr(updates, "safe_remove", remove)
    loader = PluginLoader([plugins])
    loader.registry = registry
    await loader.load_all_plugins(activate=True)
    record = loader.get_loaded_plugin(plugin_id)
    assert record.status == "active"
    assert any("needs_restart" in item for item in record.diagnostics)
    assert any(
        "committed backup locked" in item for item in record.diagnostics
    )
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "2.0.0:import",
        "2.0.0:register",
        "2.0.0:startup",
    ]
    assert marker_path(plugin_id).read_bytes() == original_marker
    assert backup.exists()


@pytest.mark.asyncio
async def test_failed_recovery_rescan_cannot_release_existing_barrier(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins import updates

    plugin_id = "boot_failed_rescan"
    plugins = tmp_path / "plugins"
    target = plugins / plugin_id
    trace = tmp_path / "blocked-trace"
    manifest = write_plugin(target, plugin_id, trace, "2.0.0")
    write_updating_marker(
        plugin_id,
        backup_path=tmp_path / "missing-backup",
        target_path=target,
    )
    original_marker = marker_path(plugin_id).read_bytes()
    loader = PluginLoader([plugins])
    loader.registry = registry
    await loader.load_all_plugins(activate=True)
    assert loader.get_loaded_plugin(plugin_id).status == "failed"

    def fail_scan(*_args, **_kwargs):
        raise OSError("recovery directory unavailable")

    monkeypatch.setattr(updates, "recover_interrupted_updates", fail_scan)
    await loader.load_all_plugins(activate=True)
    await loader.activate_all_loaded()
    await assert_direct_entries_blocked(loader, manifest, target, trace)
    record = loader.get_loaded_plugin(plugin_id)
    assert record.status == "failed"
    assert any("needs_restart" in item for item in record.diagnostics)
    assert not trace.exists()
    assert marker_path(plugin_id).read_bytes() == original_marker


@pytest.mark.asyncio
async def test_failed_provision_recovery_blocks_plugin_until_retry(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.plugins import provision

    plugin_id = "boot_provision"
    plugins = tmp_path / "plugins"
    trace = tmp_path / "blocked-trace"
    target = plugins / plugin_id
    manifest = write_plugin(target, plugin_id, trace, "1.0.0")
    healthy_trace = tmp_path / "healthy-trace"
    write_plugin(
        plugins / "healthy_provision",
        "healthy_provision",
        healthy_trace,
        "1.0.0",
    )
    dest = tmp_path / "skill"
    backup = tmp_path / "skill.bak"
    dest.mkdir()
    backup.mkdir()
    (dest / "note").write_text("new", encoding="utf-8")
    (backup / "note").write_text("old", encoding="utf-8")
    inventory = {
        "plugin_id": plugin_id,
        "locations": {
            str(dest): {
                "owned": True,
                "version": "2.0.0",
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
    }
    save_inventory(plugin_id, inventory)
    original_remove = provision._remove_path
    blocked = True

    def remove(path):
        if blocked and Path(path) == dest:
            raise PermissionError("skill locked")
        return original_remove(path)

    monkeypatch.setattr(provision, "_remove_path", remove)
    loader = PluginLoader([plugins])
    loader.registry = registry
    await loader.load_all_plugins(activate=False)
    await loader.activate_all_loaded()
    assert_blocked(loader, plugin_id, trace)
    assert loader.get_loaded_plugin("healthy_provision").status == "active"
    assert load_inventory(plugin_id) == inventory
    assert backup.exists()
    await assert_direct_entries_blocked(loader, manifest, target, trace)
    blocked = False
    await loader.load_all_plugins(activate=True)
    assert loader.get_loaded_plugin(plugin_id).status == "active"
    assert (dest / "note").read_text(encoding="utf-8") == "old"
    assert not backup.exists()
