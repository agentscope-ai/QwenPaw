# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Workspace revoke, occupancy, and per-channel start/stop."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.modes.base import AgentMode
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.lifecycle import PluginInstance, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.workspace_projector import (
    WorkspaceProjector,
    scan_owner_rows,
)
from qwenpaw.runtime.hooks import HookBase
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.slash_command_registry import CommandSpec
from qwenpaw.runtime.tool_registry import ToolDescriptor


@pytest.fixture()
def fresh_registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old


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
