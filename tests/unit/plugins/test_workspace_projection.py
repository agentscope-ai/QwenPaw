# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Workspace revoke, occupancy, and per-channel start/stop."""

from __future__ import annotations

import asyncio
import builtins
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.multi_agent_manager import MultiAgentManager
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.modes.base import AgentMode
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import PluginInstance, PluginState, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.workspace_projector import (
    WorkspaceProjector,
    scan_owner_rows,
)
from qwenpaw.runtime.hooks import HookBase
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.slash_command_registry import CommandSpec
from qwenpaw.runtime.tool_registry import ToolDescriptor


class FakeWorkspace:
    def __init__(self, agent_id: str, config=None) -> None:
        self.agent_id = agent_id
        self.plugins = WorkspacePlugins()
        self._config = config
        self.channel_manager = ChannelManager([])
        self.channel_manager._process = _noop_process
        self.channel_manager._workspace = self


async def _noop_process(_req):
    return None


async def _noop_handler(_ctx, _args):
    return None


class _PingMode(AgentMode):
    name = "ping-mode"

    def commands(self):
        return [
            CommandSpec(name="ping-cmd", handler=_noop_handler),
        ]


class _BoomMode(AgentMode):
    name = "boom-mode"

    def commands(self):
        return [CommandSpec(name="boom-cmd", handler=_noop_handler)]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        raise RuntimeError("setup failed")


class _HeartChannel:
    channel = "fake-heart"
    uses_manager_queue = False

    def __init__(self) -> None:
        self.alive = False
        self.starts = 0
        self.stops = 0

    @classmethod
    def from_config(cls, **_kwargs):
        return cls()

    async def start(self) -> None:
        self.alive = True
        self.starts += 1

    async def stop(self) -> None:
        self.alive = False
        self.stops += 1

    def set_enqueue(self, _cb) -> None:
        return None

    def set_workspace(self, _ws, _reg) -> None:
        return None


class _OtherChannel:
    channel = "other-ch"
    uses_manager_queue = False

    def __init__(self) -> None:
        self.alive = True
        self.stops = 0

    async def start(self) -> None:
        self.alive = True

    async def stop(self) -> None:
        self.alive = False
        self.stops += 1

    def set_enqueue(self, _cb) -> None:
        return None


def _enabled_config(*keys: str):
    channels = SimpleNamespace()
    extra = {}
    for key in keys:
        extra[key] = SimpleNamespace(enabled=True, no_text_debounce=True)
    channels.__pydantic_extra__ = extra
    return SimpleNamespace(channels=channels, show_tool_details=True)


def test_unstamped_mode_loads_and_unregisters():
    workspace = FakeWorkspace("a")
    mode = _PingMode()
    assert mode.owner_plugin_id == ""
    workspace.plugins.register_mode(mode, workspace)
    assert any(m.name == "ping-mode" for m in workspace.plugins.modes)
    assert "ping-cmd" in workspace.plugins.slash_command_registry.names()

    removed = workspace.plugins.unregister_mode("ping-mode", workspace)
    assert removed
    assert not workspace.plugins.modes
    assert "ping-cmd" not in workspace.plugins.slash_command_registry.names()


def test_register_mode_setup_failure_does_not_enter_table():
    workspace = FakeWorkspace("a")
    with pytest.raises(RuntimeError, match="setup failed"):
        workspace.plugins.register_mode(_BoomMode(), workspace)
    assert not workspace.plugins.modes
    assert "boom-cmd" not in workspace.plugins.slash_command_registry.names()


def test_collision_names_stamped_and_unstamped_occupant():
    workspace = FakeWorkspace("a")
    first = _PingMode()
    first.owner_plugin_id = "owner-a"
    workspace.plugins.register_mode(first, workspace)
    with pytest.raises(ValueError, match="plugin 'owner-a'"):
        workspace.plugins.register_mode(_PingMode(), workspace)

    other = FakeWorkspace("b")
    other.plugins.register_mode(_PingMode(), other)
    with pytest.raises(ValueError, match="未标注归属"):
        other.plugins.register_mode(_PingMode(), other)


def test_slash_collision_names_unstamped_occupant():
    registry = FakeWorkspace("a").plugins.slash_command_registry
    registry.register(CommandSpec(name="x", handler=_noop_handler))
    with pytest.raises(ValueError, match="未标注归属"):
        registry.register(CommandSpec(name="x", handler=_noop_handler))


def test_owner_scan_reports_stamped_leak_and_blind_unstamped():
    workspace = FakeWorkspace("a")
    workspace.plugins.tool_registry.register(
        ToolDescriptor(
            name="leaked",
            func=lambda: None,
            owner_plugin_id="plug",
        ),
    )
    workspace.plugins.tool_registry.register(
        ToolDescriptor(name="host-tool", func=lambda: None),
    )
    scan = scan_owner_rows("plug", [workspace])
    assert any("leaked" in item for item in scan.stamped_leaks)
    assert scan.saw_unstamped


def test_unload_scan_wording_matches_design(fresh_registry):
    from qwenpaw.plugins.lifecycle import UnloadReport

    loader = PluginLoader(plugin_dirs=[])
    loader.registry = fresh_registry
    report = UnloadReport(plugin_id="plug", mode=UnloadMode.UNLOAD)
    with patch(
        "qwenpaw.plugins.workspace_projector.default_live_workspaces",
        return_value=[],
    ):
        with patch(
            "qwenpaw.plugins.workspace_projector.scan_owner_rows",
            return_value=SimpleNamespace(
                stamped_leaks=[],
                saw_unstamped=True,
            ),
        ):
            loader._record_workspace_scan("plug", report)
    assert "未标注归属、未覆盖" in report.workspace_leaks
    assert "无章、未覆盖" not in report.workspace_leaks


@pytest.mark.asyncio
async def test_unload_drops_slash_without_rebuilding_workspace(
    fresh_registry,
):
    workspace = FakeWorkspace("talking")
    token = id(workspace)
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talking": workspace}),
    )
    api = PluginApi("contrib", {}, {"id": "contrib"})
    api.set_registry(fresh_registry)
    instance = PluginInstance("contrib")
    api.bind_instance(instance)
    api.register_slash_command("ping", _noop_handler)
    await fresh_registry.projector.project(
        "slash_command",
        "ping",
        "contrib",
    )
    assert "ping" in workspace.plugins.slash_command_registry.names()

    report = await instance.dispose(UnloadMode.UNLOAD)
    assert report.clean
    assert id(workspace) == token
    assert "ping" not in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_channel_start_stop_is_paired_and_isolated():
    other = _OtherChannel()
    manager = ChannelManager([other])
    manager._process = _noop_process
    config = _enabled_config("fake-heart")
    registry = {"fake-heart": _HeartChannel}

    with (
        patch(
            "qwenpaw.app.channels.manager.get_channel_registry",
            return_value=registry,
        ),
        patch(
            "qwenpaw.app.channels.manager.get_available_channels",
            return_value=("fake-heart", "other-ch"),
        ),
    ):
        handle = await manager.start_one("fake-heart", config)
        heart = handle.channel
        assert heart.alive
        assert other.alive

        receipt = await manager.stop_one("fake-heart")
        assert receipt.stopped
        assert heart.alive is False
        assert other.alive is True
        assert other.stops == 0

        handle2 = await manager.start_one("fake-heart", config)
        assert handle2.channel.alive
        assert handle2.channel.starts == 1


@pytest.mark.asyncio
async def test_channel_project_respects_three_gates(fresh_registry):
    enabled = FakeWorkspace("on", config=_enabled_config("fake-heart"))
    disabled_cfg = _enabled_config()
    disabled = FakeWorkspace("off", config=disabled_cfg)
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [enabled, disabled],
    )
    api = PluginApi("ch-plug", {}, {"id": "ch-plug"})
    api.set_registry(fresh_registry)
    instance = PluginInstance("ch-plug")
    api.bind_instance(instance)

    from qwenpaw.plugins.registry import ChannelRegistration

    fresh_registry._channels["fake-heart"] = ChannelRegistration(
        plugin_id="ch-plug",
        channel_key="fake-heart",
        channel_class=_HeartChannel,
    )
    with (
        patch(
            "qwenpaw.plugins.workspace_projector.get_available_channels",
            return_value=("fake-heart",),
        ),
        patch(
            "qwenpaw.app.channels.manager.get_channel_registry",
            return_value={"fake-heart": _HeartChannel},
        ),
        patch(
            "qwenpaw.app.channels.manager.get_available_channels",
            return_value=("fake-heart",),
        ),
    ):
        api._project_channel("fake-heart")
        await fresh_registry.projector.project(
            "channel",
            "fake-heart",
            "ch-plug",
        )
        on_keys = [c.channel for c in enabled.channel_manager.channels]
        off_keys = [c.channel for c in disabled.channel_manager.channels]
        assert "fake-heart" in on_keys
        assert "fake-heart" not in off_keys

        await instance.dispose(UnloadMode.UNLOAD)
        assert enabled.channel_manager.channels == []
        assert "fake-heart" not in fresh_registry.get_registered_channels()


class _StuckChannel:
    channel = "stuck-ch"
    uses_manager_queue = False

    def __init__(self) -> None:
        self.alive = False

    @classmethod
    def from_config(cls, **_kwargs):
        return cls()

    async def start(self) -> None:
        self.alive = True

    async def stop(self) -> None:
        raise RuntimeError("still connected")

    def set_enqueue(self, _cb) -> None:
        return None

    def set_workspace(self, _ws, _reg) -> None:
        return None


@pytest.mark.asyncio
async def test_failed_channel_stop_is_not_quiescent(fresh_registry):
    workspace = FakeWorkspace("on", config=_enabled_config("stuck-ch"))
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    api = PluginApi("stuck-plug", {}, {"id": "stuck-plug"})
    api.set_registry(fresh_registry)
    instance = PluginInstance("stuck-plug")
    api.bind_instance(instance)
    from qwenpaw.plugins.registry import ChannelRegistration

    fresh_registry._channels["stuck-ch"] = ChannelRegistration(
        plugin_id="stuck-plug",
        channel_key="stuck-ch",
        channel_class=_StuckChannel,
    )
    with (
        patch(
            "qwenpaw.plugins.workspace_projector.get_available_channels",
            return_value=("stuck-ch",),
        ),
        patch(
            "qwenpaw.app.channels.manager.get_channel_registry",
            return_value={"stuck-ch": _StuckChannel},
        ),
        patch(
            "qwenpaw.app.channels.manager.get_available_channels",
            return_value=("stuck-ch",),
        ),
    ):
        api._project_channel("stuck-ch")
        await fresh_registry.projector.project(
            "channel",
            "stuck-ch",
            "stuck-plug",
        )
        assert workspace.channel_manager.channels
        report = await instance.dispose(UnloadMode.UNLOAD)
        assert report.quiescent is False
        assert report.needs_restart is True
        assert instance.state is PluginState.FAILED
        assert workspace.channel_manager.channels
        leftover = await workspace.channel_manager.stop_one("stuck-ch")
        assert leftover.stopped is False


class _BootChannel(BaseChannel):
    channel = "boot-race"
    uses_manager_queue = False

    def __init__(self, ignore_cancel):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.ignore_cancel = ignore_cancel
        self.alive = False
        self.stops = 0

    async def start(self):
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if not self.ignore_cancel:
                raise
            await self.release.wait()
        self.alive = True

    async def stop(self):
        self.stops += 1
        self.alive = False

    def set_enqueue(self, _callback):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("ignore_cancel", [False, True])
async def test_unload_drains_boot_channel_start(
    fresh_registry,
    monkeypatch,
    ignore_cancel,
):
    workspace = FakeWorkspace("boot", config=_enabled_config("boot-race"))
    channel = _BootChannel(ignore_cancel)
    manager = workspace.channel_manager
    manager.channels.append(channel)
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.workspace_projector.get_available_channels",
        lambda: ("boot-race",),
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager._CHANNEL_START_STOP_TIMEOUT",
        0.01,
    )
    api = PluginApi("boot-plugin", {}, {"id": "boot-plugin"})
    api.set_registry(fresh_registry)
    instance = PluginInstance("boot-plugin")
    api.bind_instance(instance)
    api.register_channel(_BootChannel)
    await manager.start_all()
    await channel.entered.wait()
    start_tasks = set(manager._start_tasks)
    try:
        await fresh_registry.projector.project(
            "channel",
            "boot-race",
            "boot-plugin",
        )
        report = await instance.dispose(UnloadMode.UNLOAD)
        if ignore_cancel:
            assert not report.quiescent
            assert not report.clean
            assert report.needs_restart
            assert any("startup is still pending" in e for e in report.errors)
            assert manager.channels == [channel]
            assert start_tasks <= manager._start_tasks
            assert instance._runtime
            assert channel.stops == 0
        else:
            assert report.clean and report.quiescent
            assert all(task.done() for task in start_tasks)
            assert not manager.channels
            assert channel.stops == 1
        channel.release.set()
        await asyncio.gather(*start_tasks, return_exceptions=True)
        if ignore_cancel:
            report = await instance.dispose(UnloadMode.UNLOAD)
            assert report.clean and report.quiescent
            assert not manager.channels
        assert not channel.alive
    finally:
        channel.release.set()
        await asyncio.gather(*start_tasks, return_exceptions=True)
        await manager.stop_all()


@pytest.mark.asyncio
async def test_unload_removes_plugin_manifest(
    tmp_path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.constant.WORKING_DIR",
        tmp_path / "work",
    )
    root = tmp_path / "manifest-p"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "manifest-p",
                "version": "1.0.0",
                "name": "M",
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        "    def register(self, api):\n"
        "        pass\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    loader = PluginLoader(plugin_dirs=[tmp_path])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((root / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(manifest, root)
    assert "manifest-p" in fresh_registry.get_all_plugin_manifests()
    await loader.unload_plugin(
        "manifest-p",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert "manifest-p" not in fresh_registry.get_all_plugin_manifests()


class _NamedHook(HookBase):
    phase = Phase.PRE_DISPATCH
    name = "named-hook"


def test_hook_unregister_and_collision():
    workspace = FakeWorkspace("a")
    hook = _NamedHook()
    hook.owner_plugin_id = "plug"
    workspace.plugins.hook_registry.register(hook)
    with pytest.raises(ValueError, match="plugin 'plug'"):
        workspace.plugins.hook_registry.register(_NamedHook())
    assert workspace.plugins.hook_registry.unregister("named-hook")
    workspace.plugins.hook_registry.register(_NamedHook())


@pytest.fixture
async def channel_plugin(tmp_path, monkeypatch, fresh_registry):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    registry = fresh_registry
    live = []
    registry.projector = WorkspaceProjector(live_workspaces=lambda: live)
    entered, release = asyncio.Event(), asyncio.Event()
    state = SimpleNamespace(stop_fails=False, channel=None)

    class BlockingChannel(BaseChannel):
        channel = "projection-race"
        uses_manager_queue = False

        def __init__(self):
            self.alive = False
            self.starts = 0
            self.stops = 0
            state.channel = self

        @classmethod
        def from_config(cls, **_kwargs):
            return cls()

        async def start(self):
            self.starts += 1
            self.alive = True
            entered.set()
            await release.wait()

        async def stop(self):
            self.stops += 1
            if state.stop_fails:
                raise RuntimeError("connection still alive")
            self.alive = False

        def set_enqueue(self, _callback):
            return None

    monkeypatch.setattr(
        builtins,
        "_qwenpaw_projection_race_channel",
        BlockingChannel,
        raising=False,
    )
    for module in (
        "qwenpaw.plugins.workspace_projector",
        "qwenpaw.app.channels.manager",
    ):
        monkeypatch.setattr(
            f"{module}.get_available_channels",
            lambda: ("projection-race",),
        )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.get_channel_registry",
        lambda: {
            key: row.channel_class
            for key, row in registry.get_registered_channels().items()
        },
    )
    root = tmp_path / "plugin"
    root.mkdir()
    data = {
        "id": "projection-race",
        "name": "Projection race",
        "version": "1.0.0",
        "entry": {"backend": "main.py"},
    }
    (root / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "main.py").write_text(
        "import builtins\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        channel = builtins._qwenpaw_projection_race_channel\n"
        "        api.register_channel(channel)\n"
        "plugin = Plugin()\n",
        encoding="utf-8",
    )
    loader = PluginLoader([tmp_path])
    loader.registry = registry
    record = await loader.load_plugin(PluginManifest.from_dict(data), root)
    assert record.status == "active"
    workspace = FakeWorkspace(
        "new-workspace",
        SimpleNamespace(
            channels=SimpleNamespace(
                __pydantic_extra__={
                    "projection-race": SimpleNamespace(enabled=True),
                },
            ),
        ),
    )
    live.append(workspace)
    case = SimpleNamespace(
        loader=loader,
        registry=registry,
        workspace=workspace,
        entered=entered,
        release=release,
        state=state,
        root=root,
        manifest=PluginManifest.from_dict(data),
        live=live,
    )
    yield case
    release.set()
    state.stop_fails = False
    if loader.get_loaded_plugin("projection-race") is not None:
        await loader.unload_plugin("projection-race")


def _start_workspace(case):
    return asyncio.create_task(
        MultiAgentManager._fire_workspace_created_hooks(
            {"agent_id": case.workspace.agent_id, "workspace": case.workspace},
        ),
    )


@pytest.mark.asyncio
async def test_retiring_workspace_waits_for_start_and_blocks_late_hook(
    channel_plugin,
):
    case = channel_plugin
    projection = _start_workspace(case)
    await asyncio.wait_for(case.entered.wait(), timeout=2)
    retiring = asyncio.create_task(
        case.registry.projector.revoke_workspace(case.workspace),
    )
    try:
        done, _pending = await asyncio.wait({retiring}, timeout=0.1)
        assert not done, "Retiring workspace must wait for channel startup"
        case.release.set()
        await asyncio.wait_for(projection, timeout=2)
        await asyncio.wait_for(retiring, timeout=2)
        channel = case.state.channel
        assert channel.stops == 1
        assert not channel.alive
        assert not case.workspace.channel_manager.channels
        assert case.registry.projector._intents
        assert case.loader.get_loaded_plugin("projection-race") is not None
        await asyncio.wait_for(_start_workspace(case), timeout=2)
        assert case.state.channel is channel
        assert channel.starts == 1
        assert not case.workspace.channel_manager.channels
    finally:
        case.release.set()
        await asyncio.gather(projection, retiring, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_fails", [False, True])
async def test_unload_waits_for_new_workspace_start_and_retains_failed_stop(
    channel_plugin,
    stop_fails,
):
    case = channel_plugin
    case.state.stop_fails = stop_fails
    projection = _start_workspace(case)
    await asyncio.wait_for(case.entered.wait(), timeout=2)
    unloading = asyncio.create_task(
        case.loader.unload_plugin("projection-race"),
    )
    try:
        done, _pending = await asyncio.wait({unloading}, timeout=0.1)
        assert (
            not done
        ), "Unload must not report success during channel startup"
        assert case.loader.get_loaded_plugin("projection-race") is not None
        case.release.set()
        await asyncio.wait_for(projection, timeout=2)
        report = await asyncio.wait_for(unloading, timeout=2)
        channel = case.state.channel
        assert channel.starts == 1
        assert channel.stops == 1
        assert report.quiescent is not stop_fails
        if stop_fails:
            assert not report.clean
            assert channel.alive
            assert case.workspace.channel_manager.channels == [channel]
            assert case.registry.projector._intents
            assert (
                case.loader.lifecycle.get_instance("projection-race")
                is not None
            )
            case.state.stop_fails = False
            report = await case.loader.unload_plugin("projection-race")
        assert report.clean and report.quiescent
        assert not channel.alive
        assert not case.workspace.channel_manager.channels
        assert not case.registry.projector._intents
        assert case.loader.get_loaded_plugin("projection-race") is None
    finally:
        case.release.set()
        await asyncio.gather(projection, unloading, return_exceptions=True)


@pytest.mark.asyncio
async def test_old_hook_cannot_project_new_plugin_generation(channel_plugin):
    case = channel_plugin
    old_hooks = case.registry.get_workspace_created_hooks()
    report = await case.loader.unload_plugin("projection-race")
    assert report.clean and report.quiescent
    case.live.clear()
    record = await case.loader.load_plugin(case.manifest, case.root)
    assert record.status == "active"
    case.live.append(case.workspace)
    await MultiAgentManager._run_workspace_hooks(
        old_hooks,
        {"workspace": case.workspace},
        "workspace_created",
    )
    assert case.state.channel is None
    assert not case.workspace.channel_manager.channels
    case.release.set()
    await asyncio.wait_for(_start_workspace(case), timeout=2)
    assert case.state.channel.starts == 1
    assert case.state.channel.alive
    report = await case.loader.unload_plugin("projection-race")
    assert report.clean and report.quiescent
    assert not case.state.channel.alive
    assert not case.workspace.channel_manager.channels


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_projection", [False, True])
async def test_pending_projection_timeout_preserves_cleanup_for_retry(
    channel_plugin,
    monkeypatch,
    cancel_projection,
):
    case = channel_plugin
    monkeypatch.setattr(
        "qwenpaw.plugins.workspace_projector.PROJECTION_DRAIN_TIMEOUT",
        0.01,
    )
    projection = _start_workspace(case)
    await asyncio.wait_for(case.entered.wait(), timeout=2)
    try:
        if cancel_projection:
            projection.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(projection, timeout=2)
        report = await asyncio.wait_for(
            case.loader.unload_plugin("projection-race"),
            timeout=2,
        )
        assert not report.clean and not report.quiescent
        assert case.state.channel.alive
        assert case.workspace.channel_manager.channels == [case.state.channel]
        assert case.registry.projector._intents
        assert case.loader.get_loaded_plugin("projection-race") is not None
        assert case.loader.lifecycle.get_instance(
            "projection-race",
        ).has_runtime_ledger()
        case.release.set()
        if not cancel_projection:
            await asyncio.wait_for(projection, timeout=2)
        report = await asyncio.wait_for(
            case.loader.unload_plugin("projection-race"),
            timeout=2,
        )
        assert report.clean and report.quiescent
        assert not case.state.channel.alive
        assert not case.workspace.channel_manager.channels
        assert not case.registry.projector._intents
    finally:
        case.release.set()
        await asyncio.gather(projection, return_exceptions=True)
