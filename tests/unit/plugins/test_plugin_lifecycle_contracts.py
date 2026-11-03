# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Core plugin activation, cancellation, and resource ownership."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import (
    PluginInstance,
    PluginState,
    UnloadMode,
    UnloadReport,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.updates import marker_path
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
from qwenpaw.runtime.tool_registry import ToolRegistry

from .timing import WAIT_TIMEOUT


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


async def _load(
    tmp_path: Path,
    fresh_registry,
    plugin_id: str,
    body: str,
    *,
    config: dict | None = None,
    activate: bool = True,
    workspace=None,
):
    workspace = workspace or _slash_workspace()
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


async def _load_busy_command(
    tmp_path,
    registry,
    kind,
    *,
    ignore_cancel=False,
    exit_release=None,
):
    from qwenpaw.runtime.commands.control import handle_control_command

    entered, release, cancelled = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    calls = []

    async def handle(*_args):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            if not ignore_cancel:
                raise
            await release.wait()
        finally:
            if exit_release is not None:
                await exit_release.wait()
            calls.append("command-exit")
        return "ok"

    body = (
        _control_body("busyprobe").replace(
            "return 'ok'",
            "return await api.config['handler'](context)",
        )
        if kind != "slash"
        else "api.register_slash_command('busyprobe', api.config['handler'], "
        "aliases=('aliasprobe',))"
    ) + (
        "\n        api.effect('probe', None, "
        "lambda: api.config['calls'].append('teardown'))"
    )
    if kind == "mode":
        body = (
            "from qwenpaw.modes.base import AgentMode\n"
            "        from qwenpaw.runtime.slash_command_registry "
            "import CommandSpec\n"
            "        class Mode(AgentMode):\n"
            "            name = 'busy-mode'\n"
            "            def commands(self):\n"
            "                return [CommandSpec(name='busyprobe', "
            "help_text='probe', handler=api.config['handler'])]\n"
            "        api.register_mode(Mode)\n"
            "        api.effect('probe', None, "
            "lambda: api.config['calls'].append('teardown'))"
        )
    workspace = _slash_workspace()
    if kind == "mode":
        workspace.plugins = WorkspacePlugins()
    loader, workspace, installed = await _load(
        tmp_path,
        registry,
        "busy-probe",
        body,
        config={"handler": handle, "calls": calls},
        workspace=workspace,
    )
    ctx = SimpleNamespace(workspace=workspace)
    if kind == "adapter":
        from qwenpaw.runtime.builtin_commands import (
            collect_builtin_command_specs,
        )

        spec = next(
            item
            for item in collect_builtin_command_specs()
            if item.name == "busyprobe"
        )
        workspace.plugins.slash_command_registry.register(spec)
    dispatch = (
        handle_control_command
        if kind == "control"
        else workspace.plugins.slash_command_registry.dispatch
    )
    command = asyncio.create_task(
        dispatch("/aliasprobe" if kind == "slash" else "/busyprobe", ctx),
    )
    await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
    return loader, installed, command, release, cancelled, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_startup", [False, True])
async def test_commands_wait_for_initial_activation(
    tmp_path,
    fresh_registry,
    monkeypatch,
    fail_startup,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def startup(*_args):
        entered.set()
        await release.wait()
        if fail_startup:
            raise RuntimeError("startup failed")

    async def handler(*_args):
        calls.append("called")
        return "ok"

    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "initial",
        "api.register_slash_command('probe', api.config['handler'])\n"
        "        api.register_startup_hook('wait', api.config['startup'])",
        config={"handler": handler, "startup": startup},
        activate=False,
    )
    activate = asyncio.create_task(loader.lifecycle.activate("initial"))
    try:
        await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
        with pytest.raises(RuntimeError):
            await workspace.plugins.slash_command_registry.dispatch(
                "/probe",
                SimpleNamespace(),
            )
        assert not calls
    finally:
        release.set()
        await asyncio.gather(activate, return_exceptions=True)
    try:
        result = await workspace.plugins.slash_command_registry.dispatch(
            "/probe",
            SimpleNamespace(),
        )
        assert calls == ([] if fail_startup else ["called"])
        assert result == (None if fail_startup else "ok")
    finally:
        await loader.lifecycle.unload("initial", UnloadMode.UNLOAD)


@pytest.mark.asyncio
# Each registration kind feeds the same activity gate used by all mutations.
@pytest.mark.parametrize(
    "kind, operation",
    [
        ("control", "unload"),
        ("slash", "unload"),
        ("adapter", "unload"),
        ("mode", "unload"),
        ("control", "reload"),
        ("control", "config"),
        ("control", "install"),
    ],
)
async def test_busy_command_blocks_lifecycle(
    tmp_path,
    fresh_registry,
    monkeypatch,
    kind,
    operation,
):
    from qwenpaw.plugins.activity import PluginBusyError

    _isolate_working_dir(tmp_path, monkeypatch)
    (
        loader,
        installed,
        command,
        release,
        _cancelled,
        calls,
    ) = await _load_busy_command(tmp_path, fresh_registry, kind)
    record = loader.get_loaded_plugin("busy-probe")
    workspace = fresh_registry.get_workspace_manager().agents["talk"]
    retained = (
        workspace.plugins.slash_command_registry.resolve("/busyprobe")[0]
        if kind == "adapter"
        else None
    )
    try:
        with pytest.raises(PluginBusyError):
            if operation == "unload":
                await loader.lifecycle.unload(
                    "busy-probe",
                    UnloadMode.UNINSTALL,
                )
            elif operation == "reload":
                await loader.lifecycle.reload("busy-probe")
            elif operation == "config":
                await loader.lifecycle.update_config("busy-probe", {})
            else:
                await loader.load_plugin_from_path(installed, force=True)
        assert not calls
        assert not command.done()
        assert loader.get_loaded_plugin("busy-probe") is record
        assert (installed / "plugin.json").exists()
    finally:
        release.set()
        await command
        if loader.get_loaded_plugin("busy-probe") is not None:
            report = await loader.lifecycle.unload(
                "busy-probe",
                UnloadMode.UNLOAD,
            )
            assert report.clean and report.quiescent
    assert calls == ["command-exit", "teardown"]
    if kind == "mode":
        assert not workspace.plugins.modes
        assert (
            workspace.plugins.slash_command_registry.resolve("/busyprobe")
            is None
        )
    if retained is not None:
        await retained.handler(SimpleNamespace(workspace=workspace), "")
        assert calls == ["command-exit", "teardown"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ignore_cancel", [False, True])
@pytest.mark.parametrize("kind", ["control", "mode"])
async def test_interrupt_waits_for_actual_command_exit(
    tmp_path,
    fresh_registry,
    monkeypatch,
    ignore_cancel,
    kind,
):
    from qwenpaw.plugins.activity import PluginBusyError
    from qwenpaw.runtime.commands.control import handle_control_command

    config_path = _isolate_working_dir(tmp_path, monkeypatch) / "config.json"
    config_path.write_text(
        '{"plugins": {"busy-probe": {"enabled": true}, '
        '"unrelated": {"enabled": false}}}',
        encoding="utf-8",
    )
    if ignore_cancel:
        monkeypatch.setattr(
            "qwenpaw.plugins.activity.INTERRUPT_TIMEOUT_SECONDS",
            0.01,
        )
    exit_release = asyncio.Event()
    (
        loader,
        installed,
        command,
        release,
        cancelled,
        calls,
    ) = await _load_busy_command(
        tmp_path,
        fresh_registry,
        kind,
        ignore_cancel=ignore_cancel,
        exit_release=None if ignore_cancel else exit_release,
    )
    try:
        unload = asyncio.create_task(
            loader.lifecycle.unload(
                "busy-probe",
                UnloadMode.UNINSTALL,
                delete_files=True,
                interrupt_tasks=True,
            ),
        )
        if ignore_cancel:
            await asyncio.wait_for(cancelled.wait(), 10)
            workspace = fresh_registry.get_workspace_manager().agents["talk"]
            dispatch = (
                handle_control_command
                if kind == "control"
                else workspace.plugins.slash_command_registry.dispatch
            )
            if kind == "control":
                rejected = await dispatch("/busyprobe", SimpleNamespace())
                assert "Command Failed" in rejected
            else:
                with pytest.raises(PluginBusyError):
                    await dispatch("/busyprobe", SimpleNamespace())
            with pytest.raises(PluginBusyError) as caught:
                # Let the configured interrupt deadline expire before this
                # outer deadlock guard cancels the unload operation.
                await asyncio.wait_for(unload, 10)
            assert caught.value.detail["can_interrupt"] is False
            assert cancelled.is_set()
            assert not command.done()
            assert not calls
            assert installed.is_dir()
            assert loader.get_loaded_plugin("busy-probe") is not None
            with pytest.raises(PluginBusyError):
                await loader.lifecycle.reload("busy-probe")
            with pytest.raises(PluginBusyError):
                await loader.lifecycle.unload(
                    "busy-probe",
                    UnloadMode.UNLOAD,
                    interrupt_tasks=True,
                )
            assert not command.done()
            assert not calls
            release.set()
            await command
            report = await loader.lifecycle.unload(
                "busy-probe",
                UnloadMode.UNINSTALL,
                delete_files=True,
            )
        else:
            await asyncio.wait_for(cancelled.wait(), 10)
            await asyncio.sleep(0)
            assert not command.done()
            assert not unload.done()
            assert not calls
            assert installed.is_dir()
            exit_release.set()
            # The deadline guards deadlocks, not config and disk performance.
            report = await asyncio.wait_for(unload, 10)
            assert command.cancelled()
        assert report.clean and report.quiescent
        assert calls == ["command-exit", "teardown"]
        assert not installed.exists()
        assert json.loads(config_path.read_text(encoding="utf-8"))[
            "plugins"
        ] == {"unrelated": {"enabled": False}}
    finally:
        exit_release.set()
        release.set()
        await asyncio.gather(command, unload, return_exceptions=True)
        if loader.get_loaded_plugin("busy-probe") is not None:
            await loader.lifecycle.unload("busy-probe", UnloadMode.UNLOAD)


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
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def _slow_copy(src, dst, *args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        if not release.wait(WAIT_TIMEOUT * 2):
            raise TimeoutError("test did not release plugin copy")
        result = real_copy(src, dst, *args, **kwargs)
        finished["done"] = True
        return result

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.copytree", _slow_copy)
    task = asyncio.create_task(
        loader.load_plugin_from_path(source, install_dir=install_dir),
    )
    try:
        await asyncio.wait_for(started.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
    assert finished["done"]
    record = await loader.load_plugin_from_path(
        source,
        install_dir=install_dir,
        force=True,
    )
    assert record.manifest.id == "copier"


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
            "qwenpaw.plugins.api.get_available_channels",
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
