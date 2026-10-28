# -*- coding: utf-8 -*-
"""Offline MCP upgrade uses raw evidence and the actual plugin transaction."""

# pylint: disable=protected-access

import asyncio
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import socket
import subprocess

import pytest
import yaml

from qwenpaw.app import mcp_plugin_migration as migration
from qwenpaw.plugins.testing import PluginTestHost

from tests.unit.plugins.mcp.fixtures import Peer, card

PLUGIN_ID = "qwenpaw-mcp"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/mcp_plugin_upgrade"
SECRET = "synthetic-private-endpoint-and-token"


def entry(name):
    value = getattr(migration, name, None)
    assert callable(value), f"Task6 upgrade entrypoint {name} is missing"
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def seed(root, rows, *, plugins=None):
    profiles = {}
    for name, path, data, cards, enabled in rows:
        profiles[name] = {
            "id": name,
            "workspace_dir": str(path),
            "enabled": enabled,
        }
        write_json(path / "agent.json", {"id": name, "name": name, **data})
        for value in cards:
            target = path / "drivers/mcp" / (value["name"] + ".yaml")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(yaml.safe_dump(value), encoding="utf-8")
    config = root / "config.json"
    write_json(
        config,
        {"agents": {"profiles": profiles}, "plugins": plugins or {}},
    )
    return config


def inventory(root):
    return entry("inventory_mcp_usage")(
        config_path=root / "config.json",
        plugins_dir=root / "plugins",
    )


def bytes_under(path):
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


@pytest.fixture(autouse=True)
def prohibit_network_and_installers(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Upgrade attempted network access")

    original = subprocess.Popen

    def deny_install(args, *values, **kwargs):
        if "install" in args and ("pip" in args or "uv" in str(args[0])):
            raise AssertionError("Upgrade attempted dependency installation")
        return original(args, *values, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(subprocess, "Popen", deny_install)
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("UV_OFFLINE", "1")


def test_raw_inventory_keeps_inactive_and_damaged_siblings_without_writes(
    tmp_path,
):
    root = tmp_path / "host"
    custom = tmp_path / "custom-inactive"
    damaged = tmp_path / "damaged"
    source = card("retained", enabled=False)
    source["credentials"] = {"token": {"kind": "static", "ref": SECRET}}
    seed(
        root,
        [
            ("inactive", custom, {}, [source], False),
            ("damaged", damaged, {}, [], False),
        ],
    )
    (damaged / "agent.json").write_text('{"url":"' + SECRET, encoding="utf-8")
    before = bytes_under(tmp_path)
    snapshot = inventory(root)
    decision = migration.classify_mcp_usage(snapshot)
    assert decision.status == "configured"
    assert decision.workspace_statuses == {
        "inactive": "configured",
        "damaged": "needs_review",
    }
    assert bytes_under(tmp_path) == before
    assert SECRET not in repr(decision.reasons)


@pytest.mark.parametrize("version", [None, 0, 1, 2])
async def test_unused_twice_never_installs_loads_or_checks_dependencies(
    tmp_path,
    monkeypatch,
    version,
):
    data = (
        {"config": {}, "cards": []}
        if version is None
        else json.loads(
            (FIXTURES / f"default-v{version}.json").read_text(),
        )
    )
    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, data["config"], data["cards"], True)])
    before = bytes_under(workspace)
    async with PluginTestHost(root) as host:

        async def forbidden(*_args, **_kwargs):
            raise AssertionError(
                "Unused upgrade reached installer/dependency gate",
            )

        monkeypatch.setattr(host._loader, "install_plugin_files", forbidden)
        monkeypatch.setattr(
            host._loader,
            "_ensure_dependencies_installed",
            forbidden,
        )
        for _ in range(2):
            result = await entry("ensure_mcp_plugin_for_upgrade")(
                inventory(root),
                loader=host._loader,
            )
            assert result.status in {"unchanged", "skipped"}
            assert result.decision.status == "unused"
            assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
            assert not (root / "plugins" / PLUGIN_ID).exists()
            assert (
                json.loads((root / "config.json").read_text())["plugins"]
                .get(
                    PLUGIN_ID,
                    {},
                )
                .get("enabled")
                is not True
            )
        assert bytes_under(workspace) == before


async def test_configured_upgrade_installs_once_and_uses_actual_sdk_bridge(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    workspace = root / "workspaces/custom-workspace"
    legacy = {
        "mcp": {
            "migration_version": 0,
            "clients": {
                "custom": {
                    "name": "Custom",
                    "enabled": True,
                    "transport": "stdio",
                    "command": "synthetic-mcp",
                    "args": ["--offline"],
                    "tools": ["echo"],
                    "env": {"TOKEN": "${UPGRADE_TOKEN}"},
                },
            },
        },
    }
    enabled = card("live", config={"tools": ["echo"]})
    disabled = card(
        "disabled",
        enabled=False,
        credentials={
            "private": {"kind": "static", "ref": SECRET},
        },
        policy={"default_effect": "deny"},
    )
    seed(root, [("test", workspace, legacy, [enabled, disabled], True)])
    before = bytes_under(workspace)
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(
        root,
        workspace_dirs={"test": "custom-workspace"},
    ) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        result = await ensure(inventory(root), loader=host._loader)
        assert result.status == "installed"
        assert result.decision.status == "configured"
        with pytest.raises(FrozenInstanceError):
            result.status = "failed"
        assert (root / "plugins" / PLUGIN_ID / "plugin.json").is_file()
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]["enabled"]
            is True
        )
        assert bytes_under(workspace) == before
        assert not peer.opens  # Registration precedes source activation.
        installed = bytes_under(root / "plugins" / PLUGIN_ID)
        marker = root / "plugins/.mcp-plugin-migration.json"
        marker_before = marker.read_bytes()
        assert SECRET not in marker_before.decode()
        again = await ensure(inventory(root), loader=host._loader)
        assert again.status == "unchanged"
        assert bytes_under(root / "plugins" / PLUGIN_ID) == installed
        assert marker.read_bytes() == marker_before
        await host._workspace("test")
        await host._loader.activate_all_loaded()
        await host.open_driver(enabled)
        rows = await host.list_driver_capabilities("live")
        assert (
            rows[0]["capability_id"] == "driver://mcp/live/tools/echo#invoke"
        )
        assert (await host.call_driver("live", "echo", {"value": 42})).content[
            0
        ].text == "ok"
        assert peer.calls == [("echo", {"value": 42})]
        assert SECRET not in repr(result.diagnostics)


@pytest.mark.parametrize("installed", [False, True])
async def test_explicit_disable_survives_upgrade_without_installer_or_gate(
    tmp_path,
    monkeypatch,
    installed,
):
    import shutil

    from qwenpaw.plugins.loader import PluginLoader
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(
        root,
        [("test", workspace, {}, [card()], True)],
        plugins={
            PLUGIN_ID: {"enabled": False, "retained_setting": 17},
        },
    )
    if installed:
        shutil.copytree(PLUGIN, root / "plugins" / PLUGIN_ID)
    before = bytes_under(root)
    async with PluginTestHost(root) as host:

        async def forbidden(*_args, **_kwargs):
            raise AssertionError(
                "Explicit off reached installer/dependency gate",
            )

        monkeypatch.setattr(PluginLoader, "install_plugin_files", forbidden)
        monkeypatch.setattr(
            PluginLoader,
            "_ensure_dependencies_installed",
            forbidden,
        )
        result = await entry("ensure_mcp_plugin_for_upgrade")(
            inventory(root),
            loader=host._loader,
        )
        assert result.status == "skipped"
        assert result.decision.status == "explicit_off"
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
        after = bytes_under(root)
        assert all(after.get(path) == value for path, value in before.items())


async def test_actual_uninstall_stays_off_until_explicit_reinstall(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    peer = Peer()
    peer.install(monkeypatch)

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    ensure = entry("ensure_mcp_plugin_for_upgrade")
    async with PluginTestHost(root) as host:
        assert (
            await ensure(inventory(root), loader=host._loader)
        ).status == "installed"
        assert (await host.uninstall(PLUGIN_ID)).quiescent
        assert not (root / "plugins" / PLUGIN_ID).exists()
        assert (
            PLUGIN_ID
            not in json.loads((root / "config.json").read_text())["plugins"]
        )
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status == "skipped"
        assert result.decision.status == "explicit_off"
        assert not (root / "plugins" / PLUGIN_ID).exists()
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
        live_workspace = await host._workspace("test")
        runtime = await create_driver_service(
            live_workspace,
            None,
            lambda value: live_workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            assert runtime.manager is None
            assert not peer.opens
            assert (await host.install(PLUGIN)).ok
            assert [
                row.capability_id for row in await runtime.list_capabilities()
            ] == [
                "driver://mcp/same/tools/echo#invoke",
            ]
            assert len(peer.opens) == 1
        finally:
            await runtime.shutdown_all()
    async with PluginTestHost(root) as host:
        result = await ensure(inventory(root), loader=host._loader)
        assert result.status == "unchanged"
        assert result.decision.status == "configured"
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None


async def test_existing_user_plugin_version_and_bytes_are_never_overwritten(
    tmp_path,
):
    import shutil

    from tests.unit.plugins.mcp.fixtures import PLUGIN

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    target = root / "plugins" / PLUGIN_ID
    shutil.copytree(PLUGIN, target)
    manifest = json.loads((target / "plugin.json").read_text())
    manifest["version"] = "99.0.0"
    write_json(target / "plugin.json", manifest)
    (target / "user-note.txt").write_text(
        "Keep my custom version",
        encoding="utf-8",
    )
    before = bytes_under(target)
    async with PluginTestHost(root) as host:
        result = await entry("ensure_mcp_plugin_for_upgrade")(
            inventory(root),
            loader=host._loader,
        )
        assert result.status == "unchanged"
        assert bytes_under(target) == before
        assert (
            host._loader.get_loaded_plugin(PLUGIN_ID).manifest.version
            == "99.0.0"
        )


async def test_missing_dependencies_fail_safely_without_enabled_commit(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.dependency_gate import GateDecision
    from qwenpaw.plugins.loader import PluginLoader

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    before = bytes_under(workspace)
    permissions = []

    async def unavailable(_self, _path, _plugin_id, *, allow_install=False):
        permissions.append(allow_install)
        return GateDecision(
            allow_install=allow_install,
            already_satisfied=False,
            missing=["synthetic-missing-dependency"],
            reason="dependency unavailable " + SECRET,
        )

    monkeypatch.setattr(
        PluginLoader,
        "_ensure_dependencies_installed",
        unavailable,
    )
    async with PluginTestHost(root) as host:
        result = await entry("ensure_mcp_plugin_for_upgrade")(
            inventory(root),
            loader=host._loader,
        )
        assert result.status == "failed"
        assert result.diagnostics
        assert SECRET not in repr(result)
        assert permissions and not any(permissions)
        assert not (root / "plugins" / PLUGIN_ID).exists()
        assert (
            json.loads((root / "config.json").read_text())["plugins"]
            .get(
                PLUGIN_ID,
                {},
            )
            .get("enabled")
            is not True
        )
        assert bytes_under(workspace) == before


async def test_concurrent_upgrades_share_one_actual_install(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    original = PluginLoader.install_plugin_files
    installs = []

    async def observe(self, *args, **kwargs):
        installs.append(args[0])
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(PluginLoader, "install_plugin_files", observe)
    async with PluginTestHost(root) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        snapshot = inventory(root)
        results = await asyncio.wait_for(
            asyncio.gather(
                *(ensure(snapshot, loader=host._loader) for _ in range(6)),
            ),
            15,
        )
        assert [result.status for result in results].count("installed") == 1
        assert all(
            result.status in {"installed", "unchanged"} for result in results
        )
        assert len(installs) == 1
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None


async def test_copy_interruption_leaves_no_half_install_and_recovers(
    tmp_path,
    monkeypatch,
):
    import shutil

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    before = bytes_under(workspace)
    original = shutil.copytree
    failed = []

    def interrupt(source, destination, *args, **kwargs):
        if Path(destination).name == PLUGIN_ID and not failed:
            failed.append(True)
            Path(destination).mkdir(parents=True)
            (Path(destination) / "partial.py").write_text(
                "partial",
                encoding="utf-8",
            )
            raise OSError(SECRET)
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", interrupt)
    async with PluginTestHost(root) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        failed_result = await ensure(inventory(root), loader=host._loader)
        assert failed_result.status == "failed"
        assert SECRET not in repr(failed_result)
        assert not (root / "plugins" / PLUGIN_ID).exists()
        assert bytes_under(workspace) == before
        result = await ensure(inventory(root), loader=host._loader)
        assert result.status == "installed"
        assert (root / "plugins" / PLUGIN_ID / "plugin.json").is_file()
        assert bytes_under(workspace) == before


def test_malformed_root_and_intent_are_reviewed_without_repair(tmp_path):
    root = tmp_path / "host"
    root.mkdir()
    config = root / "config.json"
    config.write_text('{"private":"' + SECRET, encoding="utf-8")
    before = bytes_under(root)
    decision = migration.classify_mcp_usage(inventory(root))
    assert decision.status == "needs_review"
    assert SECRET not in repr(decision)
    assert bytes_under(root) == before
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    intent = root / "plugins/.plugin-intents" / (PLUGIN_ID + ".json")
    intent.parent.mkdir(parents=True)
    intent.write_text('{"private":"' + SECRET, encoding="utf-8")
    before = bytes_under(root)
    decision = migration.classify_mcp_usage(inventory(root))
    assert decision.status in {"needs_review", "explicit_off"}
    assert SECRET not in repr(decision)
    assert bytes_under(root) == before


async def test_settings_commit_interruption_resumes_owned_files_on_restart(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.config import utils

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    before = bytes_under(workspace)
    ensure = entry("ensure_mcp_plugin_for_upgrade")
    original = utils.mutate_config
    failures = []

    def interrupt(*args, **kwargs):
        if not failures:
            failures.append(True)
            raise OSError(SECRET)
        return original(*args, **kwargs)

    async with PluginTestHost(root) as host:
        with monkeypatch.context() as patch:
            patch.setattr(utils, "mutate_config", interrupt)
            result = await ensure(inventory(root), loader=host._loader)
        assert result.status == "failed"
        assert SECRET not in repr(result)
        assert failures
        assert (
            json.loads((root / "config.json").read_text())["plugins"]
            .get(
                PLUGIN_ID,
                {},
            )
            .get("enabled")
            is not True
        )
        assert bytes_under(workspace) == before
    async with PluginTestHost(root) as host:
        result = await ensure(inventory(root), loader=host._loader)
        assert result.status in {"installed", "unchanged"}
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]["enabled"]
            is True
        )
        assert bytes_under(workspace) == before


async def test_marker_commit_interruption_never_reports_success_then_recovers(
    tmp_path,
    monkeypatch,
):
    import os

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    original = os.replace
    failures = []

    def interrupt(source, target, *args, **kwargs):
        if (
            Path(target).name == ".mcp-plugin-migration.json"
            and not failures
            and json.loads(Path(source).read_text()).get("stage")
            == "completed"
        ):
            failures.append(True)
            raise OSError(SECRET)
        return original(source, target, *args, **kwargs)

    async with PluginTestHost(root) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", interrupt)
            result = await ensure(inventory(root), loader=host._loader)
        assert failures
        assert result.status == "failed"
        assert SECRET not in repr(result)
        result = await ensure(inventory(root), loader=host._loader)
        assert result.status in {"installed", "unchanged"}
        marker = root / "plugins/.mcp-plugin-migration.json"
        assert json.loads(marker.read_text())["stage"] == "completed"


async def test_cancelled_upgrade_does_not_complete_or_block_later_retry(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    original = PluginLoader._ensure_dependencies_installed
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original(self, *args, **kwargs)

    async with PluginTestHost(root) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        with monkeypatch.context() as patch:
            patch.setattr(
                PluginLoader,
                "_ensure_dependencies_installed",
                blocked,
            )
            task = asyncio.create_task(
                ensure(inventory(root), loader=host._loader),
            )
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        result = await asyncio.wait_for(
            ensure(inventory(root), loader=host._loader),
            10,
        )
        assert result.status in {"installed", "unchanged"}
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None


async def prepare(host):
    import importlib

    module = importlib.import_module("qwenpaw.app.mcp_plugin_upgrade")
    function = getattr(module, "prepare_startup_plugins", None)
    assert callable(function), "Task6 production startup helper is missing"
    return await function(
        host._loader,
        host._workspace_manager,
        app=host._http_app,
    )


async def test_phase1_registers_generic_driver_before_workspace_publication(
    tmp_path,
):
    import shutil

    from tests.unit.plugins.sdk_author_fixture import make_plugin

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [], True)])
    source = make_plugin(
        tmp_path,
        """
from qwenpaw.plugins.drivers import DriverProtocolSpec
class Connection:
    def __init__(self, context, source):
        raise AssertionError("Phase1 constructed a transport")
class Plugin:
    def register(self, plugin):
        plugin.register_driver_protocol(DriverProtocolSpec(
            "sampleproto", lambda source: None, Connection))
plugin = Plugin()
""",
        ["drivers"],
    )
    manifest = json.loads((source / "plugin.json").read_text())
    manifest.update({"id": "arbitrary-driver-owner", "type": "general"})
    manifest["sdk"]["version"] = "1.1.0"
    write_json(source / "plugin.json", manifest)
    shutil.copytree(source, root / "plugins/arbitrary-driver-owner")
    for plugin_id, plugin_type in (
        ("traditional-channel", "channel"),
        ("phase2-general", "general"),
    ):
        destination = root / "plugins" / plugin_id
        destination.mkdir()
        write_json(
            destination / "plugin.json",
            {
                "id": plugin_id,
                "version": "1.0.0",
                "type": plugin_type,
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": []},
            },
        )
        (destination / "main.py").write_text(
            "class Plugin:\n    def register(self, context):\n        pass\n"
            "plugin = Plugin()\n",
            encoding="utf-8",
        )
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.decision.status == "unused"
        assert (
            host._loader.registry.get_workspace_manager()
            is host._workspace_manager
        )
        assert not host._workspaces
        assert "sampleproto" in host._loader.registry._driver_protocols
        assert (
            host._loader.get_loaded_plugin("traditional-channel") is not None
        )
        assert host._loader.get_loaded_plugin("phase2-general") is None
        assert (
            host._loader.get_loaded_plugin("arbitrary-driver-owner")
            is not None
        )
        assert host._http_app.state.plugin_loader is host._loader
        assert host._http_app.state.plugin_registry is host._loader.registry


@pytest.mark.parametrize("operation", ["upsert", "refresh"])
async def test_nonempty_facade_uses_shared_resolver_after_unused_inventory(
    tmp_path,
    monkeypatch,
    operation,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service
    from qwenpaw.drivers.contracts import DriverCard

    root = tmp_path / "host"
    workspace_dir = root / "workspaces/test"
    seed(root, [("test", workspace_dir, {}, [], True)])
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        assert (await prepare(host)).decision.status == "unused"
        workspace = await host._workspace("test")
        runtime = await create_driver_service(
            workspace,
            None,
            lambda value: workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            assert runtime.manager is None
            assert await runtime.list_capabilities() == []
            assert not (root / "plugins" / PLUGIN_ID).exists()
            value = DriverCard(**card("late"))
            if operation == "upsert":
                await runtime.upsert_driver(value)
            else:
                await runtime.card_store.save(value)
                await runtime.refresh_driver("late")
            assert (root / "plugins" / PLUGIN_ID / "plugin.json").is_file()
            assert runtime.manager is not None
            rows = await runtime.list_capabilities()
            assert [row.capability_id for row in rows] == [
                "driver://mcp/late/tools/echo#invoke",
            ]
            assert len(peer.opens) == 1
        finally:
            await runtime.shutdown_all()


def test_legacy_root_config_without_profiles_is_configured_and_readonly(
    tmp_path,
):
    root = tmp_path / "host"
    write_json(
        root / "config.json",
        {
            "mcp": {
                "clients": {
                    "custom": {
                        "name": "Legacy custom",
                        "transport": "stdio",
                        "command": "synthetic-mcp",
                        "enabled": False,
                    },
                },
            },
        },
    )
    before = bytes_under(root)
    snapshot = inventory(root)
    assert migration.classify_mcp_usage(snapshot).status == "configured"
    assert any(row.config.get("mcp") for row in snapshot.workspaces)
    assert bytes_under(root) == before


async def test_malformed_root_startup_helper_fails_without_auto_repair(
    tmp_path,
):
    root = tmp_path / "host"
    root.mkdir()
    (root / "config.json").write_text(
        '{"private":"' + SECRET,
        encoding="utf-8",
    )
    before = bytes_under(root)
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status in {"needs_review", "failed"}
        assert SECRET not in repr(result)
        assert bytes_under(root) == before
        assert not host._loader.get_all_loaded_plugins()


async def test_startup_refreshes_settings_after_install_before_phase1_filter(
    tmp_path,
):
    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status == "installed"
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]["enabled"]
            is True
        )
        assert "mcp" in host._loader.registry._driver_protocols
        assert not host._workspaces


async def test_valid_sibling_install_does_not_activate_ambiguous_workspace(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service

    root = tmp_path / "host"
    safe = root / "workspaces/safe"
    ambiguous = root / "workspaces/ambiguous"
    seed(
        root,
        [
            ("safe", safe, {}, [card("safe")], True),
            (
                "ambiguous",
                ambiguous,
                {"mcp": {"unknown": SECRET}},
                [card("blocked")],
                True,
            ),
        ],
    )
    before = bytes_under(ambiguous)
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.decision.workspace_statuses == {
            "safe": "configured",
            "ambiguous": "needs_review",
        }
        workspace = await host._workspace("ambiguous")
        runtime = await create_driver_service(
            workspace,
            None,
            lambda value: workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            assert runtime.manager is None
            assert not peer.opens
            assert bytes_under(ambiguous) == before
        finally:
            await runtime.shutdown_all()


async def test_newer_explicit_off_during_upgrade_wins_over_stale_snapshot(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.settings import persist_plugin_settings

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    original = PluginLoader._ensure_dependencies_installed
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(self, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original(self, *args, **kwargs)

    async with PluginTestHost(root) as host:
        ensure = entry("ensure_mcp_plugin_for_upgrade")
        with monkeypatch.context() as patch:
            patch.setattr(
                PluginLoader,
                "_ensure_dependencies_installed",
                blocked,
            )
            task = asyncio.create_task(
                ensure(inventory(root), loader=host._loader),
            )
            try:
                await asyncio.wait_for(entered.wait(), 3)
                persist_plugin_settings(PLUGIN_ID, enabled=False)
            finally:
                release.set()
            result = await asyncio.wait_for(task, 10)
        assert result.status == "skipped"
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]["enabled"]
            is False
        )
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None


async def test_malformed_marker_does_not_overwrite_or_enable_code(
    tmp_path,
):
    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [card()], True)])
    marker = root / "plugins/.mcp-plugin-migration.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"private":"' + SECRET, encoding="utf-8")
    before = bytes_under(root)
    async with PluginTestHost(root) as host:
        result = await entry("ensure_mcp_plugin_for_upgrade")(
            inventory(root),
            loader=host._loader,
        )
        assert result.status in {"needs_review", "failed"}
        assert SECRET not in repr(result)
        assert bytes_under(root) == before
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None


async def test_nonempty_facade_cannot_resurrect_explicitly_disabled_plugin(
    tmp_path,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service
    from qwenpaw.drivers.contracts import DriverCard
    from qwenpaw.drivers.errors import UnsupportedProtocolError

    root = tmp_path / "host"
    seed(
        root,
        [("test", root / "workspaces/test", {}, [], True)],
        plugins={
            PLUGIN_ID: {"enabled": False},
        },
    )
    async with PluginTestHost(root) as host:
        assert (await prepare(host)).decision.status == "explicit_off"
        workspace = await host._workspace("test")
        runtime = await create_driver_service(
            workspace,
            None,
            lambda value: workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            with pytest.raises(UnsupportedProtocolError):
                await runtime.upsert_driver(DriverCard(**card("later")))
            assert runtime.manager is None
            assert not (root / "plugins" / PLUGIN_ID).exists()
            assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
        finally:
            await runtime.shutdown_all()


@pytest.mark.parametrize("tools", [None, [], ["echo"]])
async def test_real_workspace_conversion_keeps_disabled_custom_legacy_source(
    tmp_path,
    monkeypatch,
    tools,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service

    root = tmp_path / "host"
    workspace_dir = root / "workspaces/test"
    legacy = {
        "mcp": {
            "migration_version": 0,
            "clients": {
                "private": {
                    "name": "Private source",
                    "enabled": False,
                    "transport": "stdio",
                    "command": "synthetic-mcp",
                    "args": ["--custom"],
                    "tools": tools,
                    "env": {},
                },
            },
        },
    }
    seed(root, [("test", workspace_dir, legacy, [], True)])
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        assert (await prepare(host)).status == "installed"
        workspace = await host._workspace("test")
        runtime = await create_driver_service(
            workspace,
            None,
            lambda value: workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            custom = await runtime.card_store.load("private", protocol="mcp")
            assert custom.enabled is False
            assert custom.endpoint["command"] == "synthetic-mcp"
            assert custom.endpoint["args"] == ["--custom"]
            assert custom.config.get("tools") == tools
            assert runtime.manager is None
            assert runtime.watcher is not None
            assert not peer.opens
            raw = json.loads((workspace_dir / "agent.json").read_text())
            assert raw["mcp"]["migration_version"] == 2
            assert raw["mcp"]["clients"]["private"]["enabled"] is False
            before = bytes_under(workspace_dir / "drivers/mcp")
            await runtime.activate_registered_protocols()
            assert bytes_under(workspace_dir / "drivers/mcp") == before
        finally:
            await runtime.shutdown_all()


async def test_startup_keeps_preflight_legacy_evidence_after_profile_creation(
    tmp_path,
):
    from qwenpaw.app.mcp_plugin_upgrade import prepare_startup_plugins

    root = tmp_path / "host"
    write_json(
        root / "config.json",
        {
            "mcp": {
                "clients": {
                    "custom": {
                        "name": "Legacy custom",
                        "transport": "stdio",
                        "command": "synthetic-mcp",
                        "enabled": False,
                    },
                },
            },
        },
    )
    snapshot = inventory(root)
    seed(root, [("default", root / "workspaces/default", {}, [], True)])
    async with PluginTestHost(root) as host:
        result = await prepare_startup_plugins(
            host._loader,
            host._workspace_manager,
            app=host._http_app,
            snapshot=snapshot,
        )
        assert result.status == "installed"
        assert result.decision.status == "configured"
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None
        assert not host._workspaces


async def test_preinstalled_enabled_plugin_with_no_sources_remains_registered(
    tmp_path,
):
    from qwenpaw.app.workspace.service_factories import create_driver_service
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    root = tmp_path / "host"
    seed(root, [("test", root / "workspaces/test", {}, [], True)])
    async with PluginTestHost(root) as host:
        assert (await host.install(PLUGIN)).ok
    target = root / "plugins" / PLUGIN_ID
    before = bytes_under(target)
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.decision.status == "unused"
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None
        assert "mcp" in host._loader.registry._driver_protocols
        assert bytes_under(target) == before
        workspace = await host._workspace("test")
        runtime = await create_driver_service(
            workspace,
            None,
            lambda value: workspace._service_manager.services.__setitem__(
                "driver_manager",
                value,
            ),
        )
        try:
            assert runtime.manager is None
            assert runtime.watcher is None
            assert await runtime.list_capabilities() == []
        finally:
            await runtime.shutdown_all()


def test_legacy_root_invalid_mcp_is_blocked_before_config_sanitization(
    tmp_path,
):
    root = tmp_path / "host"
    write_json(
        root / "config.json",
        {
            "mcp": {
                "clients": {
                    "private": {
                        "name": "Custom",
                        "transport": "streamable_http",
                        "url": SECRET,
                        "enabled": "ambiguous",
                    },
                },
            },
        },
    )
    before = bytes_under(root)
    snapshot = inventory(root)
    assert migration.classify_mcp_usage(snapshot).status == "needs_review"
    with pytest.raises(RuntimeError) as caught:
        entry("validate_mcp_upgrade_preflight")(snapshot)
    assert SECRET not in str(caught.value)
    assert bytes_under(root) == before


async def test_orphan_owned_install_without_global_marker_is_not_user_code(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.config import utils

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    workspace_before = bytes_under(workspace)

    def interrupt(*_args, **_kwargs):
        raise OSError("Synthetic settings commit interruption")

    async with PluginTestHost(root) as host:
        with monkeypatch.context() as patch:
            patch.setattr(utils, "mutate_config", interrupt)
            result = await entry("ensure_mcp_plugin_for_upgrade")(
                inventory(root),
                loader=host._loader,
            )
        assert result.status == "failed"
    target = root / "plugins" / PLUGIN_ID
    assert (target / ".plugin-install-origin.json").is_file()
    before = bytes_under(target)
    (root / "plugins/.mcp-plugin-migration.json").unlink()
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status in {"failed", "needs_review"}
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
        assert "mcp" not in host._loader.registry._driver_protocols
        assert bytes_under(target) == before
        assert bytes_under(workspace) == workspace_before
        assert (
            json.loads((root / "config.json").read_text())["plugins"]
            .get(
                PLUGIN_ID,
                {},
            )
            .get("enabled")
            is not True
        )


async def test_explicit_reinstall_retires_interrupted_upgrade_before_restart(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.config import utils
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    source = card("retained", config={"tools": ["echo"]})
    seed(root, [("test", workspace, {}, [source], True)])
    workspace_before = bytes_under(workspace)
    marker = root / "plugins/.mcp-plugin-migration.json"
    target = root / "plugins" / PLUGIN_ID
    peer = Peer()
    peer.install(monkeypatch)

    def interrupt(*_args, **_kwargs):
        raise OSError("Synthetic settings commit interruption")

    async with PluginTestHost(root) as host:
        with monkeypatch.context() as patch:
            patch.setattr(utils, "mutate_config", interrupt)
            result = await entry("ensure_mcp_plugin_for_upgrade")(
                inventory(root),
                loader=host._loader,
            )
        assert result.status == "failed"
        assert (target / ".plugin-install-origin.json").is_file()
        assert json.loads(marker.read_text())["stage"] != "completed"
        assert (await host.uninstall(PLUGIN_ID)).quiescent
        assert not target.exists()
        assert (await host.install(PLUGIN)).ok
        assert (
            await host.update_config(PLUGIN_ID, {"user_setting": "keep"})
        ).ok
        workspace_after = bytes_under(workspace)
        assert all(
            workspace_after.get(path) == value
            for path, value in workspace_before.items()
        )
    installed = bytes_under(target)
    config_before = json.loads((root / "config.json").read_text())["plugins"][
        PLUGIN_ID
    ]
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status == "unchanged"
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is not None
        assert "mcp" in host._loader.registry._driver_protocols
        assert bytes_under(target) == installed
        workspace_after = bytes_under(workspace)
        assert all(
            workspace_after.get(path) == value
            for path, value in workspace_before.items()
        )
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]
            == config_before
        )
        await host._workspace("test")
        await host._loader.activate_all_loaded()
        await host.open_driver(source)
        rows = await host.list_driver_capabilities("retained")
        assert [row["capability_id"] for row in rows] == [
            "driver://mcp/retained/tools/echo#invoke",
        ]
        assert (
            await host.call_driver("retained", "echo", {"value": 7})
        ).content[0].text == "ok"
        assert peer.calls == [("echo", {"value": 7})]


@pytest.mark.parametrize("tamper", ["receipt-json", "plugin-code"])
async def test_explicit_commit_receipt_requires_valid_json_and_matching_code(
    tmp_path,
    monkeypatch,
    tamper,
):
    from qwenpaw.config import utils
    from tests.unit.plugins.mcp.fixtures import PLUGIN

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card()], True)])
    original_workspace = bytes_under(workspace)
    target = root / "plugins" / PLUGIN_ID
    marker = root / "plugins/.mcp-plugin-migration.json"

    def interrupt(*_args, **_kwargs):
        raise OSError("Synthetic settings commit interruption")

    async with PluginTestHost(root) as host:
        with monkeypatch.context() as patch:
            patch.setattr(utils, "mutate_config", interrupt)
            result = await entry("ensure_mcp_plugin_for_upgrade")(
                inventory(root),
                loader=host._loader,
            )
        assert result.status == "failed"
        assert (target / ".plugin-install-origin.json").is_file()
        assert json.loads(marker.read_text())["stage"] != "completed"
        assert (await host.uninstall(PLUGIN_ID)).quiescent
        assert (await host.install(PLUGIN)).ok
        assert (
            await host.update_config(PLUGIN_ID, {"user_setting": "keep"})
        ).ok
    assert json.loads(marker.read_text())["stage"] != "completed"
    receipt = target / ".plugin-install-commit.json"
    assert (
        receipt.is_file()
    ), "Successful explicit install needs a durable receipt"
    if tamper == "receipt-json":
        receipt.write_text('{"private":"' + SECRET, encoding="utf-8")
    else:
        entrypoint = target / "plugin.py"
        entrypoint.write_text(
            entrypoint.read_text(encoding="utf-8")
            + "\n# Edited after commit\n",
            encoding="utf-8",
        )
    installed = bytes_under(target)
    config_before = json.loads((root / "config.json").read_text())["plugins"][
        PLUGIN_ID
    ]
    async with PluginTestHost(root) as host:
        result = await prepare(host)
        assert result.status in {"failed", "needs_review"}
        assert SECRET not in repr(result)
        assert host._loader.get_loaded_plugin(PLUGIN_ID) is None
        assert "mcp" not in host._loader.registry._driver_protocols
        assert bytes_under(target) == installed
        workspace_after = bytes_under(workspace)
        assert all(
            workspace_after.get(path) == value
            for path, value in original_workspace.items()
        )
        assert (
            json.loads((root / "config.json").read_text())["plugins"][
                PLUGIN_ID
            ]
            == config_before
        )
